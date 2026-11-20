"""Корзина. Ограничения каналов проверяются здесь (на сервере), а затем повторно при оформлении заказа."""
from apps.catalog import builder
from apps.catalog.models import Product
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.inventory.services import availability_map

from .models import Cart, CartItem

BOT_CHANNELS = {"telegram", "vk"}
WEB_SELLABLE = {Product.Type.BOUQUET, Product.Type.FLOWER, Product.Type.GREENERY, Product.Type.CARD, Product.Type.ADDON}
STEM_TYPES = {Product.Type.FLOWER, Product.Type.GREENERY}  # раздел «Цветы поштучно»
MAX_LINE_QTY = 101
FLOWERS_OFF = "Продажа цветов поштучно сейчас выключена. Выберите готовый букет."
CONSTRUCTOR_OFF = "Сборка своего букета сейчас недоступна. Выберите готовый букет."


class ChannelRestricted(DomainError):
    code = "channel_restricted"
    http_status = 403


class SectionDisabled(DomainError):
    """Владелец выключил раздел сайта в настройках."""

    code = "section_disabled"
    http_status = 409


class OrdersClosed(DomainError):
    """Владелец временно закрыл приём заказов (Настройки → «Приём заказов»)."""

    code = "orders_closed"
    http_status = 409


def orders_open():
    from apps.core.models import ShopSettings

    return ShopSettings.load().orders_enabled


def assert_orders_open():
    """Новые заказы с сайта и из ботов не принимаются, пока приём закрыт. Продажа в магазине (касса) — всегда."""
    from apps.core.models import ShopSettings
    from apps.core.site_content import orders_closed_message

    s = ShopSettings.load()
    if not s.orders_enabled:
        raise OrdersClosed(orders_closed_message(s))


def sections():
    """Какие разделы сайта включены: {"flowers": bool, "constructor": bool}."""
    from apps.core.models import ShopSettings

    s = ShopSettings.load()
    return {"flowers": s.flowers_section_enabled, "constructor": s.constructor_section_enabled}


def assert_flowers_enabled():
    if not sections()["flowers"]:
        raise SectionDisabled(FLOWERS_OFF)


def assert_constructor_enabled():
    if not sections()["constructor"]:
        raise SectionDisabled(CONSTRUCTOR_OFF)


def channel_label(channel):
    return {"telegram": "Telegram", "vk": "ВКонтакте"}.get(channel, channel)


def assert_product_allowed(channel, product):
    if channel in BOT_CHANNELS:
        if product.type != Product.Type.BOUQUET:
            raise ChannelRestricted(
                f"В {channel_label(channel)} можно заказать только готовые букеты. "
                "Отдельные цветы и индивидуальные букеты доступны на сайте."
            )
    elif product.type not in WEB_SELLABLE:
        raise ValidationError("Этот товар добавляется только через конструктор букета", code="not_sellable")
    elif product.type in STEM_TYPES:
        assert_flowers_enabled()


def assert_custom_allowed(channel):
    if channel != Cart.Channel.WEB:
        raise ChannelRestricted(
            f"Конструктор букетов недоступен в {channel_label(channel)}. Соберите букет на сайте."
        )
    assert_constructor_enabled()


def get_cart(token, channel=None):
    try:
        cart = Cart.objects.get(token=token)
    except (Cart.DoesNotExist, ValueError, Exception):
        raise NotFound("Корзина не найдена", code="cart_not_found")
    if channel and cart.channel != channel:
        raise ChannelRestricted("Корзина принадлежит другому каналу продаж")
    return cart


def create_cart(channel="web", customer=None):
    return Cart.objects.create(channel=channel, customer=customer)


def product_available(product, avail=None):
    """Доступно к заказу: свободный остаток + (для букетов под заказ) сколько можно собрать по рецептуре."""
    from apps.recipes.services import capacity

    full = avail if avail is not None else None  # avail должен содержать все материалы (availability_map())
    free = (full if full is not None else availability_map([product.inventory_item_id])).get(product.inventory_item_id, 0)
    if product.type == Product.Type.BOUQUET and product.allow_made_to_order:
        recipe = getattr(product.inventory_item, "recipe", None)
        if recipe and recipe.is_active:
            free += capacity(recipe, full)
    return max(free, 0)


