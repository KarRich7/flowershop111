from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Запуск ВК-бота (Bots Long Poll API). Без VK_GROUP_TOKEN/VK_GROUP_ID — демонстрационный режим."

    def handle(self, *args, **opts):
        if not (settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID):
            self.stdout.write(self.style.WARNING(
                "VK_GROUP_TOKEN / VK_GROUP_ID не заданы — настоящий ВК-бот не запущен. "
                "Используйте демонстрационный симулятор: /simulator на сайте."))
            return
        from apps.bots.adapters.vk import VKBot

        VKBot().run()
