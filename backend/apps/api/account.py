"""Личный кабинет покупателя: вход через Telegram/ВКонтакте, профиль, история заказов.
Сессия хранится в HttpOnly-cookie cu_customer (JavaScript страницы её не видит, см. apps/api/cookies.py);
заголовок X-Customer-Token тоже принимается — для старых вкладок и внешних клиентов."""
import hashlib

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from apps.bots.engine import BotEngine, Incoming
from apps.core import validation as v
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.core.utils import normalize_phone
from apps.customers import login as cl
from apps.customers.models import CustomerLogin
from apps.orders.models import Order

from .auth import IPThrottle
from .cookies import (CUSTOMER_COOKIE, CUSTOMER_PATH, LOGIN_COOKIE, LOGIN_PATH, clear_cookie, from_our_site,
                      read_cookie, set_secret_cookie)


class CustomerLoginThrottle(IPThrottle):
    scope = "customer_login"


class CustomerPollThrottle(IPThrottle):
    scope = "customer_poll"


def _require(request):
    c = cl.customer_from_request(request)
    if not c:
        raise DomainError("Войдите через Telegram или ВКонтакте", code="not_authenticated", http_status=401)
    return c


@extend_schema(tags=["Покупатель"], summary="Начать вход через бота {channel: telegram|vk, order_token?}")
@api_view(["POST"])
@throttle_classes([CustomerLoginThrottle])
def login_start(request):
    order = None
    token = request.data.get("order_token")
    if token:
        order = Order.objects.filter(public_token=str(token)[:64]).exclude(source="store").first()
        if not order:
            raise NotFound("Заказ не найден")
    login = cl.start(str(request.data.get("channel") or ""), order=order,
                     user_agent=request.META.get("HTTP_USER_AGENT", ""))
    # секретный токен запроса входа — только в HttpOnly-cookie, в ответ (и в JavaScript страницы) он не попадает
    resp = Response({
        "code": login.code, "channel": login.channel, "link": cl.deep_link(login),
        "expires_in": int(cl.LOGIN_TTL.total_seconds()), "test_mode": settings.CUSTOMER_LOGIN_TEST_MODE,
    }, status=201)
    return set_secret_cookie(resp, LOGIN_COOKIE, login.token, cl.LOGIN_TTL.total_seconds(), LOGIN_PATH)


def _login_token(request):
    data = request.data if isinstance(request.data, dict) else {}
    return str(data.get("token") or "").strip() or read_cookie(request, LOGIN_COOKIE)


def _set_customer_cookie(resp, raw):
    return set_secret_cookie(resp, CUSTOMER_COOKIE, raw, cl.SESSION_TTL.total_seconds(), CUSTOMER_PATH)


@extend_schema(tags=["Покупатель"], summary="Статус входа (POST): pending | confirmed (сессия — в cookie) | expired")
@api_view(["POST"])
@throttle_classes([CustomerPollThrottle])
def login_status(request):
    result = cl.poll(_login_token(request))
    raw = result.pop("session_token", None)
    resp = Response(result)
    if raw:
        _set_customer_cookie(resp, raw)
        clear_cookie(resp, LOGIN_COOKIE, LOGIN_PATH)
    return resp