def add_product(cart, product_id, quantity=1):
    assert_orders_open()
    try:
        product = Product.objects.select_related("inventory_item").get(pk=product_id, is_active=True)
    except Product.DoesNotExist:
        raise NotFound("Товар не найден или снят с продажи", code="product_not_found")
    assert_product_allowed(cart.channel, product)
    quantity = int(quantity)
    if quantity <= 0:
        raise ValidationError("Количество должно быть больше нуля")
    line = cart.items.filter(item_type=CartItem.ItemType.PRODUCT, product=product).first()
    new_qty = (line.quantity if line else 0) + quantity
    _check_qty(product, new_qty)
    if line:
        line.quantity = new_qty
        line.save(update_fields=["quantity"])
    else:
        line = CartItem.objects.create(cart=cart, product=product, quantity=new_qty)
    cart.save(update_fields=["updated_at"])
    return line


def _check_qty(product, qty):
    if qty > MAX_LINE_QTY:
        raise ValidationError(f"Максимум {MAX_LINE_QTY} шт. в одной позиции")
    available = product_available(product)
    if qty > available:
        raise DomainError(
            f"«{product.name}»: в наличии только {available} шт.", code="insufficient_stock", http_status=409,
            details={"available": available},
        )


def add_custom_bouquet(cart, composition, quantity=1):
    assert_orders_open()
    assert_custom_allowed(cart.channel)
    q = builder.quote(composition, quantity=int(quantity))
    line = CartItem.objects.create(
        cart=cart, item_type=CartItem.ItemType.CUSTOM_BOUQUET, composition=q["composition"], quantity=int(quantity)
    )
    cart.save(update_fields=["updated_at"])
    return line


def set_quantity(cart, item_id, quantity):
    line = cart.items.filter(pk=item_id).first()
    if not line:
        raise NotFound("Позиция не найдена")
    quantity = int(quantity)
    if quantity <= 0:
        line.delete()
        return None
    if line.item_type == CartItem.ItemType.PRODUCT:
        assert_product_allowed(cart.channel, line.product)
        _check_qty(line.product, quantity)
    else:
        assert_custom_allowed(cart.channel)
        builder.quote(line.composition, quantity=quantity)
    line.quantity = quantity
    line.save(update_fields=["quantity"])
    return line


def remove_item(cart, item_id):
    cart.items.filter(pk=item_id).delete()


def clear(cart):
    cart.items.all().delete()


def summary(cart):
    """Позиции корзины с актуальными ценами (цены всегда пересчитываются сервером)."""
    lines, total, problems = [], 0, []
    on = sections()
    items = list(cart.items.select_related("product__inventory_item").prefetch_related("product__images"))
    for line in items:
        if line.item_type == CartItem.ItemType.PRODUCT:
            p = line.product
            available = product_available(p) if p.is_active else 0
            ok = p.is_active and line.quantity <= available
            image = p.images.first()
            row = {
                "id": line.id, "type": "product", "product_id": p.id, "slug": p.slug, "name": p.name,
                "product_type": p.type, "quantity": line.quantity, "unit_price": p.price,
                "total": p.price * line.quantity, "available": available, "ok": ok,
                "image": image.image.url if image else None,
            }
            if p.type in STEM_TYPES and not on["flowers"] and cart.channel not in BOT_CHANNELS:
                row.update({"ok": False, "error": FLOWERS_OFF})
        elif not on["constructor"]:
            row = {"id": line.id, "type": "custom_bouquet", "name": "Индивидуальный букет", "quantity": line.quantity,
                   "unit_price": 0, "total": 0, "ok": False, "error": CONSTRUCTOR_OFF,
                   "card_text": line.composition.get("card_text", ""), "wishes": line.composition.get("wishes", "")}
        else:
            try:
                q = builder.quote(line.composition, quantity=line.quantity)
                row = {
                    "id": line.id, "type": "custom_bouquet", "name": "Индивидуальный букет",
                    "quantity": line.quantity, "unit_price": q["unit_price"], "total": q["total"],
                    "composition": q["lines"], "florist_fee": q["florist_fee"], "ok": True, "design": {**q["composition"], "items": builder.design_catalog(q["composition"])},
                    "card_text": line.composition.get("card_text", ""), "wishes": line.composition.get("wishes", ""),
                }
            except DomainError as e:
                row = {"id": line.id, "type": "custom_bouquet", "name": "Индивидуальный букет", "quantity": line.quantity,
                       "unit_price": 0, "total": 0, "ok": False, "error": e.message}
        if not row["ok"]:
            problems.append(row["name"])
        total += row["total"]
        lines.append(row)
    return {
        "token": str(cart.token), "channel": cart.channel, "items": lines, "items_total": total,
        "count": sum(l["quantity"] for l in lines), "problems": problems,
    }
