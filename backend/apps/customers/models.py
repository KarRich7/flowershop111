from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=16, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "customers"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or self.phone or f"Клиент #{self.pk}"


class CustomerChannel(models.Model):
    class Channel(models.TextChoices):
        WEB = "web", "Сайт"
        TELEGRAM = "telegram", "Telegram"
        VK = "vk", "ВКонтакте"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="channels")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    external_id = models.CharField(max_length=64)
    chat_id = models.CharField(max_length=64, blank=True)
    username = models.CharField(max_length=120, blank=True)
    display_name = models.CharField(max_length=160, blank=True)
    is_simulated = models.BooleanField(default=False, help_text="Пользователь локального симулятора ботов")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customer_channels"
        constraints = [models.UniqueConstraint(fields=["channel", "external_id"], name="uniq_customer_channel")]


class CustomerLogin(models.Model):
    """Запрос входа на сайт через бота (Telegram / ВКонтакте).

    Сайт получает секретный token (по нему опрашивает статус), а покупателю показывает ссылку
    t.me/<бот>?start=login_<link_code> или vk.me/<сообщество>?ref=login_<link_code> и запасной 6-значный код.
    Бот находит запрос, просит подтвердить вход кнопкой и привязывает его к клиенту своего канала.
    После этого сайт обменивает token на сессию покупателя (один раз)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        CONFIRMED = "confirmed", "Подтверждён в боте"
        USED = "used", "Сессия выдана"
        CANCELLED = "cancelled", "Отменён"

    channel = models.CharField(max_length=16)
    token = models.CharField(max_length=64, unique=True)
    link_code = models.CharField(max_length=40, unique=True)
    code = models.CharField(max_length=6, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    claimed_by = models.CharField(max_length=80, blank=True, help_text="Пользователь бота, открывший ссылку")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.CASCADE, related_name="logins")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                              help_text="Подключить уведомления к уже оформленному заказу")
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_logins"
        ordering = ["-created_at"]


class CustomerSession(models.Model):
    """Сессия покупателя на сайте. В базе хранится только SHA-256 от токена."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="sessions")
    key_hash = models.CharField(max_length=64, unique=True)
    channel = models.CharField(max_length=16, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "customer_sessions"
