"""Приём заказов (вкл/выкл), кнопка «Войти» (вкл/выкл), редактируемые «Частые вопросы», заголовки страниц для поисковиков."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0010_site_sections")]
    operations = [
        migrations.AddField(
            model_name="shopsettings", name="customer_login_enabled",
            field=models.BooleanField(
                default=True, verbose_name="Кнопка «Войти» на сайте",
                help_text="Вход покупателей через Telegram / ВКонтакте. Выключено — кнопки входа на сайте нет"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="orders_enabled",
            field=models.BooleanField(
                default=True, verbose_name="Приём заказов на сайте и в ботах",
                help_text="Выключено — витрина работает, но новые заказы (сайт, Telegram, ВК) не принимаются. "
                          "Продажа в магазине через админку работает всегда"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="orders_closed_message",
            field=models.CharField(blank=True, default="", max_length=300,
                                   verbose_name="Сообщение покупателям, пока приём закрыт",
                                   help_text="Пусто — стандартный текст"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="faq",
            field=models.JSONField(
                blank=True, null=True, verbose_name="Частые вопросы",
                help_text="Блоки [{title, items:[{q, a}]}]. Пусто (null) — стандартные вопросы, собранные из настроек"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="seo_pages",
            field=models.JSONField(blank=True, default=dict,
                                   verbose_name="Заголовки и описания страниц для поисковиков",
                                   help_text="{страница: {title, description}}; пустые поля — стандартный текст"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="yandex_verification",
            field=models.CharField(blank=True, default="", max_length=100,
                                   verbose_name="Код подтверждения Яндекс Вебмастера"),
        ),
        migrations.AddField(
            model_name="shopsettings", name="google_verification",
            field=models.CharField(blank=True, default="", max_length=100,
                                   verbose_name="Код подтверждения Google Search Console"),
        ),
    ]
