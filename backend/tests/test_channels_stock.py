"""Единый остаток для сайта, Telegram, ВК и магазина + ограничения ботов."""
import pytest

from apps.bots.engine import BotEngine, Incoming
from apps.carts import services as carts
from apps.carts.models import CartItem
from apps.carts.services import ChannelRestricted
from apps.core.errors import ValidationError
from apps.orders import services as orders

pytestmark = pytest.mark.django_db


def _api_available(client, slug):
    r = client.get(f"/api/v1/catalog/products/{slug}")
    assert r.status_code == 200, r.content
    return r.json()["available"]


def test_web_order_reduces_available_stock(shop, web):
    """1. Заказ на сайте уменьшает доступный остаток."""
    b = shop.bouquet(assembled=3)
    assert _api_available(web, b.slug) == 3
    order = shop.place((b, 1))
    assert order.status == "awaiting_payment"
    bal = shop.balance(b.inventory_item)
    assert (bal.quantity, bal.reserved) == (3, 1)  # физически на месте, но зарезервирован
    assert _api_available(web, b.slug) == 2


def test_bots_see_stock_after_web_order(shop, web, tg, vk):
    """2. Telegram и ВК видят обновлённый остаток после заказа на сайте."""
    b = shop.bouquet(assembled=2)
    shop.place((b, 1))
    assert _api_available(tg, b.slug) == 1
    assert _api_available(vk, b.slug) == 1
    # чат-бот показывает тот же остаток
    out = BotEngine("telegram").handle(Incoming(channel="telegram", user_id="sim-1", payload="cat:all:0",
                                                simulated=True))
    assert any(b.name in m.text and "В наличии: 1 шт." in m.text for m in out)
    # и не даёт положить в корзину больше, чем есть
    r = tg.post("/api/v1/carts", format="json")
    token = r.json()["token"]
    r = tg.post(f"/api/v1/carts/{token}/items", {"product_id": b.id, "quantity": 2}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"


def test_store_sale_updates_all_channels(shop, web, tg, vk, staff):
    """3. Продажа в магазине уменьшает остаток для сайта и ботов."""
    b = shop.bouquet(assembled=2)
    orders.store_sale([{"product_id": b.id, "quantity": 1}], "cash", staff["florist"])
    assert _api_available(web, b.slug) == 1
    assert _api_available(tg, b.slug) == 1
    assert _api_available(vk, b.slug) == 1
    bal = shop.balance(b.inventory_item)
    assert (bal.quantity, bal.reserved) == (1, 0)
    # продажа последнего — товар исчезает из наличия везде
    orders.store_sale([{"product_id": b.id, "quantity": 1}], "card", staff["florist"])
    for c in (web, tg, vk):
        assert _api_available(c, b.slug) == 0


def test_store_sale_cannot_take_reserved_stock(shop, staff):
    b = shop.bouquet(assembled=1)
    shop.place((b, 1))
    with pytest.raises(Exception) as e:
        orders.store_sale([{"product_id": b.id, "quantity": 1}], "cash", staff["florist"])
    assert "свободно 0" in str(e.value)


@pytest.mark.parametrize("channel", ["telegram", "vk"])
def test_bots_cannot_order_flowers_or_custom_bouquets_service(shop, channel):
    """7. Боты не могут заказать цветы поштучно или индивидуальный букет (сервисный уровень)."""
    flower = shop.rose.product
    cart = carts.create_cart(channel)
    with pytest.raises(ChannelRestricted):
        carts.add_product(cart, flower.id, 1)
    with pytest.raises(ChannelRestricted):
        carts.add_custom_bouquet(cart, shop.custom_composition(), 1)
    # даже если позиция попала в корзину в обход API, оформление заказа её отклонит
    CartItem.objects.create(cart=cart, product=flower, quantity=3)
    with pytest.raises(ChannelRestricted):
        orders.place_order(cart, shop.order_data())
    cart.items.all().delete()
    CartItem.objects.create(cart=cart, item_type=CartItem.ItemType.CUSTOM_BOUQUET,
                            composition=shop.custom_composition(), quantity=1)
    with pytest.raises(ChannelRestricted):
        orders.place_order(cart, shop.order_data())


def test_bots_cannot_order_flowers_or_custom_bouquets_api(shop, tg, vk, web):
    """7. То же через HTTP API с сервисной авторизацией бота (канал определяется сервером)."""
    flower = shop.rose.product
    for client in (tg, vk):
        token = client.post("/api/v1/carts", format="json").json()["token"]
        r = client.post(f"/api/v1/carts/{token}/items", {"product_id": flower.id, "quantity": 1}, format="json")
        assert r.status_code == 403 and r.json()["error"]["code"] == "channel_restricted"
        r = client.post(f"/api/v1/carts/{token}/custom-bouquet", {"composition": shop.custom_composition()},
                        format="json")
        assert r.status_code == 403
        assert client.get("/api/v1/constructor/options").status_code == 403
    # анонимный запрос с фальшивым заголовком канала не превращается в бота, а бот-токен без канала отклоняется
    fake = web.post("/api/v1/carts", format="json", HTTP_X_BOT_CHANNEL="telegram").json()
    assert fake["channel"] == "web"
    from rest_framework.test import APIClient

    from .conftest import BOT_TOKEN

    no_channel = APIClient()
    no_channel.credentials(HTTP_AUTHORIZATION=f"Bot {BOT_TOKEN}")
    assert no_channel.post("/api/v1/carts", format="json").status_code in (401, 403)
    wrong = APIClient()
    wrong.credentials(HTTP_AUTHORIZATION="Bot wrong-token", HTTP_X_BOT_CHANNEL="telegram")
    assert wrong.post("/api/v1/carts", format="json").status_code in (401, 403)
    # корзину бота нельзя использовать с сайта, чтобы обойти ограничения
    tg_token = tg.post("/api/v1/carts", format="json").json()["token"]
    r = web.post(f"/api/v1/carts/{tg_token}/items", {"product_id": flower.id, "quantity": 1}, format="json")
    assert r.status_code in (403, 404)


def test_web_can_buy_flowers_individually(shop):
    cart = carts.create_cart("web")
    carts.add_product(cart, shop.rose.product.id, 7)
    order = orders.place_order(cart, shop.order_data())
    assert order.items.get().quantity == 7
    assert shop.balance(shop.rose).reserved == 7


def test_packaging_not_sold_separately_on_web(shop):
    cart = carts.create_cart("web")
    with pytest.raises(ValidationError):
        carts.add_product(cart, shop.kraft.product.id, 1)


def test_product_detail_always_has_composition(shop, web):
    """Карточка любого товара отдаёт состав списком: у цветов и упаковки — пустым (страница не падает)."""
    b = shop.bouquet(assembled=1)
    bouquet = web.get(f"/api/v1/catalog/products/{b.slug}").json()
    assert bouquet["composition"] == [{"name": "Роза", "quantity": 3}]
    for slug in ("fl-rose", "pk-kraft", "cd-love"):
        r = web.get(f"/api/v1/catalog/products/{slug}")
        assert r.status_code == 200, r.content
        assert r.json()["composition"] == []
