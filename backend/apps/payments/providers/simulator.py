"""Безопасный симулятор платежей. Деньги не списываются: оплата подтверждается вручную
на тестовой странице, а результат приходит подписанным (HMAC-SHA256) webhook-уведомлением."""
import hashlib
import hmac
import json
import uuid

from django.conf import settings

from .base import CreatedPayment, InvalidWebhook, PaymentProvider, WebhookEvent

SIGNATURE_HEADER = "X-Simulator-Signature"


def _secret():
    secret = settings.PAYMENT_SIMULATOR_SECRET
    if not secret:
        raise RuntimeError("PAYMENT_SIMULATOR_SECRET не задан")
    return secret.encode()


def sign(body: bytes) -> str:
    return hmac.new(_secret(), body, hashlib.sha256).hexdigest()


class SimulatorProvider(PaymentProvider):
    code = "simulator"
    title = "Тестовая оплата (симулятор)"
    is_test = True

    def create_payment(self, payment, receipt):
        return CreatedPayment(
            external_id=f"sim_{uuid.uuid4().hex}",
            confirmation_url=f"{settings.FRONTEND_URL}/pay/{payment.token}",
        )

    def request_refund(self, payment, amount):
        # Возврат подтверждается на тестовой странице платежа (кнопка «Подтвердить возврат»).
        return None

    def build_event(self, payment, event_type):
        body = json.dumps({
            "event_id": f"evt_{uuid.uuid4().hex}", "type": event_type, "payment_id": payment.external_id,
            "amount": payment.amount, "test": True,
        }, separators=(",", ":")).encode()
        return body, {SIGNATURE_HEADER: sign(body)}

    def parse_webhook(self, body, headers):
        given = headers.get(SIGNATURE_HEADER) or headers.get(SIGNATURE_HEADER.lower()) or ""
        if not hmac.compare_digest(given, sign(body)):
            raise InvalidWebhook("Неверная подпись уведомления")
        try:
            data = json.loads(body)
            return WebhookEvent(event_id=str(data["event_id"]), event_type=str(data["type"]),
                                external_id=str(data["payment_id"]), amount=int(data["amount"]), raw=data)
        except (ValueError, KeyError, TypeError):
            raise InvalidWebhook("Некорректное тело уведомления")
