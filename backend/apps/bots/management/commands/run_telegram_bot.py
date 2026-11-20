from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Запуск Telegram-бота (long polling). Без TELEGRAM_BOT_TOKEN — сообщает о демонстрационном режиме."

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.WARNING(
                "TELEGRAM_BOT_TOKEN не задан — настоящий Telegram-бот не запущен. "
                "Используйте демонстрационный симулятор: /simulator на сайте."))
            return
        from apps.bots.adapters.telegram import run

        run()
