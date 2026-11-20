"""11. Идемпотентные webhook-и, 12. самовывоз без адреса, оформление заказа."""
import json

import pytest
from django.db import IntegrityError, transaction

from apps.orders.models import Order, OrderEvent, OrderItem
from apps.payments import services as payments
from apps.payments.models import Payment, PaymentWebhookEvent
from apps.payments.providers.registry import get_provider

pytestmark = pytest.mark.django_db
S = Order.Status
URL = "/api/v1/payments/webhook/simulator"


def _webhook(client, body, headers):
    return client.post(URL, data=body, content_type="application/json",
                       **{f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()})


def test_duplicate_payment_webhook_has_no_double_effect(shop, web):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    payment = order.payments.get()
    body, headers = get_provider("simulator").build_event(payment, "payment.succeeded")
    r1 = _webhook(web, body, headers)
    r2 = _webhook(web, body, headers)  # повтор того же уведомления
    assert r1.status_code == 200 and r2.status_code == 200, (r1.content, r2.content)
    assert PaymentWebhookEvent.objects.filter(provider="simulator").count() == 1
    order.refresh_from_db()
    assert order.status == S.CONFIRMED and order.payment_status == "paid"
    assert OrderEvent.objects.filter(order=order, to_status=S.CONFIRMED).count() == 1
    # другое уведомление об уже учтённом платеже тоже ничего не меняет
    body2, headers2 = get_provider("simulator").build_event(payment, "payment.succeeded")
    _webhook(web, body2, headers2)
    assert Payment.objects.filter(order=order, status="paid").count() == 1
    assert OrderEvent.objects.filter(order=order, to_status=S.CONFIRMED).count() == 1
    assert shop.balance(b.inventory_item).reserved == 1


def test_webhook_with_bad_signature_rejected(shop, web):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    body, headers = get_provider("simulator").build_event(order.payments.get(), "payment.succeeded")
    r = _webhook(web, body, {"X-Simulator-Signature": "0" * 64})
    assert r.status_code == 400
    tampered = json.loads(body)
    tampered["amount"] = 1
    r = _webhook(web, json.dumps(tampered).encode(), headers)
    assert r.status_code == 400
    order.refresh_from_db()
    assert order.status == S.AWAITING_PAYMENT


def test_payment_after_expiry_is_refunded(shop):
    from datetime import timedelta

    from django.utils import timezone

    from apps.orders import services as orders

    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    payment = order.payments.get()
    orders.expire_overdue_orders(now=timezone.now() + timedelta(minutes=20))
    body, headers = get_provider("simulator").build_event(payment, "payment.succeeded")
    payment.status = Payment.Status.PENDING  # провайдер всё же провёл платёж
    payment.save()
    payments.process_webhook("simulator", body, headers)
    order.refresh_from_db()
    assert order.status == S.CANCELLED
    assert order.payment_status in ("refund_pending", "refunded")


def test_payment_simulator_endpoint(shop, web):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    token = order.payments.get().token
    info = web.get(f"/api/v1/payments/{token}").json()
    assert info["amount"] == order.total and info["is_test"] is True
    r = web.post(f"/api/v1/payments/{token}/simulate", {"action": "fail"}, format="json")
    assert r.status_code == 200
    order.refresh_from_db()
    assert order.payment_status == "failed" and order.status == S.AWAITING_PAYMENT
    # новая попытка оплаты
    url = web.post(f"/api/v1/orders/track/{order.public_token}/pay", format="json").json()["payment_url"]
    new_token = url.rsplit("/", 1)[-1]
    assert new_token != token
    assert web.post(f"/api/v1/payments/{new_token}/simulate", {"action": "succeed"}, format="json").status_code == 200
    order.refresh_from_db()
    assert order.status == S.CONFIRMED


