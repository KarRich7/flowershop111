"""Вход покупателя на сайт через Telegram или ВКонтакте (через наших ботов).

Схема без паролей и SMS:
1. Сайт вызывает start() → получает секретный token и ссылку на бота с одноразовым link_code
   (t.me/<бот>?start=login_<link_code> или vk.me/<сообщество>?ref=login_<link_code>) и запасной 6-значный код.
2. Покупатель открывает бота, бот показывает «Подтвердите вход» (защита от чужих ссылок) → confirm().
3. Сайт опрашивает poll(token) и один раз получает токен сессии покупателя (в базе — только его хеш).
   Сайт хранит оба токена в HttpOnly-cookie (apps/api/cookies.py) — JavaScript страницы их не видит.

Бот может писать покупателю только после того, как тот сам открыл диалог, — поэтому вход через бота
одновременно включает уведомления о заказах в этот мессенджер."""
import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.bots import telegram_net
from apps.core.errors import DomainError, NotFound
from apps.core.models import ShopSettings

from .models import Customer, CustomerChannel, CustomerLogin, CustomerSession

LOGIN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=180)
CODE_ATTEMPTS = 5
HEADER = "HTTP_X_CUSTOMER_TOKEN"
CHANNEL_LABELS = {"telegram": "Telegram", "vk": "ВКонтакте"}


# ------------------------------------------------------------------ каналы и ссылки

def telegram_username():
    if settings.TELEGRAM_BOT_USERNAME:
        return settings.TELEGRAM_BOT_USERNAME
    m = re.match(r"^https?://(?:www\.)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,64})/?$", ShopSettings.load().telegram_url or "")
    if m:
        return m.group(1)
    if not settings.TELEGRAM_BOT_TOKEN:
        return ""
    name = cache.get("tg_bot_username")
    if name is None:
        try:
            name = telegram_net.call("getMe", "GET", timeout=5)["result"]["username"]
        except Exception:  # noqa: BLE001 — сеть/токен: просто не показываем ссылку
            name = ""
        cache.set("tg_bot_username", name, 3600 if name else 120)
    return name


def vk_link_base():
    if settings.VK_GROUP_ID:
        return f"https://vk.me/club{str(settings.VK_GROUP_ID).lstrip('-')}"
    m = re.match(r"^https?://(?:m\.)?vk\.(?:com|ru|me)/([A-Za-z0-9_.]{2,64})/?$", ShopSettings.load().vk_url or "")
    return f"https://vk.me/{m.group(1)}" if m else ""


def channels_available():
    """Через какие мессенджеры можно войти на сайт. Владелец может убрать вход совсем
    (Настройки → Разделы сайта → «Кнопка «Войти»») — тогда оба канала недоступны."""
    test = settings.CUSTOMER_LOGIN_TEST_MODE
    enabled = ShopSettings.load().customer_login_enabled
    return {
        "telegram": bool(enabled and (test or (settings.TELEGRAM_BOT_TOKEN and telegram_username()))),
        "vk": bool(enabled and (test or (settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID))),
        "test_mode": test,
        "enabled": enabled,
    }


def deep_link(login):
    if login.channel == "telegram":
        name = telegram_username()
        return f"https://t.me/{name}?start=login_{login.link_code}" if name else ""
    base = vk_link_base()
    return f"{base}?ref=login_{login.link_code}&ref_source=site" if base else ""


