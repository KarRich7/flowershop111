from django.db import models
from django.db.models import Q


ASK_RECIPIENT_ADDRESS = "Адрес уточним у получателя"


class DeliveryZone(models.Model):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    price = models.PositiveIntegerField("Стоимость, коп.")
    free_from = models.PositiveIntegerField("Бесплатно от суммы, коп.", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=100)
    # Границы зоны на карте: список многоугольников, каждый — список точек [широта, долгота].
    polygons = models.JSONField("Границы зоны", default=list, blank=True)
    color = models.CharField(max_length=7, blank=True)
    # Удалённая зона, по которой уже были доставки: скрыта из настроек и не принимает заказы,
    # но остаётся в истории заказов
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "delivery_zones"
        ordering = ["sort_order", "name"]

    def cost_for(self, items_total):
        if self.free_from and items_total >= self.free_from:
            return 0
        return self.price


class DeliverySlot(models.Model):
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField("Максимум доставок в интервал", default=4)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "delivery_slots"
        ordering = ["start_time"]
        constraints = [models.CheckConstraint(condition=Q(end_time__gt=models.F("start_time")), name="slot_end_after_start")]

    @property
    def label(self):
        return f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"


class Delivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает назначения"
        ASSIGNED = "assigned", "Курьер назначен"
        IN_TRANSIT = "in_transit", "В пути"
        DELIVERED = "delivered", "Доставлено"
        FAILED = "failed", "Не доставлено"
        CANCELLED = "cancelled", "Отменено"

    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="delivery")
    zone = models.ForeignKey(DeliveryZone, null=True, on_delete=models.PROTECT)
    address = models.CharField(max_length=255)
    apartment = models.CharField(max_length=20, blank=True)
    entrance = models.CharField(max_length=20, blank=True)
    floor = models.CharField(max_length=20, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    address_verified = models.BooleanField("Адрес проверен геокодером", default=False)
    # как вручить: так делают почти все цветочные сервисы
    ask_recipient = models.BooleanField("Адрес узнать у получателя", default=False)
    surprise = models.BooleanField("Сюрприз: не звонить получателю заранее", default=False)
    anonymous = models.BooleanField("Не говорить, от кого букет", default=False)
    date = models.DateField()
    slot = models.ForeignKey(DeliverySlot, null=True, on_delete=models.PROTECT)
    courier = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="deliveries", limit_choices_to={"role": "courier"})
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    courier_comment = models.CharField(max_length=255, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "deliveries"
        indexes = [models.Index(fields=["date", "slot"]), models.Index(fields=["courier", "date"])]

    @property
    def address_pending(self):
        """Покупатель не знал адрес, а флорист ещё не вписал тот, что назвал получатель."""
        return self.ask_recipient and self.address.startswith(ASK_RECIPIENT_ADDRESS)
