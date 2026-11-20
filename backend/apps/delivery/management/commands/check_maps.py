"""Проверка ключа Яндекс Карт и геокодера: python manage.py check_maps"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.delivery import maps_check


class Command(BaseCommand):
    help = "Проверяет ключ Яндекс Карт (JavaScript API и HTTP Геокодер) и запасной геокодер Nominatim"

    def handle(self, *args, **opts):
        r = maps_check.run()

        def status(ok, text):
            if ok is True:
                return self.style.SUCCESS("OK") + f" — {text}"
            return (self.style.ERROR if ok is False else self.style.WARNING)(text)

        self.stdout.write(f"YANDEX_MAPS_API_KEY:     {r['maps']['key'] or self.style.ERROR('не задан')}")
        if r["geocoder"]["separate_key"]:
            self.stdout.write(f"YANDEX_GEOCODER_API_KEY: {r['geocoder']['key']}")
        self.stdout.write(f"GEOCODER_PROVIDER:       {settings.GEOCODER_PROVIDER}")
        self.stdout.write("Карта (JavaScript API): " + status(r["maps"]["ok"], r["maps"]["message"]))
        self.stdout.write("HTTP Геокодер Яндекса:  " + status(r["geocoder"]["ok"], r["geocoder"]["message"]))
        if r["geocoder"]["hint"]:
            self.stdout.write(self.style.WARNING("  " + r["geocoder"]["hint"]))
        self.stdout.write("Запасной геокодер Nominatim (OpenStreetMap): " + status(r["nominatim"]["ok"], r["nominatim"]["message"]))
        self.stdout.write("Сейчас адреса проверяет: " + r["active_label"]
                          + (" — Яндекс отклонил запрос, через 10 минут сайт попробует его снова" if r["yandex_paused"] else ""))
