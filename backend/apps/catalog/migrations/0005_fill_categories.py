from django.db import migrations

KIND = {"bouquet": "bouquet", "flower": "flower", "greenery": "flower"}


def fill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    Category = apps.get_model("catalog", "Category")
    seen = set()
    for p in Product.objects.filter(type__in=KIND.keys()).order_by("sort_order", "name"):
        name = (p.category or "").strip()[:60]
        kind = KIND[p.type]
        if name and (kind, name) not in seen:
            seen.add((kind, name))
            Category.objects.get_or_create(kind=kind, name=name, defaults={"sort_order": len(seen) * 10})


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_product_constructor_source_category")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
