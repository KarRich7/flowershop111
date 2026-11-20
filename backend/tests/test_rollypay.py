"""RollyPay: создание платежа, подпись уведомлений, сверка статуса с API, возвраты (запросы к API замоканы)."""
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.core import security
from apps.orders import services as orders
from apps.orders.models import Order, OrderEvent
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.providers.base import InvalidWebhook

SECRET = "whsec_test_123"
PID = "pay_a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


class FakeRollyPay:
    """Имитация API RollyPay: создаёт платёж и отдаёт его текущий статус."""

    def __init__(self, status="created", amount="2800.00", test=False):
        self.status, self.amount, self.test = status, amount, test
        self.calls, self.nonces, self.created = [], [], []

    @property
    def pid(self):
        return self.created[-1]

    def __call__(self, method, url, **kw):
        headers = kw.get("headers", {})
        assert headers["X-API-Key"] == "rpk_live_test"
        uuid.UUID(headers["X-Nonce"])  # уникальный nonce в каждом запросе
        self.nonces.append(headers["X-Nonce"])
        body = json.loads(kw["data"]) if kw.get("data") else None
        self.calls.append((method, url, body))
        if method == "POST" and url == "https://rollypay.io/api/v1/payments":
            self.created.append(PID if not self.created else f"{PID}-{len(self.created)}")
            return _Resp({"payment_id": self.pid, "order_id": body["order_id"], "status": "created", "token": "tok_1",
                          "pay_url": "https://pay.rollypay.io/pay/tok_1", "amount": body["amount"],
                          "payment_currency": "RUB"})
        pid = url.rsplit("/", 1)[-1]
        if method == "GET" and url == f"https://rollypay.io/api/v1/payments/{pid}" and pid in self.created:
            return _Resp({"payment_id": pid, "status": self.status, "amount": self.amount, "payment_currency": "RUB",
                          "test": self.test})
        return _Resp({"error": "not found"}, 404)


def signed(body: dict, *, secret=SECRET, ts=None):
    raw = json.dumps(body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    sig = hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"X-Signature": sig, "X-Timestamp": ts}


def hook(status, event=None, pid=PID):
    return signed({"event_type": event or f"payment.{status}", "payment_id": pid, "order_id": "x", "status": status,
                   "amount": "2800.00", "currency": "RUB", "test": False})


@pytest.fixture
def rp(settings):
    settings.PAYMENT_PROVIDER = "rollypay"
    settings.ROLLYPAY_API_KEY, settings.ROLLYPAY_SIGNING_SECRET = "rpk_live_test", SECRET
    settings.ROLLYPAY_TEST_MODE = False
    settings.ROLLYPAY_PAYMENT_METHOD = ""
    fake = FakeRollyPay()
    with mock.patch("apps.payments.providers.rollypay.requests.request", side_effect=fake):
        yield fake


@pytest.mark.django_db
def test_rollypay_payment_flow_with_signed_webhook(shop, rp):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    p = o.payments.get()
    assert p.provider == "rollypay" and not p.is_test and p.external_id == PID
    assert p.confirmation_url == "https://pay.rollypay.io/pay/tok_1"
    method, url, body = rp.calls[0]
    assert body["amount"] == "2800.00" and body["payment_currency"] == "RUB" and "test" not in body
    assert body["order_id"].startswith(f"{o.number}-") and body["success_redirect_url"].endswith(f"/order/{o.public_token}")
    # промежуточный статус — 200 без изменений (иначе RollyPay будет повторять уведомление)
    rp.status = "processing"
    raw, h = hook("processing")
    assert payments.process_webhook("rollypay", raw, h)["status"] == "ignored"
    # «поддельное» paid при неоплаченном в RollyPay платеже ничего не меняет
    raw, h = hook("paid")
    assert payments.process_webhook("rollypay", raw, h)["status"] == "ignored"
    p.refresh_from_db()
    assert p.status == Payment.Status.PENDING
    rp.status = "paid"
    raw, h = hook("paid")
    assert payments.process_webhook("rollypay", raw, h)["status"] == "processed"
    assert payments.process_webhook("rollypay", raw, h)["status"] == "duplicate"
    o.refresh_from_db()
    p.refresh_from_db()
    assert p.status == Payment.Status.PAID and o.status == Order.Status.CONFIRMED
    assert len(set(rp.nonces)) == len(rp.nonces)


@pytest.mark.django_db
def test_rollypay_webhook_signature_is_required(shop, rp, web):
    b = shop.bouquet(assembled=2, price=250000)
    shop.place((b, 1))
    rp.status = "paid"
    raw, h = hook("paid")
    url = "/api/v1/payments/webhook/rollypay"
    # без подписи, с чужим секретом, с устаревшей отметкой времени — 400
    assert web.post(url, data=raw, content_type="application/json").status_code == 400
    bad_raw, bad_h = signed(json.loads(raw), secret="other")
    assert web.post(url, data=bad_raw, content_type="application/json",
                    HTTP_X_SIGNATURE=bad_h["X-Signature"], HTTP_X_TIMESTAMP=bad_h["X-Timestamp"]).status_code == 400
    old_raw, old_h = signed(json.loads(raw), ts=int(time.time()) - 3 * 86400)
    assert web.post(url, data=old_raw, content_type="application/json",
                    HTTP_X_SIGNATURE=old_h["X-Signature"], HTTP_X_TIMESTAMP=old_h["X-Timestamp"]).status_code == 400
    # подпись от другого тела не подходит
    assert web.post(url, data=raw.replace(b"paid", b"PAID"), content_type="application/json",
                    HTTP_X_SIGNATURE=h["X-Signature"], HTTP_X_TIMESTAMP=h["X-Timestamp"]).status_code == 400
    assert Payment.objects.get().status == Payment.Status.PENDING
    r = web.post(url, data=raw, content_type="application/json",
                 HTTP_X_SIGNATURE=h["X-Signature"], HTTP_X_TIMESTAMP=h["X-Timestamp"])
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert Payment.objects.get().status == Payment.Status.PAID