def device_label(ua):
    ua = ua or ""
    browser = next((name for key, name in (("YaBrowser", "Яндекс Браузер"), ("Edg/", "Edge"), ("OPR/", "Opera"),
                                            ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
                    if key in ua), "")
    os_name = next((name for key, name in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                            ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if key in ua), "")
    return ", ".join(x for x in (browser, os_name) if x)


# ------------------------------------------------------------------ запрос входа (сайт)

def start(channel, *, order=None, user_agent=""):
    if channel not in CHANNEL_LABELS:
        raise DomainError("Выберите Telegram или ВКонтакте", code="channel_invalid")
    if not channels_available()[channel]:
        raise DomainError(f"Вход через {CHANNEL_LABELS[channel]} сейчас недоступен", code="channel_unavailable")
    now = timezone.now()
    CustomerLogin.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
    code = ""
    for _ in range(20):
        code = f"{secrets.randbelow(900000) + 100000}"
        if not CustomerLogin.objects.filter(code=code, status=CustomerLogin.Status.PENDING, expires_at__gt=now).exists():
            break
    return CustomerLogin.objects.create(
        channel=channel, token=secrets.token_urlsafe(32), link_code=secrets.token_urlsafe(18), code=code,
        order=order, user_agent=(user_agent or "")[:200], expires_at=now + LOGIN_TTL,
    )


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


@transaction.atomic
def poll(token):
    login = CustomerLogin.objects.select_for_update().filter(token=str(token or "")[:64]).first()
    if not login:
        raise NotFound("Запрос входа не найден")
    now = timezone.now()
    if login.status == CustomerLogin.Status.PENDING:
        if login.expires_at <= now:
            return {"status": "expired"}
        return {"status": "pending", "expires_in": int((login.expires_at - now).total_seconds()),
                "opened": bool(login.claimed_by)}
    if login.status == CustomerLogin.Status.CONFIRMED:
        if login.expires_at <= now:
            # подтверждённый, но не забранный вовремя вход больше не действует: украденный запрос входа
            # нельзя «дожать» позже, чем через 10 минут
            login.status = CustomerLogin.Status.CANCELLED
            login.save(update_fields=["status"])
            return {"status": "expired"}
        raw = create_session(login.customer, login.channel, login.user_agent)
        login.status = CustomerLogin.Status.USED
        login.save(update_fields=["status"])
        return {"status": "confirmed", "session_token": raw, "channel": login.channel,
                "order_token": login.order.public_token if login.order_id else None}
    return {"status": login.status}


# ------------------------------------------------------------------ подтверждение (бот)

def find_by_link(link_code, channel):
    return CustomerLogin.objects.filter(link_code=str(link_code)[:40], channel=channel, status=CustomerLogin.Status.PENDING,
                                        expires_at__gt=timezone.now()).first()


def find_by_code(code, channel, user_id):
    """Ручной ввод кода в боте. Не больше CODE_ATTEMPTS неверных попыток за 30 минут с одного аккаунта."""
    key = f"login_code_fail:{channel}:{user_id}"
    fails = cache.get(key, 0)
    if fails >= CODE_ATTEMPTS:
        raise DomainError("Слишком много неверных кодов. Подождите полчаса или войдите по кнопке на сайте.",
                          code="too_many_attempts")
    login = CustomerLogin.objects.filter(code=code, channel=channel, status=CustomerLogin.Status.PENDING,
                                         expires_at__gt=timezone.now()).first()
    if not login:
        cache.set(key, fails + 1, 30 * 60)
    return login


def claim(login, who):
    """Первый открывший ссылку пользователь бота «забирает» запрос — подтвердить его может только он."""
    if login.claimed_by and login.claimed_by != who:
        return False
    if not login.claimed_by:
        login.claimed_by = who
        login.save(update_fields=["claimed_by"])
    return True


@transaction.atomic
def confirm(login_id, who, customer):
    login = CustomerLogin.objects.select_for_update().filter(pk=login_id).first()
    if (not login or login.status != CustomerLogin.Status.PENDING or login.expires_at <= timezone.now()
            or login.claimed_by != who):
        return None
    login.status = CustomerLogin.Status.CONFIRMED
    login.customer = customer
    login.confirmed_at = timezone.now()
    login.save(update_fields=["status", "customer", "confirmed_at"])
    order = login.order
    if order and order.source != "store" and order.customer_id != customer.pk:
        # уведомления по этому заказу теперь идут в мессенджер покупателя
        order.customer = customer
        order.save(update_fields=["customer"])
        if not customer.phone and order.contact_phone:
            customer.phone = order.contact_phone
        if not customer.name and order.contact_name:
            customer.name = order.contact_name
        customer.save()
    return login


@transaction.atomic
def cancel(login_id, who):
    login = CustomerLogin.objects.select_for_update().filter(pk=login_id, claimed_by=who,
                                                             status=CustomerLogin.Status.PENDING).first()
    if login:
        login.status = CustomerLogin.Status.CANCELLED
        login.save(update_fields=["status"])
    return login


# ------------------------------------------------------------------ сессия покупателя (сайт)

def session_key(request):
    """Токен сессии покупателя: из HttpOnly-cookie cu_customer (так входит сайт) или из заголовка
    X-Customer-Token (старые вкладки и внешние клиенты)."""
    from apps.api.cookies import CUSTOMER_COOKIE, read_cookie

    raw = (request.META.get(HEADER) or "").strip()
    if raw:
        return raw if len(raw) <= 128 else ""
    return read_cookie(request, CUSTOMER_COOKIE)


def session_for_key(raw):
    if not raw:
        return None
    return CustomerSession.objects.select_related("customer").filter(key_hash=_hash(raw), expires_at__gt=timezone.now()).first()


def create_session(customer, channel, user_agent=""):
    raw = secrets.token_urlsafe(32)
    CustomerSession.objects.create(customer=customer, key_hash=_hash(raw), channel=channel,
                                   user_agent=(user_agent or "")[:200], expires_at=timezone.now() + SESSION_TTL)
    return raw


def customer_from_request(request):
    s = session_for_key(session_key(request))
    if not s:
        return None
    now = timezone.now()
    if now - s.last_seen_at > timedelta(hours=1):
        CustomerSession.objects.filter(pk=s.pk).update(last_seen_at=now, expires_at=now + SESSION_TTL)
    return s.customer


def logout(request):
    raw = session_key(request)
    if raw:
        CustomerSession.objects.filter(key_hash=_hash(raw)).delete()


def channels_of(customer):
    return [
        {"channel": c.channel, "label": CHANNEL_LABELS.get(c.channel, c.channel), "username": c.username,
         "display_name": c.display_name, "test": c.is_simulated}
        for c in CustomerChannel.objects.filter(customer=customer, channel__in=list(CHANNEL_LABELS)).order_by("created_at")
    ]


def profile(customer: Customer):
    from apps.orders.models import Order

    last = (Order.objects.filter(customer=customer, fulfillment="delivery").exclude(source="store")
            .select_related("delivery").order_by("-created_at").first())
    delivery = getattr(last, "delivery", None) if last else None
    return {
        "id": customer.pk, "name": customer.name, "phone": customer.phone, "email": customer.email,
        "channels": channels_of(customer),
        "last_delivery": {
            "address": delivery.address, "apartment": delivery.apartment, "entrance": delivery.entrance,
            "floor": delivery.floor, "recipient_name": last.recipient_name,
        } if delivery and delivery.address else None,
    }
