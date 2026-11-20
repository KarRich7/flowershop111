import uuid

from django.db import models
from django.db.models import F, Q

MAIN_LOCATION = "main"


class InventoryItem(models.Model):
    """Складской материал: цветок, зелень, упаковка, лента, открытка, доп. товар или готовый букет."""

    class Category(models.TextChoices):
        BOUQUET = "bouquet", "Готовый букет"
        FLOWER = "flower", "Цветок"
        GREENERY = "greenery", "Зелень"
        PACKAGING = "packaging", "Упаковка"
        RIBBON = "ribbon", "Лента"
        CARD = "card", "Открытка"
        ADDON = "addon", "Дополнительный товар"
        CONSUMABLE = "consumable", "Расходный материал"

    class Unit(models.TextChoices):
        PCS = "pcs", "шт"
        STEM = "stem", "стебель"
        BRANCH = "branch", "ветка"
        SHEET = "sheet", "лист"
        CUT = "cut", "отрез"

    sku = models.CharField("Артикул", max_length=32, unique=True)
    name = models.CharField("Название", max_length=160)
    category = models.CharField("Категория", max_length=16, choices=Category.choices)
    unit = models.CharField("Ед. изм.", max_length=8, choices=Unit.choices, default=Unit.PCS)
    purchase_price = models.PositiveIntegerField("Закупочная цена, коп.", default=0)
    sale_price = models.PositiveIntegerField("Цена продажи, коп.", null=True, blank=True)
    min_stock = models.PositiveIntegerField("Минимальный остаток", default=0)
    is_active = models.BooleanField("Активен", default=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_items"
        ordering = ["category", "name"]
        indexes = [models.Index(fields=["category", "is_active"])]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class StockBalance(models.Model):
    """Остаток по складу. Доступно = фактический остаток − резерв. Ограничения целостности — в БД."""

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="balances")
    location = models.CharField(max_length=32, default=MAIN_LOCATION)
    quantity = models.IntegerField("Фактический остаток", default=0)
    reserved = models.IntegerField("Зарезервировано", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_balances"
        constraints = [
            models.UniqueConstraint(fields=["item", "location"], name="uniq_balance_item_location"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="balance_quantity_non_negative"),
            models.CheckConstraint(condition=Q(reserved__gte=0), name="balance_reserved_non_negative"),
            models.CheckConstraint(condition=Q(reserved__lte=F("quantity")), name="balance_reserved_lte_quantity"),
        ]

    @property
    def available(self):
        return self.quantity - self.reserved


class StockMovement(models.Model):
    """Журнал физических изменений остатков (резервы фиксируются отдельно в stock_reservations)."""

    class Type(models.TextChoices):
        SUPPLY = "supply", "Поставка"
        WRITE_OFF = "write_off", "Списание"
        STORE_SALE = "store_sale", "Продажа в магазине"
        ORDER_FULFILLMENT = "order_fulfillment", "Отгрузка по заказу"
        ADJUSTMENT = "adjustment", "Корректировка"
        INVENTORY = "inventory", "Инвентаризация"
        ASSEMBLY_CONSUME = "assembly_consume", "Расход на сборку"
        ASSEMBLY_PRODUCE = "assembly_produce", "Сборка букета"
        RETURN = "return", "Возврат на склад"

    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    location = models.CharField(max_length=32, default=MAIN_LOCATION)
    movement_type = models.CharField(max_length=24, choices=Type.choices)
    quantity_delta = models.IntegerField()
    balance_after = models.IntegerField()
    unit_cost = models.PositiveIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    user = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL)
    batch_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_movements"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["item", "created_at"]),
            models.Index(fields=["movement_type", "created_at"]),
        ]
        constraints = [models.CheckConstraint(condition=~Q(quantity_delta=0), name="movement_delta_non_zero")]