def _checkout(client, shop, product, **kw):
    token = client.post("/api/v1/carts", format="json").json()["token"]
    r = client.post(f"/api/v1/carts/{token}/items", {"product_id": product.id, "quantity": 1}, format="json")
    assert r.status_code == 200, r.content
    data = {"cart_token": token, **shop.order_data(**kw)}
    return client.post("/api/v1/checkout", data, format="json")


def test_pickup_order_without_address(shop, web):
    """12. Самовывоз оформляется без адреса доставки."""
    b = shop.bouquet(assembled=1)
    data_kw = {"fulfillment": "pickup"}
    r = _checkout(web, shop, b, **data_kw)
    assert r.status_code == 201, r.content
    order = Order.objects.get(number=r.json()["number"])
    assert order.fulfillment == "pickup" and order.delivery_cost == 0
    assert not hasattr(order, "delivery") or order.delivery is None
    assert r.json()["pickup"]["address"]


def test_delivery_requires_address(shop, web):
    b = shop.bouquet(assembled=1)
    r = _checkout(web, shop, b, address="")
    assert r.status_code == 400 and r.json()["error"]["code"] == "address_required"
    assert shop.balance(b.inventory_item).reserved == 0  # ничего не зарезервировано


def test_checkout_is_idempotent(shop, web):
    b = shop.bouquet(assembled=2)
    token = web.post("/api/v1/carts", format="json").json()["token"]
    web.post(f"/api/v1/carts/{token}/items", {"product_id": b.id, "quantity": 1}, format="json")
    data = {"cart_token": token, **shop.order_data()}
    r1 = web.post("/api/v1/checkout", data, format="json", HTTP_IDEMPOTENCY_KEY="key-123")
    r2 = web.post("/api/v1/checkout", data, format="json", HTTP_IDEMPOTENCY_KEY="key-123")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["number"] == r2.json()["number"]
    assert Order.objects.count() == 1
    assert shop.balance(b.inventory_item).reserved == 1


def test_order_snapshot_is_immutable(shop):
    b = shop.bouquet(assembled=1, price=300000)
    order = shop.place((b, 1))
    b.inventory_item.sale_price = 999900
    b.inventory_item.save()
    order.refresh_from_db()
    item = order.items.get()
    assert item.unit_price == 300000 and order.snapshot["items"][0]["unit_price"] == 300000
    # состав заказа защищён на уровне PostgreSQL-триггеров
    with pytest.raises(Exception):
        with transaction.atomic():
            OrderItem.objects.filter(pk=item.pk).update(unit_price=1)
    with pytest.raises(Exception):
        with transaction.atomic():
            Order.objects.filter(pk=order.pk).update(snapshot={"total": 1})
    other = shop.bouquet("other", assembled=1)
    with pytest.raises(Exception):  # подменить товар в строке нельзя
        with transaction.atomic():
            OrderItem.objects.filter(pk=item.pk).update(product=other)
    with pytest.raises(Exception):  # и вместе с отвязкой поменять цену — тоже
        with transaction.atomic():
            OrderItem.objects.filter(pk=item.pk).update(product=None, unit_price=1)
    # отвязать удалённый владельцем товар можно: название и цена в строке остаются
    OrderItem.objects.filter(pk=item.pk).update(product=None)
    item.refresh_from_db()
    assert item.product_id is None and item.unit_price == 300000


def test_delivery_cost_and_free_threshold(shop):
    shop.zone.free_from = 500000
    shop.zone.save()
    cheap = shop.bouquet("cheap", assembled=1, price=300000)
    order = shop.place((cheap, 1))
    assert order.delivery_cost == 30000 and order.total == 330000
    rich = shop.bouquet("rich", assembled=1, price=600000)
    order = shop.place((rich, 1))
    assert order.delivery_cost == 0 and order.total == 600000


def test_order_tracking_hides_internal_data(shop, web):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))
    data = web.get(f"/api/v1/orders/track/{order.public_token}").json()
    assert data["number"] == order.number
    assert "contact_phone" not in data or "***" in str(data.get("contact_phone"))
    assert web.get("/api/v1/orders/track/wrong-token").status_code == 404
