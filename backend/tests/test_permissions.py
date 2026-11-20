"""13. Права сотрудников: курьер видит только свои доставки; цены меняет только владелец."""
import pytest

from apps.orders import services as orders
from apps.orders.models import Order

from .conftest import staff_client

pytestmark = pytest.mark.django_db
S = Order.Status


def _ready_delivery(shop, staff, slug):
    b = shop.bouquet(slug, assembled=1)
    o = shop.place((b, 1), payment="on_delivery")
    orders.staff_confirm(o.id, staff["florist"])
    orders.transition(o.id, S.ASSEMBLING, user=staff["florist"])
    orders.transition(o.id, S.READY, user=staff["florist"])
    return o


def test_courier_sees_only_assigned_orders(shop, staff):
    mine = _ready_delivery(shop, staff, "b-mine")
    other = _ready_delivery(shop, staff, "b-other")
    unassigned = _ready_delivery(shop, staff, "b-free")
    orders.assign_courier(mine.id, staff["courier1"].id, staff["owner"])
    orders.assign_courier(other.id, staff["courier2"].id, staff["owner"])

    c = staff_client("courier1")
    ids = {row["id"] for row in c.get("/api/v1/admin/orders").json()}
    assert ids == {mine.id}
    assert c.get(f"/api/v1/admin/orders/{mine.id}").status_code == 200
    for o in (other, unassigned):
        assert c.get(f"/api/v1/admin/orders/{o.id}").status_code == 404
        r = c.post(f"/api/v1/admin/orders/{o.id}/transition", {"status": "handed_to_courier"}, format="json")
        assert r.status_code in (403, 404)
    # курьер не видит склад, клиентов, настройки и не может назначать курьеров
    for url in ("/api/v1/admin/inventory", "/api/v1/admin/customers", "/api/v1/admin/settings",
                "/api/v1/admin/staff"):
        assert c.get(url).status_code == 403, url
    r = c.post(f"/api/v1/admin/orders/{unassigned.id}/assign-courier",
               {"courier_id": staff["courier1"].id}, format="json")
    assert r.status_code in (403, 404)
    # свою доставку курьер ведёт сам
    r = c.post(f"/api/v1/admin/orders/{mine.id}/transition", {"status": "handed_to_courier"}, format="json")
    assert r.status_code == 200, r.content
    # после передачи курьеру вернуть заказ в «Готов» нельзя — в действиях только «Доставлен / выдан»
    owner = staff_client("owner")
    actions = [a["status"] for a in owner.get(f"/api/v1/admin/orders/{mine.id}").json()["allowed_transitions"]]
    assert actions == ["delivered"]
    assert owner.post(f"/api/v1/admin/orders/{mine.id}/transition", {"status": "ready"}, format="json").status_code == 409
    r = c.post(f"/api/v1/admin/orders/{mine.id}/transition", {"status": "delivered"}, format="json")
    assert r.status_code == 200, r.content
    mine.refresh_from_db()
    assert mine.status == S.DELIVERED and mine.payment_status == "paid"  # наличные при получении


def test_courier_order_detail_has_no_financials(shop, staff):
    o = _ready_delivery(shop, staff, "b-x")
    orders.assign_courier(o.id, staff["courier1"].id, staff["owner"])
    data = staff_client("courier1").get(f"/api/v1/admin/orders/{o.id}").json()
    assert "payments" not in data and "events" not in data


def test_florist_sets_sale_price_but_not_purchase_price(shop, staff):
    b = shop.bouquet(assembled=1)
    florist = staff_client("florist")
    r = florist.patch(f"/api/v1/admin/products/{b.id}", {"price": 320000}, format="json")
    assert r.status_code == 200, r.content
    assert "purchase_price" not in r.json()  # закупочные цены флористу не показываются
    b.inventory_item.refresh_from_db()
    assert b.inventory_item.sale_price == 320000
    r = florist.patch(f"/api/v1/admin/products/{b.id}", {"purchase_price": 1}, format="json")
    assert r.status_code == 403
    owner = staff_client("owner")
    r = owner.patch(f"/api/v1/admin/products/{b.id}", {"price": 350000, "purchase_price": 120000}, format="json")
    assert r.status_code == 200, r.content
    b.inventory_item.refresh_from_db()
    assert (b.inventory_item.sale_price, b.inventory_item.purchase_price) == (350000, 120000)
    assert staff_client("courier1").patch(f"/api/v1/admin/products/{b.id}", {"price": 1}, format="json").status_code == 403


def test_florist_creates_bouquet_with_stock_and_recipe(shop, staff):
    """Новый букет флориста сразу доступен: начальный остаток и рецептура задаются в карточке."""
    florist = staff_client("florist")
    r = florist.post("/api/v1/admin/products", {"type": "bouquet", "name": "Новый букет", "price": 250000,
                                                "is_active": True, "stock": 2}, format="json")
    assert r.status_code == 201, r.content
    p = r.json()
    assert p["price"] == 250000 and p["available"] == 2 and p["in_stock"]
    r = florist.patch(f"/api/v1/admin/products/{p['id']}", {
        "allow_made_to_order": True, "stock": 0,
        "components": [{"item_id": shop.rose.id, "quantity": 5}, {"item_id": shop.kraft.id, "quantity": 1}],
    }, format="json")
    assert r.status_code == 200, r.content
    d = r.json()
    assert d["stock"]["quantity"] == 0
    assert d["can_assemble"] == 10 and d["available"] == 10  # 50 роз / 5 на букет
    assert [c["item_id"] for c in d["components"]] == [shop.rose.id, shop.kraft.id]
    from apps.inventory.models import StockMovement

    assert StockMovement.objects.filter(item_id=d["inventory_item_id"]).count() == 2  # приход 2 и списание 2


def test_staff_api_requires_auth(web):
    assert web.get("/api/v1/admin/orders").status_code in (401, 403)
    r = web.post("/api/v1/admin/auth/login", {"username": "nobody", "password": "x"}, format="json")
    assert r.status_code == 400


def test_florist_cannot_refund(shop, staff):
    from apps.payments import services as payments

    b = shop.bouquet(assembled=1)
    o = shop.place((b, 1))
    payments.simulator_action(o.payments.get().token, "succeed")
    r = staff_client("florist").post(f"/api/v1/admin/orders/{o.id}/refund", {}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_health_endpoint(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


def test_action_buttons_match_fulfillment_payment_and_role(shop, staff):
    """Кнопки в карточке заказа — только выполнимые переходы: без «Ожидает самовывоза» у доставки,
    без «Подтверждён» у неоплаченного онлайн-заказа, курьеру — только его шаги."""
    o = _ready_delivery(shop, staff, "b-btn")
    orders.assign_courier(o.id, staff["courier1"].id, staff["owner"])
    owner = staff_client("owner")
    actions = [a["status"] for a in owner.get(f"/api/v1/admin/orders/{o.id}").json()["allowed_transitions"]]
    assert actions == ["handed_to_courier", "cancelled"]
    courier = [a["status"] for a in staff_client("courier1").get(f"/api/v1/admin/orders/{o.id}").json()["allowed_transitions"]]
    assert courier == ["handed_to_courier"]
    online = shop.place((shop.bouquet("b-online", assembled=1), 1), payment="online")
    assert online.status == S.AWAITING_PAYMENT
    actions = [a["status"] for a in owner.get(f"/api/v1/admin/orders/{online.id}").json()["allowed_transitions"]]
    assert actions == ["cancelled"]
