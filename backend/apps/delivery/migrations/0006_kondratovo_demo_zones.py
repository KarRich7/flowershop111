"""Данные: демо-зоны Екатеринбурга заменяются зонами мастерской в Кондратово (Пермский край).

* Зоны меняются, только если в базе остались исключительно прежние демо-зоны (владелец своих не создавал).
  Зоны, по которым уже были доставки, не удаляются, а уходят в архив — история заказов сохраняется.
* Адреса демо-заказов (флаг is_demo) переезжают на улицы Кондратово и Перми."""
from django.db import migrations

# Адреса демо-заказов: прежние улицы Екатеринбурга → Кондратово / Пермь (координаты — OpenStreetMap)
KRASAVINSKAYA = ("Кондратово, Красавинская улица, 8", 57.98832, 56.12075)
KOSMONAVTOV = ("Пермь, шоссе Космонавтов, 111", 57.99078, 56.20541)
KAMSKAYA = ("Кондратово, Камская улица, 5Б", 57.97888, 56.1053)
LENINA = ("Пермь, улица Ленина, 50", 58.0119, 56.2424)
MIRA = ("Пермь, улица Мира, 41", 57.97662, 56.18713)
KOMSOMOLSKY = ("Пермь, Комсомольский проспект, 30", 58.01018, 56.24046)
DEMO_ADDRESSES = [
    ("Малышева", KRASAVINSKAYA), ("Мира, 19", KOSMONAVTOV), ("Крауля", KAMSKAYA), ("Шварца", LENINA),
    ("Геннина", MIRA), ("Белинского", KOMSOMOLSKY), ("Ленина, 24/8", KOMSOMOLSKY), ("Шейнкмана", KOSMONAVTOV),
    ("Ленина, 1", KRASAVINSKAYA),
]


def replace_zones(Zone, Delivery):
    from apps.delivery.zones_data import DEMO_ZONES, OLD_DEMO_ZONES, ZONE_COLORS, demo_polygons

    zones = list(Zone.objects.filter(is_archived=False))
    if not zones or any(z.name not in OLD_DEMO_ZONES for z in zones):
        return
    for z in zones:
        if Delivery.objects.filter(zone_id=z.pk).exists():
            z.is_active, z.is_archived = False, True
            z.save(update_fields=["is_active", "is_archived"])
        else:
            z.delete()
    polygons = demo_polygons()
    for name, desc, price, free_from, order in DEMO_ZONES:
        Zone.objects.create(name=name, description=desc, price=price, free_from=free_from, sort_order=order,
                            polygons=polygons.get(name, []), color=ZONE_COLORS.get(name, ""))


def remap_demo_addresses(Zone, Delivery):
    from django.db.models import Q

    from apps.delivery.geo import point_in_ring

    zones = list(Zone.objects.filter(is_active=True, is_archived=False).order_by("sort_order", "id"))
    if not any(z.name.startswith("Кондратово") for z in zones):
        return  # владелец настроил свои зоны — демо-адреса не трогаем
    demo = Q(order__is_demo=True) | Q(order__customer__is_demo=True)
    for d in Delivery.objects.filter(demo):
        new = next((v for key, v in DEMO_ADDRESSES if key in d.address), None)
        if not new:
            continue
        d.address, d.lat, d.lon = new
        d.zone = next((z for z in zones if any(point_in_ring(d.lat, d.lon, r) for r in z.polygons or [])), d.zone)
        d.save(update_fields=["address", "lat", "lon", "zone"])


def forwards(apps, schema_editor):
    Zone, Delivery = apps.get_model("delivery", "DeliveryZone"), apps.get_model("delivery", "Delivery")
    replace_zones(Zone, Delivery)
    remap_demo_addresses(Zone, Delivery)


class Migration(migrations.Migration):
    dependencies = [("delivery", "0005_deliveryzone_is_archived")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
