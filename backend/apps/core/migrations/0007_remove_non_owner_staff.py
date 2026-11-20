"""Оставляем в админ-панели только владельца: учётные записи флористов и курьеров (в т.ч. демо
florist / courier1 / courier2) удаляются. История заказов и журнал действий сохраняются — в них
остаётся имя сотрудника текстом. Новых сотрудников владелец создаёт сам: Админка → Сотрудники."""
from django.db import migrations


def remove_staff(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.filter(role="owner").update(is_demo=False)  # владелец — настоящая учётная запись магазина
    Delivery = apps.get_model("delivery", "Delivery")
    ids = list(User.objects.exclude(role="owner").values_list("pk", flat=True))
    if not ids:
        return
    Delivery.objects.filter(courier_id__in=ids).update(courier=None)
    try:
        Token = apps.get_model("authtoken", "Token")
        Token.objects.filter(user_id__in=ids).delete()
    except LookupError:
        pass
    User.objects.filter(pk__in=ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_kondratovo_shop"),
        ("authtoken", "0004_alter_tokenproxy_options"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("orders", "0004_delivery_options"),
        ("delivery", "0007_delivery_options"),
        ("inventory", "0002_initial"),
        ("notifications", "0001_initial"),
        ("customers", "0002_customer_login"),
        ("payments", "0001_initial"),
        ("recipes", "0001_initial"),
        ("reservations", "0001_initial"),
        ("carts", "0002_initial"),
        ("catalog", "0006_product_constructor_crop"),
    ]
    operations = [migrations.RunPython(remove_staff, migrations.RunPython.noop)]
