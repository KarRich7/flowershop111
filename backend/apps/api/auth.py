import hmac
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle

TOKEN_TTL = timedelta(hours=int(getattr(settings, "STAFF_TOKEN_TTL_HOURS", 72)))


class BearerTokenAuthentication(TokenAuthentication):
    """Токен сотрудника: «Authorization: Bearer <token>». Токен истекает через TOKEN_TTL."""

    keyword = "Bearer"

    def get_model(self):
        from apps.core.models import StaffToken

        return StaffToken

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created < timezone.now() - TOKEN_TTL:
            token.delete()
            raise AuthenticationFailed("Сессия истекла, войдите снова")
        return user, token


class CookieTokenAuthentication(BearerTokenAuthentication):
    """Тот же токен сотрудника, но из HttpOnly-cookie cu_staff (так входит сайт; JavaScript токен не видит).
    Неверный/просроченный cookie или запрос без «X-Requested-With: fetch» — как без входа."""

    def authenticate(self, request):
        from .cookies import STAFF_COOKIE, read_cookie

        key = read_cookie(request, STAFF_COOKIE)
        if not key:
            return None
        try:
            return self.authenticate_credentials(key)
        except AuthenticationFailed:
            return None


def set_staff_cookie(response, token):
    from .cookies import STAFF_COOKIE, STAFF_PATH, set_secret_cookie

    return set_secret_cookie(response, STAFF_COOKIE, token.key, TOKEN_TTL.total_seconds(), STAFF_PATH)


class BotPrincipal:
    """Сервисная учётная запись бота. Канал определяется сервером, а не телом запроса."""

    is_authenticated = True
    is_active = True
    is_bot = True
    role = None
    pk = None

    def __init__(self, channel):
        self.channel = channel
        self.username = f"{channel}-bot"


class BotServiceAuthentication(BaseAuthentication):
    """«Authorization: Bot <BOT_SERVICE_TOKEN>» + «X-Bot-Channel: telegram|vk»."""

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bot "):
            return None
        token = header[4:].strip()
        if not settings.BOT_SERVICE_TOKEN or not hmac.compare_digest(token, settings.BOT_SERVICE_TOKEN):
            raise AuthenticationFailed("Неверный сервисный токен бота")
        channel = request.META.get("HTTP_X_BOT_CHANNEL", "")
        if channel not in ("telegram", "vk"):
            raise AuthenticationFailed("Заголовок X-Bot-Channel должен быть telegram или vk")
        return BotPrincipal(channel), None


def request_channel(request):
    user = getattr(request, "user", None)
    return user.channel if getattr(user, "is_bot", False) else "web"


def client_ip(request):
    """IP покупателя с учётом доверенных прокси (TRUSTED_PROXY_COUNT): Caddy/Next.js пишут его в X-Forwarded-For."""
    return BaseThrottle().get_ident(request)


def is_internal_ip(ip):
    """Внутренняя сеть Docker/localhost: так приходят запросы сервера сайта (рендеринг страниц) и автотесты."""
    import ipaddress

    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


class IPThrottle(SimpleRateThrottle):
    """Лимит по IP покупателя для «дорогих» действий (заказ, поиск адреса, вход).
    При локальном запуске (PRODUCTION=false) запросы из сети Docker/localhost не ограничиваем —
    иначе все тестовые заказы с одного компьютера упирались бы в общий лимит."""

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        if getattr(settings, "THROTTLE_INTERNAL_EXEMPT", False) and is_internal_ip(ident):
            return None
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _GlobalThrottle(SimpleRateThrottle):
    """Общий лимит на любые запросы API: защищает от перегрузки скриптами и парсерами.
    Покупатель — по IP, сотрудник и бот — по учётной записи (у них отдельные, более высокие лимиты)."""

    staff_scope = ""

    def allow_request(self, request, view):
        user = getattr(request, "user", None)
        if getattr(user, "is_bot", False):
            return True  # сервисный токен бота: ограничивается на стороне мессенджера
        if getattr(user, "is_authenticated", False):
            self.scope = self.staff_scope
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and getattr(user, "pk", None):
            return self.cache_format % {"scope": self.scope, "ident": f"user{user.pk}"}
        ident = self.get_ident(request)
        if is_internal_ip(ident):
            return None  # сервер сайта и внутренние сервисы не ограничиваем
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BurstThrottle(_GlobalThrottle):
    scope = "burst"
    staff_scope = "staff_burst"


class SustainedThrottle(_GlobalThrottle):
    scope = "sustained"
    staff_scope = "staff_sustained"


class LoginThrottle(IPThrottle):
    scope = "login"


class CheckoutThrottle(IPThrottle):
    scope = "checkout"


class CheckoutHourThrottle(IPThrottle):
    scope = "checkout_hour"


class LookupThrottle(IPThrottle):
    scope = "lookup"


class PasswordThrottle(IPThrottle):
    scope = "password"


class SimulatorThrottle(IPThrottle):
    scope = "simulator"


class GeoThrottle(IPThrottle):
    scope = "geo"


class GeoDayThrottle(IPThrottle):
    scope = "geo_day"


# ------------------------------------------------------------------ защита входа сотрудников от подбора пароля

def _fail_key(username):
    return f"staff_login_fail:{str(username).strip().lower()[:64]}"


def login_locked(username):
    from django.core.cache import cache

    return cache.get(_fail_key(username), 0) >= settings.LOGIN_MAX_FAILS


def login_failed(username):
    """Считает неверные пароли по логину (с любых IP): после LOGIN_MAX_FAILS логин блокируется на LOGIN_LOCK_MINUTES."""
    from django.core.cache import cache

    key = _fail_key(username)
    ttl = settings.LOGIN_LOCK_MINUTES * 60
    if cache.add(key, 1, ttl):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, ttl)
        return 1


def login_succeeded(username):
    from django.core.cache import cache

    cache.delete(_fail_key(username))
