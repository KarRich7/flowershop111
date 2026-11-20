import secrets

from django.db import models


def new_payment_token():
    return secrets.token_urlsafe(24)


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидается"
        PAID = "paid", "Оплачен"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменён"
        REFUND_PENDING = "refund_pending", "Возврат"
        REFUNDED = "refunded", "Возвращён"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=32)
    amount = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    external_id = models.CharField(max_length=80, unique=True, null=True, blank=True)
    token = models.CharField(max_length=64, unique=True, default=new_payment_token)
    confirmation_url = models.CharField(max_length=500, blank=True)
    is_test = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=255, blank=True)
    refunded_amount = models.PositiveIntegerField(default=0)
    receipt = models.JSONField(default=dict, blank=True, help_text="Данные чека 54-ФЗ (касса не подключена)")
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments"
        ordering = ["-created_at"]


class PaymentWebhookEvent(models.Model):
    """Журнал входящих платёжных уведомлений. Уникальность event_id обеспечивает идемпотентность."""

    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    result = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payment_webhook_events"
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event")]
