"""Входы сотрудников на нескольких устройствах (телефон + компьютер одновременно).
Текущие входы переносятся — после обновления никого не выкидывает из админки."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def copy_tokens(apps, schema_editor):
    try:
        Token = apps.get_model("authtoken", "Token")
    except LookupError:
        return
    StaffToken = apps.get_model("core", "StaffToken")
    for t in Token.objects.all():
        st = StaffToken.objects.create(key=t.key, user_id=t.user_id)
        StaffToken.objects.filter(pk=st.pk).update(created=t.created)  # срок жизни входа считается от старой даты


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_remove_non_owner_staff'),
        ('authtoken', '0004_alter_tokenproxy_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffToken',
            fields=[
                ('key', models.CharField(max_length=40, primary_key=True, serialize=False, verbose_name='Ключ')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Создан')),
                ('user_agent', models.CharField(blank=True, default='', max_length=200, verbose_name='Устройство')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_tokens', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Вход сотрудника',
                'verbose_name_plural': 'Входы сотрудников',
                'db_table': 'staff_tokens',
            },
        ),
        migrations.RunPython(copy_tokens, migrations.RunPython.noop),
    ]
