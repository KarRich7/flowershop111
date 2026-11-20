"""Переключатели разделов сайта («Цветы поштучно», «Собрать букет») и новая зона доставки в текстах.

Тексты меняются только там, где осталась фраза из демо-данных; то, что владелец написал сам, не трогаем."""
from django.db import migrations, models

TEXT_REPLACE = [
    ("по Кондратово, Перми и ближайшим сёлам", "по Кондратово и Медовому"),
    ("по Кондратово и Перми", "по Кондратово и Медовому"),
]


def _fix(text):
    for a, b in TEXT_REPLACE:
        text = text.replace(a, b)
    return text


def forwards(apps, schema_editor):
    Shop = apps.get_model("core", "ShopSettings")
    for s in Shop.objects.all():
        changed = False
        for f, limit in (("about_lead", 300), ("about_text", None), ("tagline", 200)):
            old = getattr(s, f) or ""
            new = _fix(old)
            if new != old:
                setattr(s, f, new[:limit] if limit else new)
                changed = True
        if changed:
            s.save()


class Migration(migrations.Migration):
    dependencies = [("core", "0009_staff_notifications")]
    operations = [
        migrations.AddField(
            model_name="shopsettings", name="flowers_section_enabled",
            field=models.BooleanField(
                default=True, verbose_name="Раздел «Цветы поштучно» на сайте",
                help_text="Выключено — страница скрыта, отдельные цветы и зелень нельзя купить на сайте"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="constructor_section_enabled",
            field=models.BooleanField(
                default=True, verbose_name="Раздел «Собрать букет» на сайте",
                help_text="Выключено — конструктор букета скрыт, индивидуальные букеты не принимаются"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
