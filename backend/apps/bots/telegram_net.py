"""Связь с Telegram Bot API: адрес сервера и прокси.

С некоторых российских серверов api.telegram.org недоступен (запрос «висит» до таймаута).
Тогда в .env задают TELEGRAM_PROXY — прокси за рубежом:
    TELEGRAM_PROXY=http://логин:пароль@IP:порт      (HTTP/HTTPS-прокси)
    TELEGRAM_PROXY=socks5://логин:пароль@IP:порт    (SOCKS5-прокси)
или TELEGRAM_API_BASE — адрес своего «зеркала» Bot API (по умолчанию https://api.telegram.org).
Все обращения к Telegram (бот, уведомления, вход через Telegram) идут через этот модуль.
"""
from urllib.parse import urlsplit

import requests
from django.conf import settings

DEFAULT_API_BASE = "https://api.telegram.org"


def api_url(method):
    return f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def requests_proxies():
    proxy = settings.TELEGRAM_PROXY
    if not proxy:
        return None
    if proxy.startswith("socks5://"):  # имя api.telegram.org тоже определяется на стороне прокси
        proxy = "socks5h://" + proxy[len("socks5://"):]
    return {"http": proxy, "https": proxy}


def call(method, http_method="POST", timeout=15, **kwargs):
    """Запрос к Bot API, возвращает JSON-ответ Telegram (dict с ключом ok)."""
    r = requests.request(http_method, api_url(method), proxies=requests_proxies(), timeout=timeout, **kwargs)
    return r.json()


def proxy_display():
    """Прокси без логина и пароля — для вывода на экран."""
    if not settings.TELEGRAM_PROXY:
        return ""
    p = urlsplit(settings.TELEGRAM_PROXY)
    return f"{p.scheme}://{p.hostname}:{p.port}" if p.hostname else "(не удалось разобрать адрес)"


def aiogram_bot():
    """Bot для aiogram с теми же прокси и адресом API."""
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    kwargs = {}
    if settings.TELEGRAM_PROXY:
        kwargs["proxy"] = settings.TELEGRAM_PROXY
    if settings.TELEGRAM_API_BASE != DEFAULT_API_BASE:
        kwargs["api"] = TelegramAPIServer.from_base(settings.TELEGRAM_API_BASE)
    return Bot(settings.TELEGRAM_BOT_TOKEN, session=AiohttpSession(**kwargs))


def no_connection_hint():
    if settings.TELEGRAM_PROXY:
        return (f"Нет связи с Telegram через прокси {proxy_display()}: проверьте IP, порт, логин и пароль прокси "
                "и что прокси оплачен; если у прокси есть «Разрешённые IP» — впишите туда IP сервера")
    return NO_CONNECTION_HINT.format(base=settings.TELEGRAM_API_BASE)


NO_CONNECTION_HINT = (
    "Нет связи с Telegram ({base}). Если сервер в России, провайдер может блокировать Telegram: "
    "укажите в .env TELEGRAM_PROXY=http://логин:пароль@IP:порт (прокси за рубежом) и перезапустите контейнеры. "
    "Проверка: docker compose exec backend python manage.py check_bots"
)
