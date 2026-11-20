from django.db import models


class Notification(models.Model):
    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        VK = "vk", "ВКонтакте"
        SMS = "sms", "SMS"
        STAFF = "staff", "Сотрудникам"

    class Status(models.TextChoices):
        PENDING = "pending", "В очереди"
        SENT = "sent", "Отправлено"
        DEMO = "demo", "Демо-режим (симулятор)"
        SKIPPED = "skipped", "Канал не подключён"
        FAILED = "failed", "Ошибка"

    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    recipient = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=32)
    text = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=255, blank=True)
    is_handled = models.BooleanField(default=False, help_text="Для обращений: обработано сотрудником")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["channel", "recipient", "id"]), models.Index(fields=["kind", "is_handled"])]
