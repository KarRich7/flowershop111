from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Сотрудник магазина. Пароли хранятся только в виде хешей (PBKDF2)."""

    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        FLORIST = "florist", "Флорист"
        COURIER = "courier", "Курьер"

    class NotifyMode(models.TextChoices):
        ALWAYS = "always", "Всегда"
        SHIFT = "shift", "Только на смене"
        OFF = "off", "Не присылать"

    role = models.CharField("Роль", max_length=16, choices=Role.choices, default=Role.FLORIST)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    is_demo = models.BooleanField("Демо-данные", default=False)
    # Уведомления о новых заказах и обращениях — лично сотруднику в Telegram/ВК (apps/notifications/staff.py)
    notify_mode = models.CharField("Уведомления о заказах", max_length=8, choices=NotifyMode.choices,
                                   default=NotifyMode.SHIFT)
    telegram_id = models.CharField("Telegram (id чата)", max_length=32, blank=True)
    vk_id = models.CharField("ВКонтакте (id)", max_length=32, blank=True)
    on_shift = models.BooleanField("На смене", default=False)
    shift_started_at = models.DateTimeField("Смена начата", null=True, blank=True)
    link_code = models.CharField(max_length=40, blank=True, db_index=True)  # одноразовая ссылка привязки мессенджера
    link_code_expires = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "users"
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

    def save(self, *args, **kwargs):
        if self._state.adding and self.notify_mode == self.NotifyMode.SHIFT:  # режим по умолчанию — по роли
            self.notify_mode = {self.Role.OWNER: self.NotifyMode.ALWAYS,
                                self.Role.COURIER: self.NotifyMode.OFF}.get(self.role, self.NotifyMode.SHIFT)
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username


# Потолок для конструктора: больше 30 цветков покупатель сам не соберёт (эскиз и раскладка рассчитаны на 30),
# крупные букеты — через готовые позиции или по телефону.
MAX_CUSTOM_STEMS_LIMIT = 30


class ShopSettings(models.Model):
    """Единственная запись с настройками магазина (бренд, контакты, правила резервов)."""

    shop_name = models.CharField(max_length=120, default="Цветочная Лавка")
    tagline = models.CharField(max_length=200, blank=True, default="Цветочный магазин")
    logo = models.ImageField(upload_to="branding/", blank=True)
    hero_image = models.ImageField(upload_to="branding/", blank=True)
    city = models.CharField(max_length=80, default="Кондратово")
    address = models.CharField(max_length=255, default="ул. Тестовая, 1")
    phone = models.CharField(max_length=40, default="+7 (900) 000-00-00")
    email = models.EmailField(blank=True, default="hello@example.com")
    working_hours = models.CharField(max_length=120, default="Ежедневно 08:00–21:00")
    open_time = models.TimeField(default="08:00")
    close_time = models.TimeField(default="21:00")
    telegram_url = models.CharField(max_length=200, blank=True)
    vk_url = models.CharField(max_length=200, blank=True)
    primary_color = models.CharField(max_length=7, default="#3E5B36")
    accent_color = models.CharField(max_length=7, default="#9C6FA0")
    background_color = models.CharField(max_length=7, default="#FAF7F1")
    # Правила
    florist_fee = models.PositiveIntegerField("Работа флориста, коп.", default=30000)
    online_reservation_minutes = models.PositiveIntegerField("Резерв неоплаченного онлайн-заказа, мин", default=15)
    cod_unconfirmed_hold_minutes = models.PositiveIntegerField(
        "Резерв неподтверждённого заказа с оплатой при получении, мин (0 — без авто-отмены)", default=180
    )
    confirmation_hold_hours = models.PositiveIntegerField("Резерв на время подтверждения флористом, ч", default=24)
    min_lead_minutes = models.PositiveIntegerField("Минимальное время до доставки, мин", default=120)
    pickup_ready_minutes = models.PositiveIntegerField("Время подготовки самовывоза, мин", default=60)
    preorder_threshold_days = models.PositiveIntegerField(
        "Через сколько дней заказ считается предзаказом", default=2
    )
    max_order_days_ahead = models.PositiveIntegerField("Максимум дней вперёд для заказа", default=30)
    max_custom_stems = models.PositiveIntegerField(
        "Максимум стеблей в индивидуальном букете", default=30,
        help_text=f"Не больше {MAX_CUSTOM_STEMS_LIMIT}: конструктор рассчитан на букет до {MAX_CUSTOM_STEMS_LIMIT} цветков")
    min_custom_stems = models.PositiveIntegerField("Минимум стеблей в индивидуальном букете", default=3)
    allow_cash_on_delivery = models.BooleanField(
        "Разрешить оплату при получении", default=False,
        help_text="По умолчанию заказы оплачиваются только онлайн. Индивидуальные букеты — всегда онлайн",
    )
    flowers_section_enabled = models.BooleanField(
        "Раздел «Цветы поштучно» на сайте", default=True,
        help_text="Выключено — страница скрыта, отдельные цветы и зелень нельзя купить на сайте")
    constructor_section_enabled = models.BooleanField(
        "Раздел «Собрать букет» на сайте", default=True,
        help_text="Выключено — конструктор букета скрыт, индивидуальные букеты не принимаются")
    customer_login_enabled = models.BooleanField(
        "Кнопка «Войти» на сайте", default=True,
        help_text="Вход покупателей через Telegram / ВКонтакте. Выключено — кнопки входа на сайте нет")
    orders_enabled = models.BooleanField(
        "Приём заказов на сайте и в ботах", default=True,
        help_text="Выключено — витрина работает, но новые заказы (сайт, Telegram, ВК) не принимаются. "
                  "Продажа в магазине через админку работает всегда")
    orders_closed_message = models.CharField(
        "Сообщение покупателям, пока приём закрыт", max_length=300, blank=True, default="",
        help_text="Пусто — стандартный текст")
    faq = models.JSONField(
        "Частые вопросы", null=True, blank=True,
        help_text="Блоки [{title, items:[{q, a}]}]. Пусто (null) — стандартные вопросы, собранные из настроек")
    seo_pages = models.JSONField(
        "Заголовки и описания страниц для поисковиков", default=dict, blank=True,
        help_text="{страница: {title, description}}; пустые поля — стандартный текст")
    yandex_verification = models.CharField("Код подтверждения Яндекс Вебмастера", max_length=100, blank=True, default="")
    google_verification = models.CharField("Код подтверждения Google Search Console", max_length=100, blank=True,
                                           default="")
    about_title = models.CharField("О нас: заголовок", max_length=120, default="О нас")
    about_lead = models.CharField("О нас: коротко", max_length=300, blank=True)
    about_text = models.TextField("О нас: текст", blank=True)
    shop_lat = models.FloatField("Широта магазина", default=57.98644)
    shop_lon = models.FloatField("Долгота магазина", default=56.11818)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shop_settings"
        verbose_name = "Настройки магазина"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AuditLog(models.Model):
    user = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]


class AboutPhoto(models.Model):
    """Фото для карусели на странице «О нас»."""

    image = models.ImageField(upload_to="about/")
    caption = models.CharField("Подпись", max_length=140, blank=True)
    sort_order = models.IntegerField(default=0)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "about_photos"
        ordering = ["sort_order", "id"]


class StaffToken(models.Model):
    """Вход сотрудника в админку на одном устройстве. Устройств может быть несколько (телефон + компьютер):
    вход на новом устройстве не выкидывает с остальных. Смена пароля и отключение завершают все входы."""

    MAX_PER_USER = 10

    key = models.CharField("Ключ", max_length=40, primary_key=True)
    user = models.ForeignKey("core.User", related_name="staff_tokens", on_delete=models.CASCADE)
    created = models.DateTimeField("Создан", auto_now_add=True)
    user_agent = models.CharField("Устройство", max_length=200, blank=True, default="")

    class Meta:
        db_table = "staff_tokens"
        verbose_name = "Вход сотрудника"
        verbose_name_plural = "Входы сотрудников"

    def save(self, *args, **kwargs):
        if not self.key:
            import secrets

            self.key = secrets.token_hex(20)
        return super().save(*args, **kwargs)

    @classmethod
    def issue(cls, user, request=None):
        """Новый вход: старые входы этого сотрудника сверх MAX_PER_USER (самые давние) удаляются."""
        ua = (request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:200]
        token = cls.objects.create(user=user, user_agent=ua)
        keep = list(cls.objects.filter(user=user).order_by("-created").values_list("key", flat=True)[: cls.MAX_PER_USER])
        cls.objects.filter(user=user).exclude(key__in=keep).delete()
        return token

    def __str__(self):
        return f"{self.user} · {self.created:%d.%m.%Y %H:%M}"
