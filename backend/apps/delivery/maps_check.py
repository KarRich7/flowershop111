"""Проверка ключа Яндекс Карт и геокодера. Используется командой check_maps и карточкой в настройках админки."""
import re
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

from . import geo

TEST_ADDRESS = "Пермский край, Кондратово, Красавинская улица, 8"
PROVIDER_NAMES = {"yandex": "Яндекс", "nominatim": "Nominatim (OpenStreetMap)", "off": "выключена"}
HINT_403 = ("Ключ отклонён. Частые причины: ключ создан меньше 15 минут назад (ещё активируется); ключ выпущен не для "
            "«JavaScript API и HTTP Геокодер»; в ключе включено ограничение по HTTP Referer или IP — запросы сервера "
            "его не проходят. Выпустите отдельный ключ без ограничений и укажите его в YANDEX_GEOCODER_API_KEY")


def mask(key):
    return f"{key[:8]}…{key[-4:]}" if len(key) > 14 else ("задан" if key else "")


def _check_map(key, origin):
    url = "https://api-maps.yandex.ru/2.1/?" + urllib.parse.urlencode({"lang": "ru_RU", "apikey": key})
    try:
        req = urllib.request.Request(url, headers={"Referer": origin, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            m = re.search(r'"apikeyValid":(true|false)', r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "message": f"Не удалось проверить: {e}"}
    if m and m.group(1) == "true":
        return {"ok": True, "message": f"Ключ принят для {origin}"}
    return {"ok": False, "message": (
        f"Ключ не принят для {origin}: карта показывается в ограниченном режиме. Проверьте, что ключ — для «JavaScript API "
        f"и HTTP Геокодер», и добавьте адрес сайта (ваш домен и localhost:3000) в ограничения по HTTP Referer")}


def run():
    """Возвращает словарь с результатами проверок (без самих ключей)."""
    maps_key, geo_key = settings.YANDEX_MAPS_API_KEY, settings.YANDEX_GEOCODER_API_KEY
    origin = settings.FRONTEND_URL.rstrip("/") + "/"
    out = {
        "maps": {"key": mask(maps_key), "ok": None, "message": "Ключ не задан: карта работает в ограниченном тестовом режиме"},
        "geocoder": {"key": mask(geo_key), "separate_key": bool(geo_key and geo_key != maps_key), "ok": None,
                     "message": "Ключ не задан: адреса проверяет Nominatim (OpenStreetMap)", "hint": ""},
        "nominatim": {"ok": None, "message": ""},
        "provider_setting": settings.GEOCODER_PROVIDER,
    }
    if maps_key:
        out["maps"].update(_check_map(maps_key, origin))
    if geo_key:
        try:
            rows = geo._yandex_request(TEST_ADDRESS, 1)
            out["geocoder"].update(ok=True, message=f"Работает: {rows[0].full_address or rows[0].address}" if rows
                                   else "Работает (ответ без результатов)")
            cache.delete(geo.YANDEX_DOWN_KEY)
        except geo.GeocoderUnavailable as e:
            geo._yandex_failed(e)
            out["geocoder"].update(ok=False, message=f"Ошибка: {e.detail}", hint=HINT_403 if "403" in e.detail else "")
    try:
        rows = geo._nominatim_search(TEST_ADDRESS, 1)
        out["nominatim"] = {"ok": bool(rows), "message": "Работает" if rows else "Нет результатов"}
    except geo.GeocoderUnavailable as e:
        out["nominatim"] = {"ok": False, "message": f"Ошибка: {e.detail}"}
    active = geo.provider()
    out["active"] = active
    out["active_label"] = PROVIDER_NAMES.get(active, active)
    out["yandex_paused"] = bool(cache.get(geo.YANDEX_DOWN_KEY))
    return out
