"""8. Расчёт цены конструктора и 9. сборка без двойного списания."""
import pytest

from apps.carts import services as carts
from apps.core.errors import ValidationError
from apps.inventory.models import StockMovement
from apps.orders import services as orders
from apps.orders.models import Order
from apps.recipes import services as recipes

pytestmark = pytest.mark.django_db
S = Order.Status


def test_constructor_price_is_materials_plus_florist_fee(shop, web):
    comp = shop.custom_composition(roses=5)
    expected = 5 * 15000 + 2 * 8000 + 15000 + 5000 + 10000 + 30000
    r = web.post("/api/v1/constructor/quote", {"composition": comp}, format="json")
    assert r.status_code == 200, r.content
    q = r.json()
    assert q["materials_total"] == expected - 30000
    assert q["florist_fee"] == 30000
    assert q["unit_price"] == expected
    # клиент не может подменить цену: сервер пересчитывает её при добавлении и оформлении
    token = web.post("/api/v1/carts", format="json").json()["token"]
    r = web.post(f"/api/v1/carts/{token}/custom-bouquet",
                 {"composition": {**comp, "price": 1, "unit_price": 1}}, format="json")
    assert r.status_code == 200, r.content
    cart = carts.get_cart(token, "web")
    order = orders.place_order(cart, shop.order_data())
    item = order.items.get()
    assert item.unit_price == expected and item.composition["florist_fee"] == 30000
    assert order.total == expected + 30000  # + доставка


def test_constructor_price_follows_current_prices(shop):
    from apps.catalog import builder

    before = builder.quote(shop.custom_composition())["unit_price"]
    shop.rose.sale_price = 20000
    shop.rose.save()
    assert builder.quote(shop.custom_composition())["unit_price"] == before + 5 * 5000


def test_constructor_validates_composition(shop):
    from apps.catalog import builder

    with pytest.raises(ValidationError):
        builder.quote({"flowers": [], "packaging_id": shop.kraft.id})
    with pytest.raises(ValidationError):
        builder.quote({"flowers": [{"item_id": shop.rose.id, "quantity": 2}], "packaging_id": shop.kraft.id})
    with pytest.raises(ValidationError):  # упаковку нельзя выдать за цветок
        builder.quote({"flowers": [{"item_id": shop.kraft.id, "quantity": 5}], "packaging_id": shop.kraft.id})
    with pytest.raises(ValidationError) as e:  # не больше, чем есть на складе (2 букета × 26 роз > 50)
        builder.quote({"flowers": [{"item_id": shop.rose.id, "quantity": 26}], "packaging_id": shop.kraft.id}, quantity=2)
    assert e.value.code == "insufficient_stock"


def test_constructor_allows_at_most_30_flowers(shop, web):
    """Покупатель сам собирает букет не больше чем из 30 цветков (зелень в лимит не входит)."""
    from apps.catalog import builder
    from apps.core.models import ShopSettings

    assert builder.quote(shop.custom_composition(roses=30))["stems"] == 30
    with pytest.raises(ValidationError) as e:
        builder.quote(shop.custom_composition(roses=31))
    assert e.value.code == "too_many_stems"
    # даже если в базе осталось старое значение 101 — потолок 30
    ShopSettings.objects.filter(pk=1).update(max_custom_stems=101)
    with pytest.raises(ValidationError):
        builder.quote(shop.custom_composition(roses=31))
    assert web.get("/api/v1/constructor/options").json()["max_stems"] == 30


def test_florist_choice_bouquet_has_no_sketch(shop, web):
    """«Конструктор по фото»: только цветы, упаковка и лента, оформление — на усмотрение флориста."""
    comp = {"flowers": [{"item_id": shop.rose.id, "quantity": 7}], "packaging_id": shop.kraft.id,
            "ribbon_id": shop.ribbon.id, "florist_choice": True,
            "layout": [{"item_id": shop.rose.id, "x": 0.5, "y": 0.5, "r": 0}]}
    q = web.post("/api/v1/constructor/quote", {"composition": comp}, format="json").json()
    assert q["composition"]["florist_choice"] is True and q["composition"]["layout"] == []
    assert q["unit_price"] == 7 * 15000 + 15000 + 5000 + 30000
    token = web.post("/api/v1/carts", format="json").json()["token"]
    r = web.post(f"/api/v1/carts/{token}/custom-bouquet", {"composition": comp}, format="json")
    assert r.status_code == 200, r.content
    line = [i for i in r.json()["items"] if i["type"] == "custom_bouquet"][0]
    assert line["design"]["florist_choice"] is True and line["design"]["layout"] == []
    assert {i["id"] for i in line["design"]["items"]} >= {shop.rose.id, shop.kraft.id}
    order = orders.place_order(carts.get_cart(token, "web"), shop.order_data())
    assert order.items.get().composition["florist_choice"] is True


