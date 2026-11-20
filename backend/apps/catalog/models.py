from django.db import models

from apps.inventory.models import InventoryItem


class Category(models.Model):
    """Категория витрины: разделы «Готовые букеты» и «Цветы поштучно» (зелень — тоже здесь).
    Товар ссылается на категорию по названию (Product.category) — переименование и удаление
    категории переносят товары в сервисе apps.catalog.categories."""

    class Kind(models.TextChoices):
        BOUQUET = "bouquet", "Готовые букеты"
        FLOWER = "flower", "Цветы поштучно"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField("Название", max_length=60)
    sort_order = models.IntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalog_categories"
        ordering = ["kind", "sort_order", "name"]
        constraints = [models.UniqueConstraint(fields=["kind", "name"], name="uniq_category_kind_name")]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"


class Product(models.Model):
    """Витринная карточка товара. Цена и остаток берутся из связанного складского материала."""

    class Type(models.TextChoices):
        BOUQUET = "bouquet", "Готовый букет"
        FLOWER = "flower", "Цветок поштучно"
        GREENERY = "greenery", "Зелень"
        PACKAGING = "packaging", "Упаковка"
        RIBBON = "ribbon", "Лента"
        CARD = "card", "Открытка"
        ADDON = "addon", "Дополнительный товар"

    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    type = models.CharField(max_length=16, choices=Type.choices)
    category = models.CharField("Категория витрины", max_length=60, blank=True)
    species = models.CharField("Вид (для цветов)", max_length=60, blank=True)
    color = models.CharField("Цвет", max_length=40, blank=True)
    color_hex = models.CharField(max_length=7, blank=True)
    short_description = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    height_cm = models.PositiveIntegerField(null=True, blank=True)
    inventory_item = models.OneToOneField(InventoryItem, on_delete=models.PROTECT, related_name="product")
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    allow_made_to_order = models.BooleanField(
        "Можно собрать под заказ", default=False,
        help_text="Если готовых букетов нет, материалы резервируются по рецептуре и списываются при сборке",
    )
    constructor_enabled = models.BooleanField("Доступен в конструкторе", default=False)
    sort_order = models.IntegerField(default=100)
    constructor_image = models.ImageField(
        "Фото для конструктора", upload_to="constructor/", blank=True,
        help_text="Цветы и зелень — бутон или ветка без фона; упаковка — фрагмент материала (текстура)",
    )
    constructor_source = models.ImageField(
        "Исходная вырезка", upload_to="constructor/src/", blank=True,
        help_text="Весь объект без фона — из него флорист заново выбирает кадр бутона",
    )
    constructor_crop = models.JSONField("Кадр бутона {x, y, w, h}", default=dict, blank=True)
    photo_credit = models.CharField(max_length=300, blank=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["type", "is_active"]), models.Index(fields=["category"])]

    def __str__(self):
        return self.name

    @property
    def category_kind(self):
        return {"bouquet": "bouquet", "flower": "flower", "greenery": "flower"}.get(self.type)

    @property
    def price(self):
        return self.inventory_item.sale_price or 0


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")
    alt = models.CharField(max_length=200, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "product_images"
        ordering = ["sort_order", "id"]
