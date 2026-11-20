"""Конструктор букета: не больше 30 цветков (раньше по умолчанию было 101)."""
from django.db import migrations, models


def cap(apps, schema_editor):
    ShopSettings = apps.get_model("core", "ShopSettings")
    ShopSettings.objects.filter(max_custom_stems__gt=30).update(max_custom_stems=30)
    ShopSettings.objects.filter(min_custom_stems__gt=30).update(min_custom_stems=3)


class Migration(migrations.Migration):
    dependencies = [("core", "0004_aboutphoto_shopsettings_about_lead_and_more")]

    operations = [
        migrations.AlterField(
            model_name="shopsettings",
            name="max_custom_stems",
            field=models.PositiveIntegerField(
                default=30, help_text="Не больше 30: конструктор рассчитан на букет до 30 цветков",
                verbose_name="Максимум стеблей в индивидуальном букете"),
        ),
        migrations.RunPython(cap, migrations.RunPython.noop),
    ]
