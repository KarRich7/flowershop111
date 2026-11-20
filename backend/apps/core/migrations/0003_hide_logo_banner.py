"""Данные: демо-баннер с логотипом больше не используется как обложка (логотип уже есть в шапке сайта).
Файл остаётся в media/branding — его можно снова загрузить в «Настройках»."""
from django.db import migrations


def forwards(apps, schema_editor):
    S = apps.get_model("core", "ShopSettings")
    S.objects.filter(hero_image="branding/banner.jpg").update(hero_image="")


class Migration(migrations.Migration):
    dependencies = [("core", "0002_cod_shop_location")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
