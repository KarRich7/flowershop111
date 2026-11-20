"""Категории витрины: создание, переименование, порядок, удаление с переносом товаров."""
from django.db import transaction
from django.db.models import Max

from apps.core import validation as v
from apps.core.errors import NotFound, ValidationError

from .models import Category, Product

TYPES_BY_KIND = {Category.Kind.BOUQUET: ["bouquet"], Category.Kind.FLOWER: ["flower", "greenery"]}


def kind_of(product_type):
    return {"bouquet": Category.Kind.BOUQUET, "flower": Category.Kind.FLOWER, "greenery": Category.Kind.FLOWER}.get(product_type)


def products_of(cat):
    return Product.objects.filter(type__in=TYPES_BY_KIND[cat.kind], category=cat.name)


def _name(value, kind, exclude_id=None):
    name = v.text(value, "name", "Название категории", required=True, min_len=2, max_len=60)
    qs = Category.objects.filter(kind=kind, name__iexact=name)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        v.fail("name", f"Категория «{name}» уже есть")
    return name


def create(kind, name):
    v.choice(kind, "kind", "Раздел", Category.Kind.values)
    name = _name(name, kind)
    top = Category.objects.filter(kind=kind).aggregate(m=Max("sort_order"))["m"] or 0
    return Category.objects.create(kind=kind, name=name, sort_order=top + 10)


def get(cat_id):
    try:
        cat = Category.objects.filter(pk=int(cat_id)).first()
    except (TypeError, ValueError):
        cat = None
    if not cat:
        raise NotFound("Категория не найдена")
    return cat


@transaction.atomic
def rename(cat, name):
    name = _name(name, cat.kind, exclude_id=cat.pk)
    if name != cat.name:
        products_of(cat).update(category=name)
        cat.name = name
        cat.save(update_fields=["name"])
    return cat


@transaction.atomic
def delete(cat, move_to=None):
    """Товары удаляемой категории переносятся в move_to или остаются без категории."""
    target = None
    if move_to not in (None, "", 0, "0"):
        target = get(move_to)
        if target.kind != cat.kind or target.pk == cat.pk:
            raise ValidationError("Выберите другую категорию этого же раздела", details={"field": "move_to"})
    moved = products_of(cat).update(category=target.name if target else "")
    cat.delete()
    return moved


@transaction.atomic
def add_products(cat, product_ids):
    if not isinstance(product_ids, list) or not product_ids:
        raise ValidationError("Выберите товары", details={"field": "product_ids"})
    try:
        ids = [int(i) for i in product_ids][:500]
    except (TypeError, ValueError):
        raise ValidationError("Некорректный список товаров")
    qs = Product.objects.filter(pk__in=ids, type__in=TYPES_BY_KIND[cat.kind])
    if qs.count() != len(set(ids)):
        raise ValidationError("Часть товаров не найдена или относится к другому разделу")
    return qs.update(category=cat.name)


@transaction.atomic
def reorder(kind, ids):
    v.choice(kind, "kind", "Раздел", Category.Kind.values)
    cats = {c.pk: c for c in Category.objects.filter(kind=kind)}
    try:
        ids = [int(i) for i in ids or []]
    except (TypeError, ValueError):
        raise ValidationError("Некорректный порядок")
    if set(ids) != set(cats):
        raise ValidationError("Передайте все категории раздела")
    for n, pk in enumerate(ids):
        Category.objects.filter(pk=pk).update(sort_order=(n + 1) * 10)


def clean_product_category(product_type, value):
    """Категория товара витрины должна существовать; для упаковки, лент и т.п. — произвольная подпись."""
    kind = kind_of(product_type)
    name = v.text(value, "category", "Категория", max_len=60)
    if not kind or not name:
        return name
    cat = Category.objects.filter(kind=kind, name__iexact=name).first()
    if not cat:
        v.fail("category", f"Категории «{name}» нет. Выберите из списка или создайте её в разделе «Категории»")
    return cat.name


def ordered_names(kind):
    return list(Category.objects.filter(kind=kind).values_list("name", flat=True))
