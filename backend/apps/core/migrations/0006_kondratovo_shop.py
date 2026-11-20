"""Данные: демо-настройки магазина переезжают из Екатеринбурга в Кондратово (ЖК «Медовый», Пермский край).

Меняются только значения, оставшиеся от демо-данных; то, что владелец вписал сам, не трогаем."""
from django.db import migrations

OLD_POINT = (56.838, 60.5975)
NEW_POINT = (57.98644, 56.11818)
TEXT_REPLACE = [
    ("в Екатеринбурге", "в Кондратово"),
    ("по Екатеринбургу", "по Кондратово, Перми и ближайшим сёлам"),
    ("Екатеринбургу", "Кондратово и Перми"),
    ("Екатеринбурге", "Кондратово"),
    ("Екатеринбург", "Кондратово"),
]


def _fix(text):
    for a, b in TEXT_REPLACE:
        text = text.replace(a, b)
    return text


def forwards(apps, schema_editor):
    Shop = apps.get_model("core", "ShopSettings")
    About = apps.get_model("core", "AboutPhoto")
    for s in Shop.objects.all():
        if s.city.strip() == "Екатеринбург":
            s.city = "Кондратово"
        if "Екатеринбург" in s.address and "демо" in s.address:
            s.address = "Пермский край, д. Кондратово, ЖК «Медовый» (демо-адрес — укажите точный в настройках)"
        if round(s.shop_lat, 3) == OLD_POINT[0] and round(s.shop_lon, 3) == round(OLD_POINT[1], 3):
            s.shop_lat, s.shop_lon = NEW_POINT
        for f, limit in (("about_lead", 300), ("about_text", None), ("tagline", 200)):
            value = _fix(getattr(s, f) or "")
            setattr(s, f, value[:limit] if limit else value)
        s.save()
    for p in About.objects.filter(caption__contains="Екатеринбург"):
        p.caption = _fix(p.caption)[:140]
        p.save(update_fields=["caption"])


class Migration(migrations.Migration):
    dependencies = [("core", "0005_max_custom_stems_30")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
