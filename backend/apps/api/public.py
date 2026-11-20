"""Публичный API: сайт и боты (боты авторизуются сервисным токеном, канал задаётся сервером)."""
from datetime import date as date_cls

from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.bots.engine import BotEngine, Incoming
from apps.carts import services as carts
from apps.catalog import builder
from apps.catalog.models import Product, ProductImage
from apps.core.errors import DomainError, NotFound, ValidationError
from apps.core.models import MAX_CUSTOM_STEMS_LIMIT, ShopSettings
from apps.core.utils import normalize_phone
from apps.customers import login as customer_login
from apps.customers.models import CustomerChannel
from apps.delivery import geo
from apps.delivery.models import DeliveryZone
from apps.delivery.services import slots_for_date
from apps.inventory.services import availability_map
from apps.notifications.models import Notification
from apps.orders.models import Order
from apps.orders.services import expire_overdue_orders, place_order
from apps.payments import services as payments
from apps.payments.providers.base import InvalidWebhook

from . import serializers as ser
from .auth import (
    BurstThrottle, CheckoutHourThrottle, CheckoutThrottle, GeoDayThrottle, GeoThrottle, LookupThrottle,
    SimulatorThrottle, request_channel,
)
from .errors import error_response


def maybe_expire():
    """Ленивая страховка, если Celery beat не запущен: не чаще раза в 20 секунд."""
    if cache.add("expire-overdue-lock", 1, 20):
        expire_overdue_orders()


def _products_qs():
    return (Product.objects.filter(is_active=True).select_related("inventory_item")
            .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("sort_order", "id")),
                              "inventory_item__recipe__components"))


def _shop_qs():
    """Товары витрины: без цветов поштучно, если владелец выключил этот раздел."""
    qs = _products_qs()
    if not carts.sections()["flowers"]:
        qs = qs.exclude(type__in=carts.STEM_TYPES)
    return qs


@extend_schema(summary="Проверка работоспособности (БД и Redis)")
@api_view(["GET"])
@authentication_classes([])
def health(request):
    from django.db import connection

    checks = {}
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception:  # noqa: BLE001
        checks["db"] = "error"
    try:
        cache.set("health", "1", 5)
        checks["cache"] = "ok" if cache.get("health") == "1" else "error"
    except Exception:  # noqa: BLE001
        checks["cache"] = "error"
    ok = all(v == "ok" for v in checks.values())
    return Response({"status": "ok" if ok else "degraded", **checks}, status=200 if ok else 503)


@extend_schema(tags=["Магазин"], summary="Публичные настройки магазина")
@api_view(["GET"])
def shop_settings(request):
    return Response(ser.shop_public(ShopSettings.load()))


@extend_schema(tags=["Каталог"], summary="Категории готовых букетов")
@api_view(["GET"])
def categories(request):
    """Категории в порядке, заданном в админке; пустые скрыты, «Другое» — в конце."""
    from apps.catalog.categories import TYPES_BY_KIND
    from apps.catalog.models import Category

    kind = request.query_params.get("type") or "bouquet"
    if kind not in Category.Kind.values:
        kind = "bouquet"
    avail = availability_map()
    rows = {}
    for p in _shop_qs().filter(type__in=TYPES_BY_KIND[kind]):
        c = rows.setdefault(p.category or "", {"name": p.category or "Другое", "count": 0, "in_stock": 0})
        c["count"] += 1
        c["in_stock"] += 1 if carts.product_available(p, avail) > 0 else 0
    out = [rows.pop(name) for name in Category.objects.filter(kind=kind).values_list("name", flat=True) if name in rows]
    other = {"name": "Другое", "count": 0, "in_stock": 0}
    for r in rows.values():  # без категории или с удалённой категорией
        other["count"] += r["count"]
        other["in_stock"] += r["in_stock"]
    if other["count"]:
        out.append(other)
    return Response(out)


@extend_schema(tags=["Магазин"], summary="Страница «О нас»: текст и фото карусели")
@api_view(["GET"])
def about(request):
    from .admin_extra import about_data

    return Response(about_data())


@extend_schema(tags=["Магазин"], summary="Частые вопросы: блоки с вопросами и ответами")
@api_view(["GET"])
def faq(request):
    from .admin_extra import faq_data

    return Response({"blocks": faq_data()["blocks"]})