def _movements(item, mtype):
    return StockMovement.objects.filter(item=item, movement_type=mtype).count()


def test_assembled_bouquet_sold_without_second_write_off(shop, staff):
    """9. Заранее собранный букет: компоненты списаны при сборке, при продаже списывается только букет."""
    b = shop.bouquet(roses=3)
    recipe = b.inventory_item.recipe
    recipes.assemble(recipe, 2, user=staff["florist"])
    assert shop.balance(shop.rose).quantity == 50 - 6
    assert shop.balance(shop.kraft).quantity == 20 - 2
    assert shop.balance(b.inventory_item).quantity == 2
    consume_before = _movements(shop.rose, StockMovement.Type.ASSEMBLY_CONSUME)

    order = shop.place((b, 1), payment="on_delivery")
    orders.staff_confirm(order.id, staff["florist"])
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])

    assert shop.balance(shop.rose).quantity == 44  # компоненты повторно НЕ списаны
    assert shop.balance(shop.kraft).quantity == 18
    assert shop.balance(b.inventory_item).quantity == 1
    assert _movements(shop.rose, StockMovement.Type.ASSEMBLY_CONSUME) == consume_before
    assert StockMovement.objects.filter(order=order, movement_type=StockMovement.Type.ORDER_FULFILLMENT).count() == 1


def test_made_to_order_bouquet_consumes_components_once(shop, staff):
    """Букет под заказ: резервируются и списываются только компоненты, готовый букет не трогается."""
    b = shop.bouquet(roses=3, made_to_order=True)
    order = shop.place((b, 2), payment="on_delivery")
    assert shop.balance(shop.rose).reserved == 6
    orders.staff_confirm(order.id, staff["florist"])
    orders.transition(order.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(order.id, S.READY, user=staff["florist"])
    rose = shop.balance(shop.rose)
    assert (rose.quantity, rose.reserved) == (44, 0)
    assert shop.balance(b.inventory_item).quantity == 0
    # повторный переход невозможен — повторного списания не будет
    with pytest.raises(Exception):
        orders.transition(order.id, S.READY, user=staff["florist"])
    assert shop.balance(shop.rose).quantity == 44


def test_mixed_stock_and_made_to_order(shop, staff):
    b = shop.bouquet(roses=3, made_to_order=True, assembled=1)
    assert shop.available(b) == 1 + 15  # 1 готовый + min(47 роз // 3, 19 листов крафта)
    order = shop.place((b, 2), payment="on_delivery")
    plan = order.items.get().fulfillment_plan
    assert plan == {"stock": 1, "made_to_order": 1}


def test_constructor_layout_is_saved_with_order(shop):
    """Расположение цветов из конструктора сохраняется в заказе (эскиз для флориста), лишние точки отбрасываются."""
    from apps.catalog import builder

    comp = shop.custom_composition(roses=3)
    comp["layout"] = ([{"item_id": shop.rose.id, "x": 0.5, "y": 0.4, "r": 10}] * 5
                      + [{"item_id": shop.euc.id, "x": 1.7, "y": -1}, {"item_id": 999999, "x": 0.1, "y": 0.1}, {"bad": 1}])
    norm = builder.normalize_composition(comp)
    assert len(norm["layout"]) == 4  # 3 розы + 1 эвкалипт (не больше, чем стеблей в составе)
    assert norm["layout"][-1] == {"item_id": shop.euc.id, "x": 1.0, "y": 0.0, "r": 0.0}
    order = shop.place(custom=comp)
    item = order.items.get()
    assert len(item.composition["layout"]) == 4
