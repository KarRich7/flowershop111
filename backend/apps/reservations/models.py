from django.db import models
from django.db.models import Q


class StockReservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        CONSUMED = "consumed", "Списан"
        RELEASED = "released", "Снят"
        EXPIRED = "expired", "Истёк"

    class Kind(models.TextChoices):
        FINISHED = "finished", "Готовый товар"
        COMPONENT = "component", "Материал для сборки"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="reservations")
    order_item = models.ForeignKey("orders.OrderItem", null=True, on_delete=models.CASCADE, related_name="reservations")
    item = models.ForeignKey("inventory.InventoryItem", on_delete=models.PROTECT, related_name="reservations")
    quantity = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "stock_reservations"
        indexes = [models.Index(fields=["status", "expires_at"]), models.Index(fields=["order", "status"])]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="reservation_qty_positive")]
