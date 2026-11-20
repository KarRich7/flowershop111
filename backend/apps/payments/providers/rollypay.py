"""RollyPay (https://docs.rollypay.io): оплата по СБП, картой и др. на платёжной форме RollyPay.

Подключение: PAYMENT_PROVIDER=rollypay, ROLLYPAY_API_KEY и ROLLYPAY_SIGNING_SECRET (выдаются при создании
кассы). В настройках кассы указать callback_url https://<ваш-домен>/api/v1/payments/webhook/rollypay.
Проверка без денег: ROLLYPAY_TEST_MODE=true — платежи создаются тестовыми, на форме оплаты есть кнопки
«успешная / неуспешная оплата».

Безопасность уведомлений:
* подпись X-Signature = HMAC-SHA256(signing_secret, X-Timestamp + "." + тело) — без верной подписи 400;
* статус и сумму не берём из уведомления на слово: по payment_id запрашиваем платёж у API RollyPay
  с ключом кассы (как и для ЮKassa); тестовый платёж не подтвердит заказ, если тестовый режим выключен.

Возвраты: в API RollyPay нет метода возврата — заявку оформляют в личном кабинете/через поддержку RollyPay;
когда возврат проведён, приходит уведомление payment.refunded и платёж в заказе станет «Возвращён»."""
import hashlib
import hmac
import json
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from .base import CreatedPayment, IgnoredWebhook, InvalidWebhook, PaymentProvider, WebhookEvent

TIMEOUT = (5, 20)
SYNC_TIMEOUT = (3, 6)
PAYMENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{4,80}$")

# статус платежа RollyPay → событие магазина
STATUS_EVENTS = {
    "paid": "payment.succeeded",
    "canceled": "payment.canceled",
    "cancelled": "payment.canceled",
    "expired": "payment.expired",
    "refunded": "refund.succeeded",
    "chargeback": "payment.chargeback",
}


def _rub(kopecks: int) -> str:
    return f"{Decimal(int(kopecks)) / 100:.2f}"


def _kopecks(value) -> int:
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError, TypeError):
        return -1


class RollyPayError(RuntimeError):
    pass


