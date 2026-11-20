from django.db import models


class BotSession(models.Model):
    """Состояние диалога пользователя с ботом (общая модель для Telegram, ВК и симулятора)."""

    channel = models.CharField(max_length=16)
    external_user_id = models.CharField(max_length=64)
    chat_id = models.CharField(max_length=64, blank=True)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.SET_NULL)
    cart = models.ForeignKey("carts.Cart", null=True, blank=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=40, default="idle")
    data = models.JSONField(default=dict, blank=True)
    is_simulated = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bot_sessions"
        constraints = [models.UniqueConstraint(fields=["channel", "external_user_id"], name="uniq_bot_session")]
