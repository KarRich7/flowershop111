"""ЮKassa (https://yookassa.ru/developers/api). Подключение: PAYMENT_PROVIDER=yookassa, YOOKASSA_SHOP_ID,
YOOKASSA_SECRET_KEY; в личном кабинете ЮKassa → Интеграция → HTTP-уведомления указать
https://<ваш-домен>/api/v1/payments/webhook/yookassa (события payment.succeeded, payment.canceled,
refund.succeeded).

Уведомлениям ЮKassa не доверяем на слово: по id из уведомления запрашиваем объект у API ЮKassa
с секретным ключом магазина и берём статус и сумму оттуда. Поддельное уведомление ничего не изменит."""
import json
import uuid
from decimal import Decimal

import requests
from django.conf import settings

from .base import CreatedPayment, InvalidWebhook, PaymentProvider, WebhookEvent

TIMEOUT = (5, 20)


def _rub(kopecks: int) -> str:
    return f"{Decimal(int(kopecks)) / 100:.2f}"


def _kopecks(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1")))


class YooKassaError(RuntimeError):
    pass


class YooKassaProvider(PaymentProvider):
    code = "yookassa"
    title = "ЮKassa"
    is_test = False

    # ---------------------------------------------------------------- HTTP
    def _auth(self):
        if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
            raise YooKassaError("ЮKassa не настроена: укажите YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")
        return settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY

    def _request(self, method, path, payload=None, idempotence_key=None):
        headers = {"Content-Type": "application/json"}
        if idempotence_key:
            headers["Idempotence-Key"] = idempotence_key
        try:
            r = requests.request(method, f"{settings.YOOKASSA_API_URL}{path}", auth=self._auth(), headers=headers,
                                 data=json.dumps(payload) if payload is not None else None, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise YooKassaError(f"ЮKassa не отвечает: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            try:
                desc = r.json().get("description") or r.text[:200]
            except ValueError:
                desc = r.text[:200]
            raise YooKassaError(f"ЮKassa вернула ошибку {r.status_code}: {desc}")
        return r.json()

    # ---------------------------------------------------------------- чек 54-ФЗ
    def _receipt(self, receipt):
        if not settings.YOOKASSA_SEND_RECEIPT or not receipt:
            return None
        customer = {}
        cust = receipt.get("customer") or {}
        if cust.get("email"):
            customer["email"] = cust["email"]
        if cust.get("phone"):
            customer["phone"] = str(cust["phone"]).lstrip("+")
        items = [{
            "description": (it.get("description") or "Товар")[:128],
            "quantity": f"{int(it.get('quantity') or 1):.2f}",
            "amount": {"value": _rub(it.get("price") or 0), "currency": "RUB"},
            "vat_code": settings.YOOKASSA_VAT_CODE,
            "payment_subject": it.get("payment_subject") or "commodity",
            "payment_mode": "full_payment",
        } for it in receipt.get("items") or []]
        out = {"customer": customer, "items": items}
        if settings.YOOKASSA_TAX_SYSTEM_CODE:
            out["tax_system_code"] = int(settings.YOOKASSA_TAX_SYSTEM_CODE)
        return out

    # ---------------------------------------------------------------- интерфейс провайдера
    def create_payment(self, payment, receipt):
        order = payment.order
        payload = {
            "amount": {"value": _rub(payment.amount), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": f"{settings.FRONTEND_URL}/order/{order.public_token}"},
            "description": f"Заказ №{order.number}"[:128],
            "metadata": {"payment_token": payment.token, "order_number": order.number},
        }
        r = self._receipt(receipt)
        if r:
            payload["receipt"] = r
        data = self._request("POST", "/payments", payload, idempotence_key=f"pay-{payment.token}")
        url = (data.get("confirmation") or {}).get("confirmation_url") or ""
        if not data.get("id") or not url:
            raise YooKassaError("ЮKassa не вернула ссылку на оплату")
        return CreatedPayment(external_id=str(data["id"]), confirmation_url=url)

    def request_refund(self, payment, amount):
        payload = {"payment_id": payment.external_id, "amount": {"value": _rub(amount), "currency": "RUB"}}
        data = self._request("POST", "/refunds", payload, idempotence_key=f"refund-{payment.token}-{amount}")
        return data.get("id")

    def parse_webhook(self, body, headers):
        try:
            data = json.loads(body)
            event = str(data["event"])
            obj_id = str(data["object"]["id"])
        except (ValueError, KeyError, TypeError):
            raise InvalidWebhook("Некорректное тело уведомления")
        if not obj_id or len(obj_id) > 64 or not all(c.isalnum() or c == "-" for c in obj_id):
            raise InvalidWebhook("Некорректный идентификатор")
        try:
            if event.startswith("refund."):
                obj = self._request("GET", f"/refunds/{obj_id}")
                status = obj.get("status")
                event_type = {"succeeded": "refund.succeeded", "canceled": "refund.failed"}.get(status)
                external_id = str(obj.get("payment_id") or "")
            else:
                obj = self._request("GET", f"/payments/{obj_id}")
                status = obj.get("status")
                event_type = {"succeeded": "payment.succeeded", "canceled": "payment.canceled"}.get(status)
                external_id = str(obj.get("id") or "")
        except YooKassaError as e:
            raise InvalidWebhook(f"Не удалось проверить уведомление в ЮKassa: {e}")
        if not event_type or not external_id:
            raise InvalidWebhook(f"Статус «{status}» не требует действий")
        amount = _kopecks((obj.get("amount") or {}).get("value") or 0)
        return WebhookEvent(event_id=f"{event_type}:{obj_id}", event_type=event_type, external_id=external_id,
                            amount=amount, raw={"event": event, "object": obj})