class RollyPayProvider(PaymentProvider):
    code = "rollypay"
    title = "RollyPay"
    manual_refunds = True

    @property
    def is_test(self):
        return bool(settings.ROLLYPAY_TEST_MODE)

    # ---------------------------------------------------------------- HTTP
    def _request(self, method, path, payload=None, timeout=TIMEOUT):
        if not settings.ROLLYPAY_API_KEY:
            raise RollyPayError("RollyPay не настроен: укажите ROLLYPAY_API_KEY")
        headers = {"X-API-Key": settings.ROLLYPAY_API_KEY, "X-Nonce": str(uuid.uuid4()), "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            r = requests.request(method, f"{settings.ROLLYPAY_API_URL}{path}", headers=headers,
                                 data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
                                 timeout=timeout)
        except requests.RequestException as e:
            raise RollyPayError(f"RollyPay не отвечает: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            try:
                desc = r.json().get("error") or r.text[:200]
            except ValueError:
                desc = r.text[:200]
            raise RollyPayError(f"RollyPay вернул ошибку {r.status_code}: {desc}")
        try:
            return r.json()
        except ValueError as e:
            raise RollyPayError("RollyPay вернул неожиданный ответ") from e

    # ---------------------------------------------------------------- интерфейс провайдера
    def create_payment(self, payment, receipt):
        order = payment.order
        back = f"{settings.FRONTEND_URL}/order/{order.public_token}"
        payload = {
            "amount": _rub(payment.amount),
            "payment_currency": "RUB",
            # уникален для каждой попытки оплаты: у одного заказа может быть несколько попыток
            "order_id": f"{order.number}-{payment.token[:10]}",
            "description": f"Заказ №{order.number}"[:128],
            "success_redirect_url": back,
            "fail_redirect_url": back,
            "metadata": {"payment_token": payment.token, "order_number": str(order.number)},
        }
        if settings.ROLLYPAY_PAYMENT_METHOD:
            payload["payment_method"] = settings.ROLLYPAY_PAYMENT_METHOD
        if self.is_test:
            payload["test"] = True
        data = self._request("POST", "/api/v1/payments", payload)
        pid, url = str(data.get("payment_id") or ""), str(data.get("pay_url") or "")
        if not PAYMENT_ID_RE.match(pid) or not url.startswith("https://"):
            raise RollyPayError("RollyPay не вернул ссылку на оплату")
        return CreatedPayment(external_id=pid, confirmation_url=url)

    def request_refund(self, payment, amount):
        # API возвратов у RollyPay нет: заявку на возврат оформляют в личном кабинете кассы или через поддержку.
        # Итог придёт уведомлением payment.refunded.
        return None

    def refund_hint(self, payment):
        if payment.is_test:
            return "Тестовый платёж: деньги не списывались, возвращать нечего"
        return (f"Верните деньги покупателю в личном кабинете RollyPay (платёж {payment.external_id}) — "
                "после возврата статус обновится сам")

    def _verify_signature(self, body: bytes, headers: dict):
        secret = settings.ROLLYPAY_SIGNING_SECRET
        if not secret:
            raise InvalidWebhook("RollyPay не настроен: укажите ROLLYPAY_SIGNING_SECRET")
        h = {str(k).lower(): v for k, v in headers.items()}
        signature, ts = str(h.get("x-signature") or "").strip().lower(), str(h.get("x-timestamp") or "").strip()
        if not signature or not ts.isdigit():
            raise InvalidWebhook("Нет подписи уведомления")
        expected = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidWebhook("Неверная подпись уведомления")
        if abs(time.time() - int(ts)) > settings.ROLLYPAY_WEBHOOK_TOLERANCE:
            raise InvalidWebhook("Уведомление устарело")

    def _event_from_object(self, obj, payment_id, raw_event=""):
        status = str(obj.get("status") or "").lower()
        if str(obj.get("payment_id") or payment_id) != payment_id:
            raise InvalidWebhook("Платёж в ответе RollyPay не совпадает с уведомлением")
        if obj.get("test") is True and not settings.ROLLYPAY_TEST_MODE:
            raise IgnoredWebhook("Тестовый платёж RollyPay при выключенном тестовом режиме — не учитываем")
        currency = str(obj.get("payment_currency") or obj.get("currency") or "RUB").upper()
        if currency != "RUB":
            raise IgnoredWebhook(f"Платёж в валюте {currency} — не учитываем")
        event_type = STATUS_EVENTS.get(status)
        if not event_type:
            raise IgnoredWebhook(f"Статус «{status or '—'}» не требует действий")
        return WebhookEvent(event_id=f"{event_type}:{payment_id}", event_type=event_type, external_id=payment_id,
                            amount=_kopecks(obj.get("amount") or 0), raw={"event": raw_event, "object": obj})

    def parse_webhook(self, body, headers):
        self._verify_signature(body, headers)
        try:
            data = json.loads(body)
            payment_id = str(data["payment_id"])
            raw_event = str(data.get("event_type") or "")
        except (ValueError, KeyError, TypeError):
            raise InvalidWebhook("Некорректное тело уведомления")
        if not PAYMENT_ID_RE.match(payment_id):
            raise InvalidWebhook("Некорректный идентификатор платежа")
        if raw_event.startswith("payout.") or raw_event == "payment.created":
            raise IgnoredWebhook(f"Событие {raw_event} не требует действий")
        try:
            obj = self._request("GET", f"/api/v1/payments/{payment_id}")
        except RollyPayError as e:
            # 400 → RollyPay повторит уведомление позже
            raise InvalidWebhook(f"Не удалось проверить платёж в RollyPay: {e}")
        return self._event_from_object(obj, payment_id, raw_event)

    def fetch_event(self, payment):
        """Сверка статуса без уведомления (покупатель вернулся с формы оплаты раньше колбэка, колбэк не настроен)."""
        if not payment.external_id or not PAYMENT_ID_RE.match(payment.external_id):
            return None
        try:
            obj = self._request("GET", f"/api/v1/payments/{payment.external_id}", timeout=SYNC_TIMEOUT)
            return self._event_from_object(obj, payment.external_id, "sync")
        except (RollyPayError, IgnoredWebhook, InvalidWebhook):
            return None