@pytest.mark.django_db
def test_rollypay_test_payment_does_not_confirm_live_order(shop, rp):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    rp.status, rp.test = "paid", True
    raw, h = hook("paid")
    assert payments.process_webhook("rollypay", raw, h)["status"] == "ignored"
    o.refresh_from_db()
    assert o.status == Order.Status.AWAITING_PAYMENT


@pytest.mark.django_db
def test_rollypay_amount_mismatch_is_not_accepted(shop, rp):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    rp.status, rp.amount = "paid", "1.00"
    raw, h = hook("paid")
    payments.process_webhook("rollypay", raw, h)
    o.refresh_from_db()
    assert o.status == Order.Status.AWAITING_PAYMENT and o.payments.get().status == Payment.Status.FAILED


@pytest.mark.django_db
def test_rollypay_expired_then_late_paid(shop, rp):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    rp.status = "expired"
    raw, h = hook("expired")
    payments.process_webhook("rollypay", raw, h)
    p = o.payments.get()
    assert p.status == Payment.Status.CANCELLED and p.failure_reason == "Истёк срок оплаты"
    # деньги дошли позже — RollyPay присылает paid, заказ подтверждается
    rp.status = "paid"
    raw, h = hook("paid")
    payments.process_webhook("rollypay", raw, h)
    o.refresh_from_db()
    assert o.status == Order.Status.CONFIRMED


@pytest.mark.django_db
def test_rollypay_refund_is_manual_and_closed_by_webhook(shop, rp):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    rp.status = "paid"
    payments.process_webhook("rollypay", *hook("paid"))
    orders.cancel(o.pk, actor_label="тест", reason="передумал")
    o.refresh_from_db()
    p = o.payments.get()
    assert p.status == Payment.Status.REFUND_PENDING and o.payment_status == Order.PaymentStatus.REFUND_PENDING
    assert OrderEvent.objects.filter(order=o, message__contains="личном кабинете RollyPay").exists()
    rp.status = "refunded"
    payments.process_webhook("rollypay", *hook("refunded", "refund_request.completed"))
    assert payments.process_webhook("rollypay", *hook("refunded", "payment.refunded"))["status"] == "duplicate"
    o.refresh_from_db()
    p.refresh_from_db()
    assert p.status == Payment.Status.REFUNDED and o.payment_status == Order.PaymentStatus.REFUNDED


@pytest.mark.django_db
def test_rollypay_test_mode(shop, rp, settings):
    settings.ROLLYPAY_TEST_MODE = True
    rp.test = True
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    p = o.payments.get()
    assert p.is_test and rp.calls[0][2]["test"] is True
    rp.status = "paid"
    payments.process_webhook("rollypay", *hook("paid"))
    # отмена тестового заказа: деньги не списывались — возврат закрывается сразу
    orders.cancel(o.pk, actor_label="тест")
    p.refresh_from_db()
    assert p.status == Payment.Status.REFUNDED
    assert any(i["code"] == "rollypay_test" for i in security.run_checks()["items"])


@pytest.mark.django_db
def test_rollypay_status_is_synced_without_webhook(shop, rp, web):
    b = shop.bouquet(assembled=2, price=250000)
    o = shop.place((b, 1))
    rp.status = "paid"  # уведомление не пришло, покупатель вернулся на страницу заказа
    r = web.get(f"/api/v1/orders/track/{o.public_token}")
    assert r.status_code == 200
    o.refresh_from_db()
    assert o.status == Order.Status.CONFIRMED
    # перед снятием резерва тоже сверяемся с кассой
    o2 = shop.place((b, 1))
    assert o2.payments.get().external_id == rp.pid != PID
    assert orders.expire_overdue_orders(now=timezone.now() + timedelta(days=1)) == []
    o2.refresh_from_db()
    assert o2.status == Order.Status.CONFIRMED


@pytest.mark.django_db
def test_rollypay_without_keys_is_reported(settings):
    settings.PAYMENT_PROVIDER = "rollypay"
    settings.ROLLYPAY_API_KEY = settings.ROLLYPAY_SIGNING_SECRET = ""
    assert any(i["code"] == "rollypay" for i in security.run_checks()["items"])
    from apps.payments.providers.rollypay import RollyPayProvider

    with pytest.raises(InvalidWebhook):
        RollyPayProvider().parse_webhook(b"{}", {})


@pytest.mark.django_db
def test_rollypay_outage_gives_clear_error(shop, rp, web):
    b = shop.bouquet(assembled=2, price=250000)
    with mock.patch("apps.payments.providers.rollypay.requests.request", return_value=_Resp({"error": "unavailable"}, 503)):
        from apps.core.errors import DomainError

        with pytest.raises(DomainError) as e:
            shop.place((b, 1))
    assert e.value.code == "payment_unavailable"
    assert not Order.objects.exists()  # заказ не создан, товар не зарезервирован
