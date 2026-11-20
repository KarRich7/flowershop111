import secrets

from django.db import models
from django.db.models import F, Q


def new_public_token():
    return secrets.token_urlsafe(18)


class Order(models.Model):
    class Source(models.TextChoices):
        WEB = "web", "Сайт"
        TELEGRAM = "telegram", "Telegram"
        VK = "vk", "ВКонтакте"
        STORE = "store", "Магазин"

    class Status(models.TextChoices):
        NEW = "new", "Новый"
        AWAITING_CONFIRMATION = "awaiting_confirmation", "Ожидает подтверждения"
        AWAITING_PAYMENT = "awaiting_payment", "Ожидает оплаты"
        CONFIRMED = "confirmed", "Подтверждён"
        ASSEMBLING = "assembling", "Собирается"
        READY = "ready", "Готов"
        HANDED_TO_COURIER = "handed_to_courier", "Передан курьеру"
        AWAITING_PICKUP = "awaiting_pickup", "Ожидает самовывоза"
        DELIVERED = "delivered", "Доставлен / выдан"
        COMPLETED = "completed", "Завершён"
        CANCELLED = "cancelled", "Отменён"

    class PaymentMethod(models.TextChoices):
        ONLINE = "online", "Онлайн"
        ON_DELIVERY = "on_delivery", "При получении"
        IN_STORE = "in_store", "В магазине"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Не оплачен"
        PENDING = "pending", "Ожидается"
        PAID = "paid", "Оплачен"
        REFUND_PENDING = "refund_pending", "Возврат"
        REFUNDED = "refunded", "Возвращён"
        FAILED = "failed", "Ошибка"

    class Fulfillment(models.TextChoices):
        DELIVERY = "delivery", "Доставка"
        PICKUP = "pickup", "Самовывоз"
        IN_STORE = "in_store", "Покупка в магазине"

    number = models.CharField(max_length=20, unique=True, null=True)
    public_token = models.CharField(max_length=40, unique=True, default=new_public_token)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices)
    customer = models.ForeignKey("customers.Customer", null=True, on_delete=models.PROTECT, related_name="orders")
    contact_name = models.CharField(max_length=160, blank=True)
    contact_phone = models.CharField(max_length=16, blank=True)
    contact_email = models.EmailField(blank=True)
    recipient_name = models.CharField(max_length=160, blank=True)
    recipient_phone = models.CharField(max_length=16, blank=True)
    items_total = models.PositiveIntegerField(default=0)
    delivery_cost = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    fulfillment = models.CharField(max_length=16, choices=Fulfillment.choices)
    pickup_point = models.CharField(max_length=255, blank=True)
    fulfillment_date = models.DateField(null=True, blank=True)
    slot = models.ForeignKey("delivery.DeliverySlot", null=True, blank=True, on_delete=models.SET_NULL)
    time_from = models.TimeField(null=True, blank=True)
    time_to = models.TimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    card_text = models.CharField(max_length=300, blank=True)
    photo_before = models.BooleanField("Прислать фото букета перед отправкой", default=False)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEW)
    is_preorder = models.BooleanField(default=False)
    requires_confirmation = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "reservation_expires_at"]),
            models.Index(fields=["fulfillment_date"]),
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total=F("items_total") + F("delivery_cost")), name="order_total_consistent"),
        ]

    def __str__(self):
        return f"Заказ №{self.number}"


class OrderItem(models.Model):
    """Строка заказа — неизменяемый снимок (UPDATE запрещён триггером в БД)."""

    class ItemType(models.TextChoices):
        PRODUCT = "product", "Товар"
        CUSTOM_BOUQUET = "custom_bouquet", "Индивидуальный букет"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=16, choices=ItemType.choices)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL)
    inventory_item = models.ForeignKey("inventory.InventoryItem", null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=32, blank=True)
    product_type = models.CharField(max_length=16, blank=True)
    unit_price = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()
    line_total = models.PositiveIntegerField()
    composition = models.JSONField(null=True, blank=True)
    fulfillment_plan = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "order_items"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="order_item_qty_positive"),
            models.CheckConstraint(condition=Q(line_total=F("unit_price") * F("quantity")), name="order_item_total_consistent"),
        ]


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=32)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    message = models.TextField(blank=True)
    actor = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_events"
        ordering = ["created_at", "id"]


def _photo_path(instance, filename):
    import uuid

    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "jpg").lower()[:5]
    return f"orders/photos/{uuid.uuid4().hex}.{ext}"


class OrderPhoto(models.Model):
    """Фото собранного букета: флорист загружает перед отправкой, покупатель видит на странице заказа."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=_photo_path)
    uploaded_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_photos"
        ordering = ["created_at"]
