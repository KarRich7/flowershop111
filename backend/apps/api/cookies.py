"""Секретные токены входа — в cookie с флагом HttpOnly: JavaScript страницы их не видит, поэтому даже
внедрённый на страницу скрипт (XSS) не сможет унести токен и войти с другого устройства.

* cu_staff    — вход сотрудника в админку (путь /api/v1/admin);
* cu_customer — вход покупателя через Telegram/ВК (путь /api/v1);
* cu_login    — незавершённый вход покупателя, пока он подтверждает его в мессенджере (10 мин).

SameSite=Strict — браузер не отправит cookie с чужого сайта. Дополнительно запросы, меняющие данные,
с cookie принимаются только с заголовком «X-Requested-With: fetch» (его ставит наш сайт; чужой сайт
без разрешения CORS добавить такой заголовок не может) — защита от подделки запросов (CSRF).
"""
from django.conf import settings

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
STAFF_COOKIE, STAFF_PATH = "cu_staff", "/api/v1/admin"
CUSTOMER_COOKIE, CUSTOMER_PATH = "cu_customer", "/api/v1"
LOGIN_COOKIE, LOGIN_PATH = "cu_login", "/api/v1/account/login"


def set_secret_cookie(response, name, value, max_age, path):
    response.set_cookie(name, value, max_age=int(max_age), path=path, httponly=True, samesite="Strict",
                        secure=bool(getattr(settings, "SECURE_COOKIES", False)))
    return response


def clear_cookie(response, name, path):
    response.delete_cookie(name, path=path, samesite="Strict")
    return response


def from_our_site(request):
    return request.META.get("HTTP_X_REQUESTED_WITH", "").lower() == "fetch"


def cookie_usable(request):
    """Cookie можно учитывать: безопасный запрос (чтение) или запрос с нашего сайта."""
    return request.method in SAFE_METHODS or from_our_site(request)


def read_cookie(request, name):
    raw = (request.COOKIES.get(name) or "").strip()
    return raw if raw and len(raw) <= 128 and cookie_usable(request) else ""