@extend_schema(tags=["Каталог"], summary="Товары: ?type=bouquet|flower|greenery|card|addon&category=&featured=1&in_stock=1")
@api_view(["GET"])
def products(request):
    maybe_expire()
    qs = _shop_qs()
    t = request.query_params.get("type")
    if t:
        qs = qs.filter(type__in=t.split(","))
    if request.query_params.get("category"):
        cat = request.query_params["category"]
        if cat == "Другое":
            from apps.catalog.models import Category

            known = Category.objects.values_list("name", flat=True)
            qs = qs.exclude(category__in=[c for c in known if c != "Другое"])
        else:
            qs = qs.filter(category=cat)
    if request.query_params.get("featured"):
        qs = qs.filter(is_featured=True)
    if request.query_params.get("q"):
        qs = qs.filter(name__icontains=request.query_params["q"])
    avail = availability_map()
    data = [ser.product(p, avail) for p in qs]
    if request.query_params.get("in_stock"):
        data = [d for d in data if d["in_stock"]]
    sort = request.query_params.get("sort")
    if sort == "price":
        data.sort(key=lambda d: d["price"])
    elif sort == "-price":
        data.sort(key=lambda d: -d["price"])
    return Response(data)


@extend_schema(tags=["Каталог"], summary="Карточка товара")
@api_view(["GET"])
def product_detail(request, slug):
    p = _shop_qs().filter(slug=slug).first()
    if not p:
        raise NotFound("Товар не найден")
    return Response(ser.product(p, availability_map(), detail=True))


@extend_schema(tags=["Конструктор"], summary="Варианты для конструктора букета (только сайт)")
@api_view(["GET"])
def constructor_options(request):
    carts.assert_custom_allowed(request_channel(request))
    avail = availability_map()
    qs = _products_qs().filter(constructor_enabled=True)
    groups = {"flower": [], "greenery": [], "packaging": [], "ribbon": [], "card": []}
    for p in qs:
        if p.type in groups:
            groups[p.type].append(ser.product(p, avail))
    s = ShopSettings.load()
    return Response({"flowers": groups["flower"], "greenery": groups["greenery"], "packaging": groups["packaging"],
                     "ribbons": groups["ribbon"], "cards": groups["card"], "florist_fee": s.florist_fee,
                     "min_stems": min(s.min_custom_stems, MAX_CUSTOM_STEMS_LIMIT),
                     "max_stems": min(s.max_custom_stems, MAX_CUSTOM_STEMS_LIMIT)})


@extend_schema(tags=["Конструктор"], summary="Расчёт стоимости индивидуального букета на сервере")
@api_view(["POST"])
def constructor_quote(request):
    carts.assert_custom_allowed(request_channel(request))
    q = builder.quote(request.data.get("composition") or request.data, quantity=int(request.data.get("quantity", 1)))
    return Response(q)


# ------------------------------------------------------------------ корзина

def _cart(request, token):
    return carts.get_cart(token, channel=request_channel(request))


@extend_schema(tags=["Корзина"], summary="Создать корзину (канал определяется сервером)")
@api_view(["POST"])
def cart_create(request):
    cart = carts.create_cart(request_channel(request))
    return Response(carts.summary(cart), status=201)


@extend_schema(tags=["Корзина"], summary="Корзина с актуальными ценами")
@api_view(["GET"])
def cart_detail(request, token):
    return Response(carts.summary(_cart(request, token)))


@extend_schema(tags=["Корзина"], summary="Добавить товар {product_id, quantity}")
@api_view(["POST"])
def cart_add(request, token):
    cart = _cart(request, token)
    carts.add_product(cart, int(request.data["product_id"]), int(request.data.get("quantity", 1)))
    return Response(carts.summary(cart))


@extend_schema(tags=["Корзина"], summary="Изменить количество {quantity} или удалить позицию")
@api_view(["PATCH", "DELETE"])
def cart_item(request, token, item_id):
    cart = _cart(request, token)
    if request.method == "DELETE":
        carts.remove_item(cart, item_id)
    else:
        carts.set_quantity(cart, item_id, int(request.data["quantity"]))
    return Response(carts.summary(cart))


