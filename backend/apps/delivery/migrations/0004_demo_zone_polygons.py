"""Данные: границы демо-зон на карте и бесплатная доставка от 1 500 ₽ во всех зонах."""
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.delivery.zones_data import FREE_DELIVERY_FROM, ZONE_COLORS, demo_polygons

    Zone = apps.get_model("delivery", "DeliveryZone")
    polygons = demo_polygons()
    for z in Zone.objects.all():
        if not z.polygons and z.name in polygons:
            z.polygons = polygons[z.name]
        if not z.color:
            z.color = ZONE_COLORS.get(z.name, "")
        z.free_from = FREE_DELIVERY_FROM
        z.save(update_fields=["polygons", "color", "free_from"])


class Migration(migrations.Migration):
    dependencies = [("delivery", "0003_zone_polygons_delivery_coords")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