@extend_schema(tags=["Покупатель"], summary="Тестовый режим: подтвердить вход без настоящего бота {token}")
@api_view(["POST"])
@throttle_classes([CustomerLoginThrottle])
def login_test_confirm(request):
    """Только при CUSTOMER_LOGIN_TEST_MODE=true. Проходит тот же путь, что и настоящий бот: «открыть ссылку» →
    кнопка «Войти на сайт» от имени тестового пользователя мессенджера."""
    if not settings.CUSTOMER_LOGIN_TEST_MODE:
        raise NotFound("Тестовый режим входа отключён")
    login = CustomerLogin.objects.filter(token=_login_token(request)[:64]).first() if _login_token(request) else None
    if not login:
        raise NotFound("Запрос входа не найден")
    name = v.person_name(request.data.get("name") or "", "name", "Имя", required=False) or "Тестовый покупатель"
    uid = "sim-web-" + hashlib.sha1(f"{login.channel}:{name}".encode()).hexdigest()[:10]
    engine = BotEngine(login.channel)
    first = Incoming(channel=login.channel, user_id=uid, chat_id=uid, display_name=name, simulated=True,
                     username="test_buyer" if login.channel == "telegram" else "")
    if login.channel == "vk":
        first.ref, first.text = f"login_{login.link_code}", "Начать"
    else:
        first.text = f"/start login_{login.link_code}"
    engine.handle(first)
    engine.handle(Incoming(channel=login.channel, user_id=uid, chat_id=uid, payload=f"login_ok:{login.pk}",
                           display_name=name, simulated=True))
    return Response({"ok": True})


def _orders(customer):
    rows = (Order.objects.filter(customer=customer).exclude(source="store").order_by("-created_at")
            .prefetch_related("items")[:30])
    return [{
        "number": o.number, "token": o.public_token, "created_at": o.created_at, "status": o.status,
        "status_label": o.get_status_display(), "total": o.total, "source": o.source,
        "source_label": o.get_source_display(), "fulfillment": o.fulfillment,
        "fulfillment_label": o.get_fulfillment_display(), "date": o.fulfillment_date,
        "items": ", ".join(f"{i.name}{' × ' + str(i.quantity) if i.quantity > 1 else ''}" for i in o.items.all())[:200],
    } for o in rows]


@extend_schema(tags=["Покупатель"], summary="Профиль покупателя (GET) / изменить имя, телефон, e-mail (PATCH)")
@api_view(["GET", "PATCH"])
def me(request):
    c = _require(request)
    if request.method == "PATCH":
        d = request.data
        fields = []
        if "name" in d:
            c.name = v.person_name(d.get("name"), "name", "Имя", required=False)[:160]
            fields.append("name")
        if "email" in d:
            c.email = v.email(d.get("email"), "email", "E-mail")
            fields.append("email")
        if "phone" in d:
            raw = (d.get("phone") or "").strip()
            phone = normalize_phone(raw) if raw else ""
            if raw and not phone:
                raise ValidationError("Укажите телефон в формате +7XXXXXXXXXX", code="invalid_phone",
                                      details={"field": "phone"})
            c.phone = phone
            fields.append("phone")
        if fields:
            c.save(update_fields=fields + ["updated_at"])
    resp = Response({**cl.profile(c), "orders": _orders(c)})
    if not request.META.get(cl.HEADER):
        _set_customer_cookie(resp, cl.session_key(request))  # продлеваем cookie вместе с сессией (180 дней)
    return resp


@extend_schema(tags=["Покупатель"], summary="Перенести вход из старой версии сайта (заголовок X-Customer-Token) в cookie")
@api_view(["POST"])
@throttle_classes([CustomerLoginThrottle])
def session_adopt(request):
    raw = (request.META.get(cl.HEADER) or "").strip()
    if not cl.session_for_key(raw if len(raw) <= 128 else ""):
        raise DomainError("Войдите через Telegram или ВКонтакте", code="not_authenticated", http_status=401)
    return _set_customer_cookie(Response({"ok": True}), raw)


@extend_schema(tags=["Покупатель"], summary="Выйти на этом устройстве")
@api_view(["POST"])
def logout(request):
    cl.logout(request)
    resp = Response({"ok": True})
    # cookie стираем только по запросу нашего сайта: чужая страница не может «разлогинить» покупателя
    return clear_cookie(resp, CUSTOMER_COOKIE, CUSTOMER_PATH) if from_our_site(request) else resp


@extend_schema(tags=["Покупатель"], summary="Выйти на всех устройствах")
@api_view(["POST"])
def logout_all(request):
    c = _require(request)
    c.sessions.all().delete()
    return clear_cookie(Response({"ok": True}), CUSTOMER_COOKIE, CUSTOMER_PATH)