@extend_schema(tags=["Корзина"], summary="Добавить индивидуальный букет (только сайт)")
@api_view(["POST"])
def cart_custom(request, token):
    cart = _cart(request, token)
    carts.add_custom_bouquet(cart, request.data.get("composition") or {}, int(request.data.get("quantity", 1)))
    return Response(carts.summary(cart))


# ------------------------------------------------------------------ доставка и заказ

@extend_schema(tags=["Доставка"], summary="Зоны доставки с границами на карте")
@api_view(["GET"])
def delivery_zones(request):
    return Response([ser.zone(z) for z in DeliveryZone.objects.filter(is_active=True)])


def _geo_call(fn, *args):
    try:
        return fn(*args)
    except geo.GeocoderUnavailable as e:
        raise DomainError(str(e), code="geocoder_unavailable", http_status=503)


@extend_schema(tags=["Доставка"], summary="Найти адрес: ?q=улица, дом → адреса с координатами, зоной и подписью")
@api_view(["GET"])
@throttle_classes([BurstThrottle, GeoThrottle, GeoDayThrottle])
def delivery_geocode(request):
    q = request.query_params.get("q", "")
    rows = _geo_call(geo.geocode, q, 5)
    return Response({"results": [geo.describe(r) for r in rows]})


@extend_schema(tags=["Доставка"], summary="Адрес по точке на карте: ?lat=&lon=")
@api_view(["GET"])
@throttle_classes([BurstThrottle, GeoThrottle, GeoDayThrottle])
def delivery_reverse(request):
    try:
        lat, lon = float(request.query_params["lat"]), float(request.query_params["lon"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("Укажите координаты lat и lon")
    zone = geo.find_zone(lat, lon)
    try:
        res = geo.reverse(lat, lon)
    except geo.GeocoderUnavailable:
        return Response({"result": None, "zone": geo.zone_info(zone), "geocoder": False})
    return Response({"result": geo.describe(res) if res else None, "zone": geo.zone_info(zone), "geocoder": True})


@extend_schema(tags=["Доставка"], summary="Интервалы на дату: ?date=YYYY-MM-DD&fulfillment=delivery|pickup")
@api_view(["GET"])
def delivery_slots(request):
    try:
        d = date_cls.fromisoformat(request.query_params.get("date", ""))
    except ValueError:
        raise ValidationError("Укажите дату в формате YYYY-MM-DD")
    fulfillment = request.query_params.get("fulfillment", "delivery")
    return Response(slots_for_date(d, "pickup" if fulfillment == "pickup" else "delivery"))


@extend_schema(tags=["Заказы"], summary="Оформить заказ из корзины")
@api_view(["POST"])
@throttle_classes([BurstThrottle, CheckoutThrottle, CheckoutHourThrottle])
def checkout(request):
    if str(request.data.get("website") or "").strip():
        # «Ловушка для ботов»: скрытое поле, которое человек не видит и не заполняет
        raise ValidationError("Не удалось оформить заказ. Обновите страницу и попробуйте ещё раз.", code="spam_detected")
    cart = _cart(request, request.data.get("cart_token"))
    data = dict(request.data)
    data["idempotency_key"] = request.headers.get("Idempotency-Key") or request.data.get("idempotency_key")
    signed_in = customer_login.customer_from_request(request) if cart.channel == "web" else None
    order = place_order(cart, data, actor_label="сайт" if cart.channel == "web" else f"{cart.channel}-бот",
                        customer=signed_in)
    return Response(ser.order_public(order), status=201)


@extend_schema(tags=["Заказы"], summary="Статус заказа по секретной ссылке")
@api_view(["GET"])
def order_track(request, token):
    maybe_expire()
    o = Order.objects.filter(public_token=token).exclude(source="store").first()
    if not o:
        raise NotFound("Заказ не найден")
    if payments.sync_pending(o):  # покупатель вернулся с формы оплаты раньше уведомления
        o.refresh_from_db()
    return Response(ser.order_public(o))


@extend_schema(tags=["Заказы"], summary="Найти заказ по номеру и телефону {number, phone}")
@api_view(["POST"])
@throttle_classes([BurstThrottle, LookupThrottle])
def order_lookup(request):
    phone = normalize_phone(request.data.get("phone"))
    o = Order.objects.filter(number=str(request.data.get("number", "")).strip().lstrip("№"), contact_phone=phone).exclude(source="store").first() if phone else None
    if not o:
        raise NotFound("Заказ с таким номером и телефоном не найден")
    return Response({"token": o.public_token})


@extend_schema(tags=["Заказы"], summary="Получить ссылку на оплату (новая попытка)")
@api_view(["POST"])
def order_pay(request, token):
    o = Order.objects.filter(public_token=token).first()
    if not o:
        raise NotFound("Заказ не найден")
    url = payments.ensure_payment_link(o)
    if not url:
        raise DomainError("Заказ не ожидает оплаты", code="invalid_state", http_status=409)
    return Response({"payment_url": url})


# ------------------------------------------------------------------ платежи

@extend_schema(tags=["Платежи"], summary="Данные платежа для страницы оплаты")
@api_view(["GET"])
def payment_info(request, token):
    p = payments.get_by_token(token)
    o = p.order
    return Response({
        "amount": p.amount, "status": p.status, "status_label": p.get_status_display(), "is_test": p.is_test,
        "provider": p.provider, "order_number": o.number, "order_token": o.public_token,
        "order_status": o.status, "order_status_label": o.get_status_display(),
        "expires_at": o.reservation_expires_at, "shop_name": ShopSettings.load().shop_name,
    })


@extend_schema(tags=["Платежи"], summary="Симулятор: succeed | fail | cancel | refund_succeed | refund_fail")
@api_view(["POST"])
def payment_simulate(request, token):
    result = payments.simulator_action(token, request.data.get("action"))
    return Response(result)


@extend_schema(tags=["Платежи"], summary="Webhook платёжного провайдера (подпись обязательна, идемпотентно)")
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def payment_webhook(request, provider):
    try:
        result = payments.process_webhook(provider, request.body, dict(request.headers))
    except InvalidWebhook as e:
        return error_response("invalid_webhook", str(e), 400)
    except RuntimeError as e:
        return error_response("provider_not_configured", str(e), 400)
    return Response(result)


# ------------------------------------------------------------------ демонстрационный симулятор ботов

def _sim_guard(channel):
    if not settings.BOT_SIMULATOR_ENABLED:
        raise NotFound("Симулятор отключён")
    if channel not in ("telegram", "vk"):
        raise NotFound("Неизвестный канал")


def _out_json(out):
    d = out.to_dict()
    d["photo"] = f"{settings.MEDIA_URL}{out.photo}" if out.photo else None
    return d


@extend_schema(tags=["Симулятор ботов"], summary="Отправить сообщение/нажатие кнопки боту {user_id, text|payload|contact_phone|location}")
@api_view(["POST"])
@throttle_classes([SimulatorThrottle])
def simulator_message(request, channel):
    _sim_guard(channel)
    user_id = str(request.data.get("user_id") or "")
    if not user_id.startswith("sim-") or len(user_id) > 40:
        raise ValidationError("user_id симулятора должен начинаться с «sim-»")
    loc = request.data.get("location") or None
    try:
        location = (float(loc["lat"]), float(loc["lon"])) if loc else None
    except (KeyError, TypeError, ValueError):
        raise ValidationError("location: ожидается {lat, lon}")
    inc = Incoming(channel=channel, user_id=user_id, chat_id=user_id, text=request.data.get("text"),
                   payload=request.data.get("payload"), contact_phone=request.data.get("contact_phone"), location=location,
                   display_name=(request.data.get("display_name") or "")[:60], simulated=True)
    outs = BotEngine(channel).handle(inc)
    return Response({"messages": [_out_json(o) for o in outs]})


@extend_schema(tags=["Симулятор ботов"], summary="Уведомления, отправленные пользователю симулятора")
@api_view(["GET"])
def simulator_inbox(request, channel):
    _sim_guard(channel)
    user_id = request.query_params.get("user_id", "")
    after = int(request.query_params.get("after", 0) or 0)
    if not CustomerChannel.objects.filter(channel=channel, external_id=user_id, is_simulated=True).exists():
        return Response([])
    rows = Notification.objects.filter(channel=channel, recipient=user_id, id__gt=after).order_by("id")[:50]
    return Response([{"id": n.id, "text": n.text, "buttons": (n.payload or {}).get("buttons", []), "at": n.created_at,
                      "kind": n.kind} for n in rows])
