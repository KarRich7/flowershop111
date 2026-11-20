import uuid

from django.db import models
from django.db.models import Q


class Cart(models.Model):
    class Channel(models.TextChoices):
        WEB = "web", "Сайт"
        TELEGRAM = "telegram", "Telegram"
        VK = "vk", "ВКонтакте"

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WEB)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carts"


class CartItem(models.Model):
    class ItemType(models.TextChoices):
        PRODUCT = "product", "Товар"
        CUSTOM_BOUQUET = "custom_bouquet", "Индивидуальный букет"

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=16, choices=ItemType.choices, default=ItemType.PRODUCT)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    composition = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cart_items"
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(item_type="product", product__isnull=False) | Q(item_type="custom_bouquet", composition__isnull=False)),
                name="cart_item_kind_consistent",
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="cart_item_qty_positive"),
        ]
