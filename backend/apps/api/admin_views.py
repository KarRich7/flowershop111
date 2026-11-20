"""API админ-панели. Права проверяются на сервере для каждой операции."""
import io
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from PIL import Image, ImageOps
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog import categories
from apps.catalog.models import Product, ProductImage
from apps.core import site_content
from apps.core import validation as v
from apps.core.audit import audit
from apps.api.auth import set_staff_cookie
from apps.api.cookies import STAFF_COOKIE, STAFF_PATH, clear_cookie, from_our_site
from apps.core.errors import DomainError, NotFound, PermissionDenied, ValidationError
from apps.core.models import MAX_CUSTOM_STEMS_LIMIT, AuditLog, ShopSettings, StaffToken, User
from apps.core.utils import local_today, normalize_phone
from apps.customers.models import Customer
from apps.delivery import geo
from apps.delivery.models import Delivery, DeliverySlot, DeliveryZone
from apps.inventory import services as inv
from apps.inventory.models import InventoryItem, StockBalance, StockMovement
from apps.notifications import services as notifications
from apps.notifications.models import Notification
from apps.orders import services as orders
from apps.orders.models import Order
from apps.orders.state import ACTIVE_STATUSES
from apps.payments import services as payments
from apps.recipes import services as recipes
from apps.recipes.models import BouquetRecipe

from . import serializers as ser
from .auth import LoginThrottle, PasswordThrottle
from .permissions import AnyStaff, FloristOrOwner, OwnerOnly

TAG = ["Админ-панель"]


def doc(summary):
    return extend_schema(tags=TAG, summary=summary)


def _int(v, name="id"):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValidationError(f"Некорректное значение: {name}")


# ------------------------------------------------------------------ вход

@doc("Вход сотрудника {username, password}")
@api_view(["POST"])
@throttle_classes([LoginThrottle])
def login(request):
    from django.conf import settings

    from .auth import login_failed, login_locked, login_succeeded

    username = str(request.data.get("username", "") or "")[:150]
    password = str(request.data.get("password", "") or "")[:256]
    if login_locked(username):
        audit(None, "login_locked", request=request, actor_label=username[:64])
        raise DomainError(f"Слишком много неверных попыток. Вход для «{username}» заблокирован на "
                          f"{settings.LOGIN_LOCK_MINUTES} мин.", code="login_locked", http_status=429)
    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        fails = login_failed(username)
        audit(None, "login_failed", request=request, actor_label=username[:64], attempt=fails)
        left = settings.LOGIN_MAX_FAILS - fails
        msg = "Неверный логин или пароль"
        if 0 < left <= 2:
            msg += f". Осталось попыток: {left}"
        raise ValidationError(msg, code="invalid_credentials")
    login_succeeded(username)
    token = StaffToken.issue(user, request)  # вход на этом устройстве; другие устройства остаются в системе
    audit(user, "login", user, request=request)
    from apps.core.security import has_demo_password

    # токен — только в HttpOnly-cookie, в ответе его нет (JavaScript страницы не может его прочитать)
    return set_staff_cookie(Response({"user": {**ser.user(user), "weak_password": has_demo_password(user)}}), token)


@doc("Сменить свой пароль {old_password, new_password} — все остальные сеансы завершаются")
@api_view(["POST"])
@permission_classes([AnyStaff])
@throttle_classes([PasswordThrottle])
def change_password(request):
    u = request.user
    old = str(request.data.get("old_password") or "")
    if not u.check_password(old):
        audit(u, "password_change_failed", u, request=request)
        v.fail("old_password", "Текущий пароль указан неверно")
    new = _password(str(request.data.get("new_password") or ""), u, field="new_password")
    if new == old:
        v.fail("new_password", "Новый пароль должен отличаться от текущего")
    u.set_password(new)
    u.save(update_fields=["password"])
    StaffToken.objects.filter(user=u).delete()  # все остальные устройства выходят из админки
    token = StaffToken.issue(u, request)
    audit(u, "password_change", u, request=request)
    return set_staff_cookie(Response({"user": ser.user(u)}), token)


@doc("Проверка безопасности установки (только владелец)")
@api_view(["GET"])
@permission_classes([OwnerOnly])
def security_check(request):
    from apps.core.security import run_checks

    return Response(run_checks())


@doc("Выход (cookie удаляется, даже если вход уже истёк)")
@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    if isinstance(request.auth, StaffToken):
        request.auth.delete()  # выход только на этом устройстве
    resp = Response({"ok": True})
    return clear_cookie(resp, STAFF_COOKIE, STAFF_PATH) if from_our_site(request) else resp


@doc("Перенести вход из старой версии сайта (токен в заголовке Authorization) в HttpOnly-cookie")
@api_view(["POST"])
@permission_classes([AnyStaff])
def adopt_session(request):
    if not isinstance(request.auth, StaffToken):
        raise ValidationError("Нет входа для переноса")
    return set_staff_cookie(Response({"ok": True}), request.auth)


@doc("Текущий сотрудник")
@api_view(["GET"])
@permission_classes([AnyStaff])
def me(request):
    from apps.core.security import has_demo_password

    return Response({**ser.user(request.user), "weak_password": has_demo_password(request.user)})


# ------------------------------------------------------------------ панель

@doc("Показатели для главной панели")
@api_view(["GET"])
@permission_classes([AnyStaff])
def dashboard(request):
    u = request.user
    today = local_today()
    if u.role == "courier":
        qs = Delivery.objects.filter(courier=u, date=today).exclude(order__status="cancelled")
        return Response({"role": "courier", "deliveries_today": qs.count(),
                         "in_transit": qs.filter(status="in_transit").count(),
                         "delivered": qs.filter(status="delivered").count()})
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    today_orders = Order.objects.filter(created_at__gte=start)
    shop = ShopSettings.load()
    low = []
    for b in StockBalance.objects.select_related("item").filter(item__is_active=True):
        if b.available <= b.item.min_stock:
            low.append({"id": b.item_id, "name": b.item.name, "available": b.available, "min_stock": b.item.min_stock})
    data = {
        "role": u.role,
        "orders_today": today_orders.exclude(status="cancelled").count(),
        "awaiting_confirmation": Order.objects.filter(status="awaiting_confirmation").count(),
        "new_to_confirm": Order.objects.filter(status="new").count(),
        "awaiting_payment": Order.objects.filter(status="awaiting_payment").count(),
        "in_work": Order.objects.filter(status__in=["confirmed", "assembling", "ready"]).count(),
        "deliveries_today": Delivery.objects.filter(date=today).exclude(order__status="cancelled").count(),
        "unassigned_deliveries": Delivery.objects.filter(date__gte=today, courier__isnull=True)
        .exclude(order__status__in=["cancelled", "delivered", "completed"]).count(),
        "low_stock": sorted(low, key=lambda r: r["available"])[:12],
        "recent_orders": [
            {"id": o.id, "number": o.number, "status": o.status, "status_label": o.get_status_display(),
             "source_label": o.get_source_display(), "total": o.total, "created_at": o.created_at, "name": o.contact_name}
            for o in Order.objects.order_by("-created_at")[:8]
        ],
        "feed": [
            {"id": n.id, "kind": n.kind, "text": n.text, "at": n.created_at, "handled": n.is_handled,
             "can_reply": bool((n.payload or {}).get("reply_to"))}
            for n in Notification.objects.filter(channel="staff", kind="support_request").order_by("-created_at")[:12]
        ],
        "open_support": Notification.objects.filter(kind="support_request", is_handled=False).count(),
        "orders_enabled": shop.orders_enabled,
        "orders_closed_message": site_content.orders_closed_message(shop),
    }
    if u.role == "owner":
        paid = Order.objects.filter(created_at__gte=start, payment_status="paid")
        week_start = start - timedelta(days=6)
        by_source = (Order.objects.filter(created_at__gte=week_start, payment_status="paid")
                     .values("source").annotate(n=Count("id"), s=Sum("total")))
        data.update({
            "revenue_today": paid.aggregate(s=Sum("total"))["s"] or 0,
            "revenue_week": Order.objects.filter(created_at__gte=week_start, payment_status="paid").aggregate(s=Sum("total"))["s"] or 0,
            "by_source": [{"source": dict(Order.Source.choices)[r["source"]], "orders": r["n"], "revenue": r["s"]} for r in by_source],
        })
    return Response(data)


# ------------------------------------------------------------------ заказы

def _orders_for(user):
    qs = Order.objects.select_related("customer", "delivery__courier", "delivery__zone")
    if user.role == "courier":
        qs = qs.filter(delivery__courier=user)  # курьер видит только назначенные ему заказы
    return qs


def _get_order(user, order_id):
    o = _orders_for(user).filter(pk=_int(order_id)).first()
    if not o:
        raise NotFound("Заказ не найден")
    return o


@doc("Список заказов: ?status=&source=&date=&q=&scope=active")
@api_view(["GET"])
@permission_classes([AnyStaff])
def order_list(request):
    qs = _orders_for(request.user)
    p = request.query_params
    if p.get("status"):
        qs = qs.filter(status__in=p["status"].split(","))
    if p.get("scope") == "active":
        qs = qs.filter(status__in=list(ACTIVE_STATUSES))
    if p.get("source"):
        qs = qs.filter(source=p["source"])
    if p.get("date"):
        qs = qs.filter(fulfillment_date=p["date"])
    if p.get("q"):
        q = p["q"].strip()
        qs = qs.filter(Q(number__icontains=q) | Q(contact_name__icontains=q) | Q(contact_phone__icontains=q))
    rows = []
    for o in qs.order_by("-created_at")[:200]:
        d = getattr(o, "delivery", None)
        rows.append({
            "id": o.id, "number": o.number, "created_at": o.created_at, "source": o.source, "source_label": o.get_source_display(),
            "status": o.status, "status_label": o.get_status_display(), "payment_status": o.payment_status,
            "payment_status_label": o.get_payment_status_display(), "payment_method_label": o.get_payment_method_display(),
            "fulfillment": o.fulfillment, "fulfillment_label": o.get_fulfillment_display(), "date": o.fulfillment_date,
            "time_from": o.time_from, "time_to": o.time_to, "total": o.total, "contact_name": o.contact_name,
            "requires_confirmation": o.requires_confirmation, "is_preorder": o.is_preorder,
            "courier": d.courier.display_name if d and d.courier else None,
            "address": d.address if d else None, "address_pending": bool(d and d.address_pending),
            "surprise": bool(d and d.surprise), "anonymous": bool(d and d.anonymous), "photo_before": o.photo_before,
        })
    return Response(rows)


@doc("Карточка заказа")
@api_view(["GET"])
@permission_classes([AnyStaff])
def order_detail(request, order_id):
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Сменить статус {status, comment}")
@api_view(["POST"])
@permission_classes([AnyStaff])
def order_transition(request, order_id):
    o = _get_order(request.user, order_id)
    to = request.data.get("status")
    if to not in Order.Status.values:
        raise ValidationError("Неизвестный статус")
    orders.transition(o.id, to, user=request.user, comment=(request.data.get("comment") or "")[:255])
    audit(request.user, "order_status", o, request=request, to=to)
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Подтвердить заказ (звонок / проверка флористом)")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def order_confirm(request, order_id):
    o = _get_order(request.user, order_id)
    orders.staff_confirm(o.id, request.user)
    audit(request.user, "order_confirm", o, request=request)
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Отменить заказ {reason}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def order_cancel(request, order_id):
    o = _get_order(request.user, order_id)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        raise ValidationError("Укажите причину отмены")
    orders.cancel(o.id, user=request.user, reason=reason)
    audit(request.user, "order_cancel", o, request=request, reason=reason)
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Назначить курьера {courier_id}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def order_assign(request, order_id):
    o = _get_order(request.user, order_id)
    orders.assign_courier(o.id, request.data.get("courier_id"), request.user)
    audit(request.user, "courier_assign", o, request=request, courier_id=request.data.get("courier_id"))
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Возврат оплаты")
@api_view(["POST"])
@permission_classes([OwnerOnly])
def order_refund(request, order_id):
    o = _get_order(request.user, order_id)
    payments.refund_order(o.id, request.user, request.data.get("reason", ""))
    audit(request.user, "order_refund", o, request=request)
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Комментарий сотрудника {text}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def order_note(request, order_id):
    o = _get_order(request.user, order_id)
    orders.add_note(o.id, request.user, request.data.get("text"))
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user))


@doc("Адрес доставки {address, apartment, entrance, floor}: флорист вписывает адрес, который назвал получатель")
@api_view(["PATCH"])
@permission_classes([FloristOrOwner])
def order_delivery(request, order_id):
    o = _get_order(request.user, order_id)
    _, note = orders.set_delivery_address(o.id, request.user, request.data)
    audit(request.user, "order_address", o, request=request)
    data = ser.order_admin(_get_order(request.user, order_id), request.user)
    data["warning"] = note
    return Response(data)


@doc("Фото собранного букета (multipart: image). Первое фото уходит покупателю в мессенджер")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def order_photo_upload(request, order_id):
    o = _get_order(request.user, order_id)
    orders.add_photo(o.id, request.user, _check_image(request.FILES.get("image")))
    audit(request.user, "order_photo", o, request=request)
    return Response(ser.order_admin(_get_order(request.user, order_id), request.user), status=201)


@doc("Удалить фото букета")
@api_view(["DELETE"])
@permission_classes([FloristOrOwner])
def order_photo_delete(request, photo_id):
    o = orders.delete_photo(_int(photo_id), request.user)
    audit(request.user, "order_photo_delete", o, request=request)
    return Response(ser.order_admin(_get_order(request.user, o.id), request.user))


@doc("Проверить ключ Яндекс Карт и геокодер (запросы к Яндексу и OpenStreetMap, до ~20 с)")
@api_view(["GET"])
@permission_classes([OwnerOnly])
def maps_check(request):
    from apps.delivery import maps_check as mc

    return Response(mc.run())


@doc("Сотрудники-курьеры")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def couriers(request):
    return Response([ser.user(u) for u in User.objects.filter(role="courier", is_active=True)])


# ------------------------------------------------------------------ доставки

@doc("Доставки на дату ?date=YYYY-MM-DD (курьер видит только свои)")
@api_view(["GET"])
@permission_classes([AnyStaff])
def deliveries(request):
    d = request.query_params.get("date") or local_today().isoformat()
    qs = Delivery.objects.filter(date=d).select_related("order", "slot", "zone", "courier").exclude(order__status="cancelled")
    if request.user.role == "courier":
        qs = qs.filter(courier=request.user)
    rows = []
    for x in qs.order_by("slot__start_time", "id"):
        o = x.order
        rows.append({
            "id": x.id, "order_id": o.id, "number": o.number, "status": x.status, "status_label": x.get_status_display(),
            "order_status": o.status, "order_status_label": o.get_status_display(), "slot": x.slot.label if x.slot else "",
            "zone": x.zone.name if x.zone else "", "address": x.address, "apartment": x.apartment,
            "recipient": o.recipient_name or o.contact_name, "phone": o.recipient_phone or o.contact_phone,
            "courier": ser.user(x.courier) if x.courier else None, "total": o.total,
            "payment_status_label": o.get_payment_status_display(), "payment_method": o.payment_method,
            "address_pending": x.address_pending, "surprise": x.surprise, "anonymous": x.anonymous,
        })
    slots = [{"id": s.id, "label": s.label, "capacity": s.capacity} for s in DeliverySlot.objects.filter(is_active=True)]
    return Response({"date": d, "deliveries": rows, "slots": slots})


# ------------------------------------------------------------------ товары

PRODUCT_FIELDS = ["name", "category", "species", "color", "color_hex", "short_description", "description", "height_cm",
                  "is_active", "is_featured", "allow_made_to_order", "constructor_enabled", "sort_order"]


def _product_admin(p, viewer):
    avail = inv.availability_map()
    data = ser.product(p, avail, detail=True)
    data.update({f: getattr(p, f) for f in PRODUCT_FIELDS})
    data["images"] = [{"id": i.id, "url": ser.media_url(i.image)} for i in p.images.all()]
    data["constructor_image"] = ser.media_url(p.constructor_image)
    data["constructor_source"] = ser.media_url(p.constructor_source)
    data["constructor_crop"] = p.constructor_crop or None
    data["unit_code"] = p.inventory_item.unit
    item = p.inventory_item
    if viewer.role == User.Role.OWNER:  # закупочные цены видит только владелец
        data["purchase_price"] = item.purchase_price
    data["sku"] = item.sku
    data["min_stock"] = item.min_stock
    bal = StockBalance.objects.filter(item=item).values("quantity", "reserved").first() or {"quantity": 0, "reserved": 0}
    data["stock"] = {"quantity": bal["quantity"], "reserved": bal["reserved"], "free": bal["quantity"] - bal["reserved"]}
    if p.type == Product.Type.BOUQUET:
        recipe = getattr(item, "recipe", None)
        comps = list(recipe.components.select_related("item")) if recipe else []
        data["components"] = [{"item_id": c.item_id, "name": c.item.name, "category": c.item.category,
                               "quantity": c.quantity, "available": avail.get(c.item_id, 0)} for c in comps]
        data["recipe_id"] = recipe.id if recipe else None
        data["can_assemble"] = recipes.capacity(recipe, avail) if recipe else 0
    return data


def _clean_components(raw):
    if not isinstance(raw, list):
        v.fail("components", "Состав букета: некорректный список")
    comps, seen = [], set()
    for n, c in enumerate(raw):
        if not isinstance(c, dict) or not c.get("item_id"):
            continue
        item_id = v.integer(c.get("item_id"), "components", "Материал")
        qty = v.integer(c.get("quantity"), "components", "Количество в составе", min_value=0, max_value=500)
        if qty <= 0:
            continue
        if item_id in seen:
            v.fail("components", "В составе один материал указан дважды")
        seen.add(item_id)
        comps.append({"item_id": item_id, "quantity": qty})
    found = set(InventoryItem.objects.filter(pk__in=seen).values_list("pk", flat=True))
    if found != seen:
        v.fail("components", "Часть материалов состава не найдена на складе")
    return comps


def _apply_stock(request, product, d):
    """Остаток и рецептура из карточки товара: флорист может сразу сделать новый букет доступным."""
    item = product.inventory_item
    if product.type == Product.Type.BOUQUET and "components" in d:
        recipe = recipes.get_or_create_recipe(item)
        recipes.set_components(recipe, _clean_components(d.get("components") or []))
    if d.get("stock") not in (None, ""):
        target = v.integer(d["stock"], "stock", "Остаток", min_value=0, max_value=100000)
        inv.ensure_balance(item)
        current = StockBalance.objects.filter(item=item).values_list("quantity", flat=True).first() or 0
        if target != current:
            inv.inventory_count({item.id: target}, user=request.user,
                                reason=v.text(d.get("stock_reason"), "stock_reason", "Причина", max_len=200)
                                or "Остаток изменён в карточке товара")


def _clean_product(d, ptype):
    """Проверка полей карточки товара: на входе — данные формы, на выходе — только корректные значения."""
    out = {}
    if "name" in d:
        out["name"] = v.text(d["name"], "name", "Название", required=True, min_len=2, max_len=160)
    if "category" in d:
        out["category"] = categories.clean_product_category(ptype, d["category"])
    if "species" in d:
        out["species"] = v.text(d["species"], "species", "Вид / стиль", max_len=60)
    if "color" in d:
        out["color"] = v.text(d["color"], "color", "Цвет", max_len=40)
    if "color_hex" in d:
        out["color_hex"] = v.hex_color(d["color_hex"], "color_hex", "Оттенок")
    if "short_description" in d:
        out["short_description"] = v.text(d["short_description"], "short_description", "Короткое описание", max_len=255)
    if "description" in d:
        out["description"] = v.text(d["description"], "description", "Описание", max_len=5000, multiline=True)
    if "height_cm" in d:
        out["height_cm"] = v.integer(d["height_cm"], "height_cm", "Высота, см", min_value=5, max_value=300, allow_none=True)
    for f in ("is_active", "is_featured", "allow_made_to_order", "constructor_enabled"):
        if f in d:
            out[f] = v.boolean(d[f])
    if "sort_order" in d:
        so = v.integer(d["sort_order"], "sort_order", "Порядок", min_value=-10000, max_value=10000, allow_none=True)
        out["sort_order"] = 100 if so is None else so
    return out


def _clean_item(d):
    out = {}
    if "price" in d:
        out["sale_price"] = v.money(d["price"], "price", "Цена продажи", allow_none=True)
    if "purchase_price" in d:
        out["purchase_price"] = v.money(d["purchase_price"], "purchase_price", "Закупочная цена", required=False) or 0
    if "min_stock" in d:
        out["min_stock"] = v.integer(d["min_stock"], "min_stock", "Минимальный остаток", min_value=0,
                                     max_value=100000, required=False)
    if "unit" in d:
        out["unit"] = v.choice(d["unit"] or "pcs", "unit", "Единица измерения", InventoryItem.Unit.values)
    if d.get("sku"):
        out["sku"] = v.sku(d["sku"])
    return out


def _unique_sku(sku, exclude_id=None):
    qs = InventoryItem.objects.filter(sku__iexact=sku)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        v.fail("sku", f"Артикул {sku} уже занят")
    return sku


def _next_sku(prefix):
    n = InventoryItem.objects.count() + 1
    while InventoryItem.objects.filter(sku=f"{prefix}-{n:04d}").exists():
        n += 1
    return f"{prefix}-{n:04d}"


@doc("Товары")
@api_view(["GET", "POST"])
@permission_classes([FloristOrOwner])
def product_list(request):
    if request.method == "POST":
        return _product_create(request)
    qs = Product.objects.select_related("inventory_item").prefetch_related("images", "inventory_item__recipe__components")
    if request.query_params.get("type"):
        qs = qs.filter(type__in=request.query_params["type"].split(","))
    avail = inv.availability_map()
    return Response([{**ser.product(p, avail), "is_active": p.is_active, "sku": p.inventory_item.sku} for p in qs])


def _check_price_permission(user, data):
    """Цену продажи меняют владелец и флорист; закупочную цену — только владелец."""
    if user.role != User.Role.OWNER and "purchase_price" in data:
        raise PermissionDenied("Закупочную цену может изменить только владелец")
    if user.role not in (User.Role.OWNER, User.Role.FLORIST) and "price" in data:
        raise PermissionDenied("Недостаточно прав для изменения цены")


@transaction.atomic
def _product_create(request):
    d = request.data
    _check_price_permission(request.user, {k: v_ for k, v_ in d.items()
                                           if k in ("price", "purchase_price") and v_ not in (None, "", 0, "0")})
    ptype = d.get("type")
    if ptype not in Product.Type.values:
        v.fail("type", "Укажите тип товара")
    fields = _clean_product({**d, "name": d.get("name")}, ptype)
    item_fields = _clean_item(d)
    name = fields.pop("name")
    base = slugify(d.get("slug") or name, allow_unicode=False) or f"product-{ptype}"
    base = base[:100]
    slug, n = base, 2
    while Product.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    sku = _unique_sku(item_fields.pop("sku")) if item_fields.get("sku") else _next_sku(ptype[:3].upper())
    if request.user.role != User.Role.OWNER:
        item_fields.pop("purchase_price", None)
    item = InventoryItem.objects.create(sku=sku, name=name, category=ptype, **item_fields)
    inv.ensure_balance(item)
    if ptype in ("flower", "greenery", "packaging", "ribbon") and "constructor_enabled" not in fields:
        fields["constructor_enabled"] = True
    p = Product.objects.create(inventory_item=item, slug=slug, name=name, type=ptype, **fields)
    if ptype == "bouquet":
        recipes.get_or_create_recipe(item)
    _apply_stock(request, p, {**d, "stock_reason": "Начальный остаток при создании товара"})
    audit(request.user, "product_create", p, request=request, stock=d.get("stock"))
    return Response(_product_admin(p, request.user), status=201)


@doc("Карточка / изменение товара: цена, остаток {stock}, рецептура букета {components}")
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([FloristOrOwner])
def product_detail(request, product_id):
    p = Product.objects.select_related("inventory_item").filter(pk=_int(product_id)).first()
    if not p:
        raise NotFound("Товар не найден")
    if request.method == "DELETE":
        return _product_delete(request, p)
    if request.method == "PATCH":
        d = request.data
        fields = _clean_product(d, p.type)
        item_fields = _clean_item(d)
        price_changes = {}
        if "sale_price" in item_fields and item_fields["sale_price"] != p.inventory_item.sale_price:
            price_changes["price"] = item_fields["sale_price"]
        if "purchase_price" in item_fields and item_fields["purchase_price"] != p.inventory_item.purchase_price:
            price_changes["purchase_price"] = item_fields["purchase_price"]
        _check_price_permission(request.user, price_changes)
        if "purchase_price" not in price_changes:
            item_fields.pop("purchase_price", None)
        if item_fields.get("sku"):
            _unique_sku(item_fields["sku"], exclude_id=p.inventory_item_id)
        with transaction.atomic():
            for f, val in fields.items():
                setattr(p, f, val)
            p.save()
            item = p.inventory_item
            item.name = p.name
            item.is_active = p.is_active
            for f, val in item_fields.items():
                setattr(item, f, val)
            item.save()
            _apply_stock(request, p, d)
        audit(request.user, "product_update", p, request=request, **fields, **price_changes,
              **{k: d[k] for k in ("stock", "components") if k in d})
    return Response(_product_admin(p, request.user))


def _product_files(p):
    return [i.image for i in p.images.all() if i.image] + [f for f in (p.constructor_image, p.constructor_source) if f]


def _drop_files(files):
    for f in files:
        try:
            f.storage.delete(f.name)
        except Exception:  # noqa: BLE001 — файл уже мог быть удалён вручную
            pass


def _purge_item(item):
    """Полностью удаляет складскую позицию без истории. False — если на неё что-то ссылается."""
    from django.db.models import ProtectedError

    try:
        with transaction.atomic():
            StockMovement.objects.filter(item=item).delete()
            StockBalance.objects.filter(item=item).delete()
            recipe = getattr(item, "recipe", None)
            if recipe:
                recipe.delete()
            item.delete()
        return True
    except ProtectedError:
        return False


def _item_has_history(item):
    """Движения склада, резервы, рецептуры или индивидуальные букеты в заказах — позицию нельзя стирать бесследно."""
    from apps.orders.models import OrderItem

    return (StockMovement.objects.filter(item=item).exclude(movement_type=StockMovement.Type.INVENTORY).exists()
            or item.used_in_recipes.exists() or item.reservations.exists()
            or OrderItem.objects.filter(composition__lines__contains=[{"item_id": item.pk}]).exists())


def _product_delete(request, p):
    """Удаление товара.

    Владелец удаляет любой товар навсегда: карточка, фото и строки в корзинах исчезают, в прошлых заказах
    остаются сохранённые название и цена. Складская позиция с историей движений остаётся в архиве склада
    (для отчётов), а если она входит в рецептуры других букетов — остаётся рабочей.
    Исключение — товар в незавершённых заказах: его сначала снимаем с продажи, удалить можно после выполнения.
    Флорист удаляет только товары без истории, остальные снимаются с продажи."""
    from apps.orders.models import OrderItem

    item = p.inventory_item
    name = p.name
    owner = request.user.role == User.Role.OWNER
    active = list(Order.objects.filter(items__product=p, status__in=list(ACTIVE_STATUSES))
                  .values_list("number", flat=True).distinct()[:5])
    if owner and not active:
        files = _product_files(p)
        with transaction.atomic():
            p.delete()
        _drop_files(files)
        item = InventoryItem.objects.get(pk=item.pk)
        note = ""
        if _item_has_history(item) or not _purge_item(item):
            in_recipes = list(item.used_in_recipes.values_list("recipe__bouquet_item__name", flat=True).distinct()[:3])
            if in_recipes:
                note = (" Складская позиция оставлена — она входит в рецептуры: " + ", ".join(f"«{n}»" for n in in_recipes)
                        + ".")
            else:
                item.is_active = False
                item.save(update_fields=["is_active", "updated_at"])
                note = " История склада сохранена в архиве склада."
        audit(request.user, "product_delete", request=request, name=name, item_id=item.pk)
        return Response({"ok": True, "archived": False, "message": f"Товар «{name}» удалён навсегда.{note}"})

    used = bool(active) or OrderItem.objects.filter(product=p).exists() or _item_has_history(item)
    if not used:
        files = _product_files(p)
        with transaction.atomic():
            p.delete()
        if not _purge_item(InventoryItem.objects.get(pk=item.pk)):
            InventoryItem.objects.filter(pk=item.pk).update(is_active=False)
        _drop_files(files)
        audit(request.user, "product_delete", request=request, name=name)
        return Response({"ok": True, "archived": False, "message": f"Товар «{name}» удалён"})

    p.is_active = False
    p.constructor_enabled = False
    p.save(update_fields=["is_active", "constructor_enabled", "updated_at"])
    if not item.used_in_recipes.exists():
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
    audit(request.user, "product_archive", p, request=request)
    if active:
        nums = ", ".join(f"№{n}" for n in active)
        msg = (f"Товар есть в незавершённых заказах ({nums}) — он снят с продажи и скрыт. "
               "Удалить навсегда можно после выполнения или отмены этих заказов.")
    else:
        msg = "У товара есть история продаж или движений склада — он снят с продажи и скрыт. Удалить навсегда может владелец."
    return Response({"ok": True, "archived": True, "message": msg})


@doc("Загрузить фото товара (multipart: image)")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def product_image_upload(request, product_id):
    p = Product.objects.filter(pk=_int(product_id)).first()
    if not p:
        raise NotFound("Товар не найден")
    f = _check_image(request.FILES.get("image"))
    if p.images.count() >= 12:
        v.fail("image", "У товара уже 12 фото — удалите лишние")
    ProductImage.objects.create(product=p, image=f, alt=p.name, sort_order=p.images.count())
    audit(request.user, "product_image_upload", p, request=request)
    return Response(_product_admin(p, request.user))


IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000  # ~ 7700×5200: больше не бывает у реальных фото, а «бомбы» отсекаем
IMAGE_MAX_SIDE = 2560
IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "MPO": "jpg"}


def _check_image(f, field="image"):
    """Проверка и «перепаковка» загруженной картинки.

    Принимаем только настоящие JPG/PNG/WebP (по содержимому, а не по расширению), режем «бомбы»
    из миллиардов пикселей, поворачиваем по EXIF и сохраняем заново: из файла пропадают EXIF/GPS
    и любые «приклеенные» к картинке данные (скрипты, архивы). Имя файла — случайное.
    Возвращает новый файл — именно его и нужно сохранять."""
    import uuid
    import warnings

    from django.core.files.base import ContentFile

    if not f:
        v.fail(field, "Выберите файл изображения")
    if f.size > IMAGE_MAX_BYTES:
        v.fail(field, "Файл больше 8 МБ — уменьшите фото")
    bad = "Файл не является изображением (нужен JPG, PNG или WebP)"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            f.seek(0)
            img = Image.open(f)
            fmt = (img.format or "").upper()
            if fmt not in IMAGE_FORMATS:
                v.fail(field, bad)
            w, h = img.size
            if w * h > IMAGE_MAX_PIXELS:
                v.fail(field, "Слишком большое разрешение — уменьшите фото до 40 мегапикселей")
            if w < 16 or h < 16:
                v.fail(field, "Картинка слишком маленькая")
            img.verify()
            f.seek(0)
            img = Image.open(f)
            img.load()
    except v.ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        v.fail(field, "Слишком большое разрешение — уменьшите фото до 40 мегапикселей")
    except Exception:  # noqa: BLE001
        v.fail(field, bad)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001 — битый EXIF не повод отказывать
        pass
    if max(img.size) > IMAGE_MAX_SIDE:
        img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), Image.LANCZOS)
    ext = IMAGE_FORMATS[fmt]
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    buf = io.BytesIO()
    if ext == "jpg":
        img.convert("RGB").save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    elif ext == "webp":
        img.convert("RGBA" if has_alpha else "RGB").save(buf, "WEBP", quality=88, method=4)
    else:
        img.convert("RGBA" if has_alpha else "RGB").save(buf, "PNG", optimize=True)
    f.seek(0)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex[:16]}.{ext}")


def _replace_file(field, name, content):
    old = field.name if field else ""
    field.save(name, content, save=False)
    if old and old != field.name:
        field.storage.delete(old)


@doc("Фото для конструктора: загрузить (multipart: image, remove_background=true|false) или удалить. "
     "Для цветов фон убирается нейросетью, бутон выделяется автоматически.")
@api_view(["POST", "DELETE"])
@permission_classes([FloristOrOwner])
def product_constructor_image(request, product_id):
    from apps.catalog import cutout

    p = Product.objects.select_related("inventory_item").filter(pk=_int(product_id)).first()
    if not p:
        raise NotFound("Товар не найден")
    if request.method == "DELETE":
        for f in (p.constructor_image, p.constructor_source):
            if f:
                f.delete(save=False)
        p.constructor_image = ""
        p.constructor_source = ""
        p.constructor_crop = {}
        p.save(update_fields=["constructor_image", "constructor_source", "constructor_crop", "updated_at"])
        audit(request.user, "product_constructor_image_delete", p, request=request)
        return Response(_product_admin(p, request.user))
    f = _check_image(request.FILES.get("image"))
    remove_bg = str(request.data.get("remove_background", "true")).lower() not in ("0", "false", "no", "off")
    prepared = cutout.prepare(f, p.type, remove_background=remove_bg)
    _replace_file(p.constructor_image, f"{p.slug}-{prepared.file.name}", prepared.file)
    if prepared.source is not None:
        _replace_file(p.constructor_source, f"{p.slug}-{prepared.source.name}", prepared.source)
        p.constructor_crop = prepared.crop or {}
    else:
        if p.constructor_source:
            p.constructor_source.delete(save=False)
        p.constructor_source = ""
        p.constructor_crop = {}
    p.save(update_fields=["constructor_image", "constructor_source", "constructor_crop", "updated_at"])
    audit(request.user, "product_constructor_image_upload", p, request=request,
          background_removed=prepared.background_removed)
    data = _product_admin(p, request.user)
    data["constructor_image_note"] = prepared.note or (
        "Фон убран автоматически — проверьте превью." if prepared.background_removed else "")
    return Response(data)


@doc("Изменить кадр бутона для конструктора {x, y, w, h} — доли исходной вырезки 0..1")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def product_constructor_crop(request, product_id):
    from apps.catalog import cutout

    p = Product.objects.filter(pk=_int(product_id)).first()
    if not p:
        raise NotFound("Товар не найден")
    if not p.constructor_source:
        v.fail("crop", "Сначала загрузите фото для конструктора")
    box = cutout.clean_crop(request.data)
    with p.constructor_source.open("rb") as fh:
        source = Image.open(fh)
        source.load()
    content = cutout.crop_image(source, box)
    _replace_file(p.constructor_image, f"{p.slug}-{content.name}", content)
    p.constructor_crop = box
    p.save(update_fields=["constructor_image", "constructor_crop", "updated_at"])
    audit(request.user, "product_constructor_crop", p, request=request, **box)
    return Response(_product_admin(p, request.user))


@doc("Удалить фото товара")
@api_view(["DELETE"])
@permission_classes([FloristOrOwner])
def product_image_delete(request, image_id):
    img = ProductImage.objects.filter(pk=_int(image_id)).first()
    if not img:
        raise NotFound("Фото не найдено")
    p = img.product
    img.delete()
    audit(request.user, "product_image_delete", p, request=request)
    return Response(_product_admin(p, request.user))


# ------------------------------------------------------------------ склад

def _inventory_rows(request, qs):
    bals = {b["item_id"]: b for b in StockBalance.objects.values("item_id", "quantity", "reserved")}
    rows = [ser.inventory_item(i, bals.get(i.id)) for i in qs]
    if request.user.role != User.Role.OWNER:
        for r in rows:
            r.pop("purchase_price", None)
    return rows


def _clean_inventory_item(d, partial, item=None):
    out = {}
    if "name" in d or not partial:
        out["name"] = v.text(d.get("name"), "name", "Название", required=True, min_len=2, max_len=160)
    if "category" in d or not partial:
        cat = v.choice(d.get("category"), "category", "Группа", InventoryItem.Category.values)
        if item is not None and cat != item.category and hasattr(item, "product"):
            v.fail("category", "Группу товара витрины менять нельзя — создайте новый товар")
        out["category"] = cat
    out.update(_clean_item(d))
    if "sale_price" in d:  # в форме склада цена продажи приходит как sale_price
        out["sale_price"] = v.money(d["sale_price"], "sale_price", "Цена продажи", allow_none=True)
    if "is_active" in d:
        out["is_active"] = v.boolean(d["is_active"])
    return out


@doc("Складские позиции с остатками ?category=&q=&archived=1; POST — новая позиция (владелец)")
@api_view(["GET", "POST"])
@permission_classes([FloristOrOwner])
def inventory_list(request):
    if request.method == "POST":
        if request.user.role != User.Role.OWNER:
            raise PermissionDenied("Создавать складские позиции может только владелец")
        d = request.data
        data = _clean_inventory_item(d, partial=False)
        sku = _unique_sku(data.pop("sku")) if data.get("sku") else _next_sku(data["category"][:3].upper())
        qty = v.integer(d.get("quantity"), "quantity", "Начальный остаток", min_value=0, max_value=100000, required=False)
        with transaction.atomic():
            item = InventoryItem.objects.create(sku=sku, **data)
            inv.ensure_balance(item)
            if qty:
                inv.inventory_count({item.id: qty}, user=request.user, reason="Начальный остаток")
        audit(request.user, "inventory_item_create", item, request=request, quantity=qty)
        return Response(_inventory_rows(request, InventoryItem.objects.filter(pk=item.pk))[0], status=201)
    qs = InventoryItem.objects.select_related("product").prefetch_related("product__images")
    p = request.query_params
    if p.get("category"):
        qs = qs.filter(category__in=p["category"].split(","))
    if p.get("q"):
        qs = qs.filter(Q(name__icontains=p["q"]) | Q(sku__icontains=p["q"]))
    if p.get("archived") == "0":
        qs = qs.filter(is_active=True)
    elif p.get("archived") == "1":
        qs = qs.filter(is_active=False)
    return Response(_inventory_rows(request, qs))


@doc("Складская позиция: изменить {name, category, unit, sku, purchase_price, sale_price, min_stock, is_active} "
     "или удалить (позиция с историей переносится в архив). Только владелец.")
@api_view(["PATCH", "DELETE"])
@permission_classes([OwnerOnly])
def inventory_item_detail(request, item_id):
    item = InventoryItem.objects.filter(pk=_int(item_id)).first()
    if not item:
        raise NotFound("Позиция не найдена")
    product = getattr(item, "product", None)
    if request.method == "DELETE":
        if product:
            return _product_delete(request, product)
        has_history = (StockMovement.objects.filter(item=item).exclude(movement_type=StockMovement.Type.INVENTORY).exists()
                       or item.used_in_recipes.exists())
        name = item.name
        if has_history:
            item.is_active = False
            item.save(update_fields=["is_active", "updated_at"])
            audit(request.user, "inventory_item_archive", item, request=request)
            return Response({"ok": True, "archived": True,
                             "message": f"«{name}» есть в истории операций или рецептурах — позиция перенесена в архив"})
        with transaction.atomic():
            StockMovement.objects.filter(item=item).delete()
            StockBalance.objects.filter(item=item).delete()
            item.delete()
        audit(request.user, "inventory_item_delete", request=request, name=name)
        return Response({"ok": True, "archived": False, "message": f"Позиция «{name}» удалена"})
    data = _clean_inventory_item(request.data, partial=True, item=item)
    if data.get("sku"):
        _unique_sku(data["sku"], exclude_id=item.pk)
    elif "sku" in data:
        data.pop("sku")
    with transaction.atomic():
        for f, val in data.items():
            setattr(item, f, val)
        item.save()
        if product and ({"name", "is_active"} & set(data)):
            product.name = item.name
            product.is_active = item.is_active
            product.save(update_fields=["name", "is_active", "updated_at"])
    audit(request.user, "inventory_item_update", item, request=request, **data)
    return Response(_inventory_rows(request, InventoryItem.objects.filter(pk=item.pk))[0])


def _item_id(value, field="item_id"):
    item_id = v.integer(value, field, "Позиция", min_value=1)
    if not InventoryItem.objects.filter(pk=item_id).exists():
        v.fail(field, "Позиция склада не найдена")
    return item_id


@doc("Поставка {lines:[{item_id, quantity, unit_cost}], comment}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def inventory_supply(request):
    raw = request.data.get("lines")
    if not isinstance(raw, list) or not raw:
        v.fail("lines", "Добавьте хотя бы одну позицию поставки")
    if len(raw) > 200:
        v.fail("lines", "Не больше 200 позиций в одной поставке")
    lines = []
    for l in raw:
        if not isinstance(l, dict):
            v.fail("lines", "Некорректная строка поставки")
        cost = l.get("unit_cost")
        if request.user.role != User.Role.OWNER:
            cost = None  # закупочные цены вносит только владелец
        lines.append(inv.SupplyLine(
            item_id=_item_id(l.get("item_id")),
            quantity=v.integer(l.get("quantity"), "quantity", "Количество", min_value=1, max_value=100000),
            unit_cost=v.money(cost, "unit_cost", "Цена закупки", allow_none=True)))
    comment = v.text(request.data.get("comment"), "comment", "Комментарий", max_len=200) or "Поставка"
    moves = inv.receive_supply(lines, user=request.user, reason=comment)
    audit(request.user, "stock_supply", request=request, lines=len(moves))
    return Response({"ok": True, "movements": len(moves)})


@doc("Списание {item_id, quantity, reason}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def inventory_write_off(request):
    d = request.data
    m = inv.write_off(_item_id(d.get("item_id")),
                      v.integer(d.get("quantity"), "quantity", "Количество", min_value=1, max_value=100000),
                      v.text(d.get("reason"), "reason", "Причина списания", required=True, min_len=3, max_len=200),
                      user=request.user)
    audit(request.user, "stock_write_off", m.item, request=request, quantity=-m.quantity_delta, reason=m.reason)
    return Response({"ok": True, "balance_after": m.balance_after})


@doc("Корректировка {item_id, delta, reason}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def inventory_adjust(request):
    d = request.data
    delta = v.integer(d.get("delta"), "delta", "Изменение", min_value=-100000, max_value=100000)
    if delta == 0:
        v.fail("delta", "Изменение не может быть нулевым")
    m = inv.adjust(_item_id(d.get("item_id")), delta,
                   v.text(d.get("reason"), "reason", "Причина корректировки", required=True, min_len=3, max_len=200),
                   user=request.user)
    audit(request.user, "stock_adjust", m.item, request=request, delta=m.quantity_delta, reason=m.reason)
    return Response({"ok": True, "balance_after": m.balance_after})


@doc("Инвентаризация {counts:[{item_id, counted}], comment}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def inventory_count(request):
    raw = request.data.get("counts")
    if not isinstance(raw, list):
        v.fail("counts", "Укажите фактические остатки")
    counts = {}
    for c in raw:
        if isinstance(c, dict) and c.get("counted") not in (None, ""):
            counts[_item_id(c.get("item_id"))] = v.integer(c["counted"], "counted", "Фактический остаток",
                                                           min_value=0, max_value=100000)
    if not counts:
        v.fail("counts", "Укажите фактические остатки")
    comment = v.text(request.data.get("comment"), "comment", "Комментарий", max_len=200) or "Инвентаризация"
    res = inv.inventory_count(counts, user=request.user, reason=comment)
    audit(request.user, "stock_inventory", request=request, items=len(res), changed=sum(1 for r in res if r["delta"]))
    return Response({"ok": True, "result": [{k: val for k, val in r.items() if k != "movement"} for r in res]})


def _date_param(value, field):
    from datetime import date

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        v.fail(field, "Дата в формате ГГГГ-ММ-ДД")


@doc("История операций ?item_id=&type=&date_from=&date_to=&q=&limit=&export=csv")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def inventory_movements(request):
    from datetime import datetime, time as dtime

    qs = StockMovement.objects.select_related("item", "user", "order")
    p = request.query_params
    if p.get("item_id"):
        qs = qs.filter(item_id=_int(p["item_id"]))
    if p.get("type"):
        qs = qs.filter(movement_type__in=p["type"].split(","))
    if p.get("q"):
        qs = qs.filter(Q(item__name__icontains=p["q"]) | Q(reason__icontains=p["q"]))
    tz = timezone.get_current_timezone()
    d_from = _date_param(p["date_from"], "date_from") if p.get("date_from") else None
    d_to = _date_param(p["date_to"], "date_to") if p.get("date_to") else None
    if d_from and d_to and d_from > d_to:
        v.fail("date_to", "Дата «по» раньше даты «с»")
    if d_from:
        qs = qs.filter(created_at__gte=datetime.combine(d_from, dtime.min, tzinfo=tz))
    if d_to:
        qs = qs.filter(created_at__lt=datetime.combine(d_to + timedelta(days=1), dtime.min, tzinfo=tz))
    show_cost = request.user.role == User.Role.OWNER
    if p.get("export") == "csv":
        return _movements_csv(qs[:20000], show_cost)
    limit = min(max(_int(p.get("limit", 100), "limit"), 1), 500)
    return Response([
        {"id": m.id, "at": m.created_at, "item": m.item.name, "item_id": m.item_id, "type": m.movement_type,
         "type_label": m.get_movement_type_display(), "delta": m.quantity_delta, "balance_after": m.balance_after,
         "reason": m.reason, "user": m.user.display_name if m.user else "система",
         "order_number": m.order.number if m.order else None, "unit_cost": m.unit_cost if show_cost else None}
        for m in qs[:limit]
    ])


def _movements_csv(qs, show_cost):
    import csv
    import io

    from django.http import HttpResponse

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    head = ["Дата", "Позиция", "Артикул", "Операция", "Изменение", "Остаток после", "Причина", "Сотрудник", "Заказ"]
    w.writerow(head + (["Цена закупки, ₽"] if show_cost else []))
    for m in qs:
        row = [timezone.localtime(m.created_at).strftime("%d.%m.%Y %H:%M"), m.item.name, m.item.sku,
               m.get_movement_type_display(), m.quantity_delta, m.balance_after, m.reason,
               m.user.display_name if m.user else "система", m.order.number if m.order else ""]
        if show_cost:
            row.append(f"{m.unit_cost / 100:.2f}".replace(".", ",") if m.unit_cost is not None else "")
        w.writerow(row)
    resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="stock-movements-{local_today():%Y-%m-%d}.csv"'
    return resp


@doc("Плановый спрос по будущим датам (предзаказы и сборка под заказ)")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def inventory_demand(request):
    today = local_today()
    demand = defaultdict(lambda: defaultdict(int))
    names = {}
    qs = Order.objects.filter(fulfillment_date__gt=today, status__in=list(ACTIVE_STATUSES)).prefetch_related(
        "items__product__inventory_item__recipe__components__item")
    for o in qs:
        for it in o.items.all():
            if it.item_type == "custom_bouquet":
                for line in (it.composition or {}).get("lines", []):
                    demand[o.fulfillment_date][line["item_id"]] += line["quantity"] * it.quantity
                    names[line["item_id"]] = line["name"]
            elif it.product:
                recipe = getattr(it.product.inventory_item, "recipe", None)
                plan = it.fulfillment_plan or {}
                to_build = plan.get("made_to_order", 0) + plan.get("preorder", 0)
                if recipe and to_build and it.product.type == "bouquet":
                    for c in recipe.components.all():
                        demand[o.fulfillment_date][c.item_id] += c.quantity * to_build
                        names[c.item_id] = c.item.name
                else:
                    demand[o.fulfillment_date][it.inventory_item_id] += it.quantity
                    names[it.inventory_item_id] = it.name
    avail = inv.availability_map()
    rows = []
    for d in sorted(demand):
        for item_id, qty in sorted(demand[d].items(), key=lambda kv: names.get(kv[0], "")):
            rows.append({"date": d, "item_id": item_id, "item": names.get(item_id, ""), "planned": qty,
                         "available_now": avail.get(item_id, 0)})
    return Response(rows)


# ------------------------------------------------------------------ продажа в магазине

@doc("Быстрая продажа в магазине {lines:[{product_id, quantity}], payment: cash|card, customer_phone}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def store_sale(request):
    d = request.data
    lines = d.get("lines")
    if not isinstance(lines, list) or not lines:
        v.fail("lines", "Добавьте товары в продажу")
    for l in lines:
        if not isinstance(l, dict):
            v.fail("lines", "Некорректная строка продажи")
        v.integer(l.get("product_id"), "lines", "Товар", min_value=1)
        v.integer(l.get("quantity"), "lines", "Количество", min_value=1, max_value=1000)
    o = orders.store_sale(lines, v.choice(d.get("payment"), "payment", "Оплата", ("cash", "card")), request.user,
                          customer_phone=v.phone(d.get("customer_phone"), "customer_phone", required=False),
                          customer_name=v.person_name(d.get("customer_name"), "customer_name", required=False))
    audit(request.user, "store_sale", o, request=request, total=o.total)
    return Response({"ok": True, "order_id": o.id, "number": o.number, "total": o.total}, status=201)


# ------------------------------------------------------------------ рецептуры

def _recipe(r, avail):
    p = getattr(r.bouquet_item, "product", None)
    bal = StockBalance.objects.filter(item=r.bouquet_item).first()
    return {
        "id": r.id, "bouquet_item_id": r.bouquet_item_id, "name": r.bouquet_item.name, "product_id": p.id if p else None,
        "price": r.bouquet_item.sale_price, "cost": recipes.cost(r), "can_assemble": recipes.capacity(r, avail),
        "assembled_available": bal.available if bal else 0, "made_to_order": p.allow_made_to_order if p else False,
        "image": ser.media_url(p.images.first().image) if p and p.images.first() else None,
        "components": [{"item_id": c.item_id, "name": c.item.name, "category": c.item.category, "quantity": c.quantity,
                        "available": avail.get(c.item_id, 0)} for c in r.components.select_related("item")],
    }


@doc("Рецептуры готовых букетов")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def recipe_list(request):
    avail = inv.availability_map()
    qs = BouquetRecipe.objects.select_related("bouquet_item__product").prefetch_related("bouquet_item__product__images")
    return Response([_recipe(r, avail) for r in qs.order_by("bouquet_item__name")])


@doc("Изменить состав рецептуры {components:[{item_id, quantity}]}")
@api_view(["PUT"])
@permission_classes([FloristOrOwner])
def recipe_update(request, recipe_id):
    r = BouquetRecipe.objects.filter(pk=_int(recipe_id)).first()
    if not r:
        raise NotFound("Рецептура не найдена")
    recipes.set_components(r, request.data.get("components") or [])
    audit(request.user, "recipe_update", r, request=request, components=request.data.get("components"))
    return Response(_recipe(r, inv.availability_map()))


@doc("Собрать готовые букеты заранее {count}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def recipe_assemble(request, recipe_id):
    r = BouquetRecipe.objects.filter(pk=_int(recipe_id)).first()
    if not r:
        raise NotFound("Рецептура не найдена")
    recipes.assemble(r, request.data.get("count", 1), user=request.user)
    audit(request.user, "bouquet_assemble", r, request=request, count=request.data.get("count"))
    return Response(_recipe(r, inv.availability_map()))


# ------------------------------------------------------------------ клиенты

@doc("Клиенты ?q=")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def customer_list(request):
    qs = Customer.objects.annotate(orders_count=Count("orders"), orders_sum=Sum("orders__total", filter=~Q(orders__status="cancelled"))).prefetch_related("channels")
    q = request.query_params.get("q")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    return Response([
        {"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "orders_count": c.orders_count,
         "orders_sum": c.orders_sum or 0, "created_at": c.created_at, "is_demo": c.is_demo,
         "channels": [{"channel": ch.channel, "label": ch.get_channel_display(), "username": ch.username,
                       "simulated": ch.is_simulated} for ch in c.channels.all()]}
        for c in qs.order_by("-created_at")[:300]
    ])


@doc("Клиент и его заказы")
@api_view(["GET"])
@permission_classes([FloristOrOwner])
def customer_detail(request, customer_id):
    c = Customer.objects.filter(pk=_int(customer_id)).first()
    if not c:
        raise NotFound("Клиент не найден")
    return Response({"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "notes": c.notes,
                     "orders": [{"id": o.id, "number": o.number, "status_label": o.get_status_display(), "total": o.total,
                                 "created_at": o.created_at, "source_label": o.get_source_display()} for o in c.orders.all()[:50]]})


# ------------------------------------------------------------------ обращения из ботов

@doc("Ответить на обращение из бота {text}")
@api_view(["POST"])
@permission_classes([FloristOrOwner])
def support_reply(request, notification_id):
    n = Notification.objects.filter(pk=_int(notification_id), kind="support_request").first()
    if not n:
        raise NotFound("Обращение не найдено")
    text = (request.data.get("text") or "").strip()
    if not text:
        raise ValidationError("Введите ответ")
    payload = n.payload or {}
    notifications.create(payload.get("reply_channel"), f"💬 Ответ флориста: {text}", kind="support_reply",
                         recipient=payload.get("reply_to"), customer=n.customer)
    n.is_handled = True
    n.save(update_fields=["is_handled"])
    audit(request.user, "support_reply", n, request=request)
    return Response({"ok": True})


# ------------------------------------------------------------------ сотрудники (владелец)

USERNAME_RE = r"^[A-Za-z0-9_.\-]{3,30}$"


def _password(value, user=None, field="password"):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    if not value or len(value) > 128:
        v.fail(field, "Пароль: от 10 до 128 символов")
    try:
        validate_password(value, user)
    except DjangoValidationError as e:
        v.fail(field, "Пароль: " + " ".join(e.messages))
    return value


@doc("Сотрудники")
@api_view(["GET", "POST"])
@permission_classes([OwnerOnly])
def staff_list(request):
    import re

    if request.method == "POST":
        d = request.data
        role = v.choice(d.get("role"), "role", "Роль", User.Role.values)
        username = (d.get("username") or "").strip()
        if not re.match(USERNAME_RE, username):
            v.fail("username", "Логин: 3–30 символов — латиница, цифры, точка, дефис или _")
        if User.objects.filter(username__iexact=username).exists():
            v.fail("username", "Такой логин уже занят")
        first = v.person_name(d.get("first_name"), "first_name", "Имя", required=False, max_len=60)
        last = v.person_name(d.get("last_name"), "last_name", "Фамилия", required=False, max_len=60)
        phone = v.phone(d.get("phone"), "phone", required=False)
        password = _password(d.get("password") or "")
        u = User.objects.create_user(username=username, password=password, role=role,
                                     first_name=first, last_name=last, phone=phone)
        audit(request.user, "staff_create", u, request=request, role=u.role)
        return Response(ser.user(u), status=201)
    return Response([ser.user(u) for u in User.objects.order_by("role", "username")])


@doc("Изменить сотрудника {role, is_active, password, first_name, last_name, phone} или удалить его учётную запись")
@api_view(["PATCH", "DELETE"])
@permission_classes([OwnerOnly])
def staff_detail(request, user_id):
    u = User.objects.filter(pk=_int(user_id)).first()
    if not u:
        raise NotFound("Сотрудник не найден")
    if request.method == "DELETE":
        if u.pk == request.user.pk:
            raise ValidationError("Нельзя удалить собственную учётную запись")
        if u.role == User.Role.OWNER and not User.objects.filter(role=User.Role.OWNER, is_active=True).exclude(pk=u.pk).exists():
            raise ValidationError("Нельзя удалить последнего владельца")
        audit(request.user, "staff_delete", u, request=request, username=u.username, role=u.role)
        Delivery.objects.filter(courier=u, status__in=[Delivery.Status.PENDING, Delivery.Status.ASSIGNED]).update(
            courier=None, status=Delivery.Status.PENDING, assigned_at=None)
        u.delete()  # история заказов сохраняется: в ней остаётся имя сотрудника
        return Response({"ok": True})
    d = request.data
    if "role" in d:
        v.choice(d["role"], "role", "Роль", User.Role.values)
    if u.pk == request.user.pk and (("is_active" in d and not v.boolean(d["is_active"]))
                                    or (d.get("role") and d["role"] != "owner")):
        raise ValidationError("Нельзя отключить или понизить собственную учётную запись")
    if "first_name" in d:
        u.first_name = v.person_name(d["first_name"], "first_name", "Имя", required=False, max_len=60)
    if "last_name" in d:
        u.last_name = v.person_name(d["last_name"], "last_name", "Фамилия", required=False, max_len=60)
    if "phone" in d:
        u.phone = v.phone(d["phone"], "phone", required=False)
    if d.get("role"):
        u.role = d["role"]
    if "is_active" in d:
        u.is_active = v.boolean(d["is_active"])
        if not u.is_active:
            StaffToken.objects.filter(user=u).delete()
    if d.get("password"):
        u.set_password(_password(d["password"], u))
        StaffToken.objects.filter(user=u).delete()
    _apply_notify(u, d)
    u.save()
    audit(request.user, "staff_update", u, request=request, fields=[k for k in d.keys() if k != "password"])
    return Response(ser.user(u))


def _apply_notify(u, d):
    """Общие поля уведомлений: режим, смена, отвязка мессенджера (без сохранения)."""
    if "notify_mode" in d:
        u.notify_mode = v.choice(d["notify_mode"], "notify_mode", "Уведомления", User.NotifyMode.values)
    if "on_shift" in d:
        on = v.boolean(d["on_shift"])
        if on != u.on_shift:
            u.on_shift, u.shift_started_at = on, (timezone.now() if on else None)
    unlink = d.get("unlink")
    if unlink in ("telegram", "vk"):
        setattr(u, "telegram_id" if unlink == "telegram" else "vk_id", "")
    elif unlink:
        raise ValidationError("unlink: telegram или vk")


@doc("Одноразовые ссылки, чтобы сотрудник привязал свой Telegram/ВК для уведомлений о заказах (24 ч)")
@api_view(["POST"])
@permission_classes([OwnerOnly])
def staff_link(request, user_id):
    from apps.notifications import staff as staff_notify

    u = User.objects.filter(pk=_int(user_id), is_active=True).first()
    if not u:
        raise NotFound("Сотрудник не найден")
    audit(request.user, "staff_link_created", u, request=request)
    return Response(staff_notify.new_link(u))


@doc("Мои уведомления о заказах: режим, смена, привязанные мессенджеры; PATCH {notify_mode, on_shift, unlink}")
@api_view(["GET", "PATCH"])
@permission_classes([AnyStaff])
def my_notify(request):
    from apps.notifications import staff as staff_notify

    u = request.user
    if request.method == "PATCH":
        _apply_notify(u, request.data)
        u.save()
        audit(request.user, "my_notify_update", u, request=request, fields=list(request.data.keys()))
    return Response({**ser.user(u), "on_shift_now": staff_notify.on_shift_names(),
                     "shift_max_hours": staff_notify.shift_max_hours()})


@doc("Ссылки, чтобы привязать свой Telegram/ВК для уведомлений о заказах (24 ч)")
@api_view(["POST"])
@permission_classes([AnyStaff])
def my_notify_link(request):
    from apps.notifications import staff as staff_notify

    return Response(staff_notify.new_link(request.user))


# ------------------------------------------------------------------ настройки (владелец)

SETTINGS_FIELDS = ["shop_name", "tagline", "city", "address", "phone", "email", "working_hours", "telegram_url",
                   "vk_url", "primary_color", "accent_color", "background_color", "florist_fee",
                   "online_reservation_minutes", "cod_unconfirmed_hold_minutes", "confirmation_hold_hours",
                   "min_lead_minutes", "pickup_ready_minutes", "preorder_threshold_days", "max_order_days_ahead",
                   "max_custom_stems", "min_custom_stems", "allow_cash_on_delivery", "shop_lat", "shop_lon",
                   "flowers_section_enabled", "constructor_section_enabled", "orders_enabled",
                   "customer_login_enabled", "orders_closed_message", "seo_pages", "yandex_verification", "google_verification"]

# поле: (подпись, минимум, максимум) — те же пределы показывает форма настроек
SETTINGS_INT_RULES = {
    "online_reservation_minutes": ("Резерв неоплаченного онлайн-заказа, мин", 5, 120),
    "cod_unconfirmed_hold_minutes": ("Резерв заказа с оплатой при получении, мин", 10, 1440),
    "confirmation_hold_hours": ("Резерв на время подтверждения флористом, ч", 1, 72),
    "min_lead_minutes": ("Минимум времени до доставки, мин", 0, 720),
    "pickup_ready_minutes": ("Подготовка самовывоза, мин", 0, 480),
    "preorder_threshold_days": ("Предзаказ — с какого дня вперёд", 1, 60),
    "max_order_days_ahead": ("Заказ максимум на дней вперёд", 1, 365),
    "min_custom_stems": ("Минимум стеблей в конструкторе", 1, MAX_CUSTOM_STEMS_LIMIT),
    "max_custom_stems": ("Максимум стеблей в конструкторе", 1, MAX_CUSTOM_STEMS_LIMIT),
}
SETTINGS_TEXT_RULES = {
    "shop_name": ("Название магазина", True, 120), "tagline": ("Подзаголовок", False, 200),
    "city": ("Город", True, 80), "address": ("Адрес", True, 255), "working_hours": ("Часы работы", True, 120),
}


def _clean_settings(d, s):
    out = {}
    for f, (label, required, max_len) in SETTINGS_TEXT_RULES.items():
        if f in d:
            out[f] = v.text(d[f], f, label, required=required, max_len=max_len, min_len=2 if required else 0)
    if "phone" in d:
        v.phone(d["phone"], "phone", "Телефон магазина")  # проверяем формат, храним как ввёл владелец
        out["phone"] = v.text(d["phone"], "phone", "Телефон магазина", required=True, max_len=40)
    if "email" in d:
        out["email"] = v.email(d["email"], "email", "E-mail магазина")
    if "telegram_url" in d:
        out["telegram_url"] = v.url(d["telegram_url"], "telegram_url", "Ссылка на Telegram", hosts=("t.me", "telegram.me"))
    if "vk_url" in d:
        out["vk_url"] = v.url(d["vk_url"], "vk_url", "Ссылка на VK", hosts=("vk.com", "vk.ru", "m.vk.com"))
    for f, label in (("primary_color", "Основной цвет"), ("accent_color", "Акцентный цвет"),
                     ("background_color", "Цвет фона")):
        if f in d:
            out[f] = v.hex_color(d[f], f, label, required=True)
    if "florist_fee" in d:
        out["florist_fee"] = v.money(d["florist_fee"], "florist_fee", "Работа флориста", max_value=1_000_000)
    for f, (label, lo, hi) in SETTINGS_INT_RULES.items():
        if f in d:
            out[f] = v.integer(d[f], f, label, min_value=lo, max_value=hi)
    for f in ("allow_cash_on_delivery", "flowers_section_enabled", "constructor_section_enabled", "orders_enabled",
              "customer_login_enabled"):
        if f in d:
            out[f] = v.boolean(d[f])
    if "orders_closed_message" in d:
        out["orders_closed_message"] = v.text(d["orders_closed_message"], "orders_closed_message",
                                              "Сообщение покупателям", max_len=300, multiline=True)
    if "seo_pages" in d:
        out["seo_pages"] = site_content.clean_seo_pages(d["seo_pages"])
    if "yandex_verification" in d:
        out["yandex_verification"] = site_content.clean_verification(d["yandex_verification"], "yandex_verification",
                                                                     "Код Яндекс Вебмастера")
    if "google_verification" in d:
        out["google_verification"] = site_content.clean_verification(d["google_verification"], "google_verification",
                                                                     "Код Google Search Console")
    if "shop_lat" in d:
        out["shop_lat"] = v.number(d["shop_lat"], "shop_lat", "Широта магазина", min_value=41.0, max_value=82.0)
    if "shop_lon" in d:
        out["shop_lon"] = v.number(d["shop_lon"], "shop_lon", "Долгота магазина", min_value=19.0, max_value=180.0)
    get = lambda f: out.get(f, getattr(s, f))  # noqa: E731
    if get("min_custom_stems") > get("max_custom_stems"):
        v.fail("min_custom_stems", "Минимум стеблей не может быть больше максимума")
    if get("preorder_threshold_days") > get("max_order_days_ahead"):
        v.fail("preorder_threshold_days", "Порог предзаказа не может быть дальше, чем максимум дней для заказа")
    return out


@doc("Настройки магазина")
@api_view(["GET", "PATCH", "POST"])
@permission_classes([OwnerOnly])
def settings_view(request):
    s = ShopSettings.load()
    if request.method == "PATCH":
        changed = _clean_settings(request.data, s)
        for f, value in changed.items():
            setattr(s, f, value)
        s.save()
        audit(request.user, "settings_update", s, request=request, **changed)
    elif request.method == "POST":  # загрузка логотипа / обложки
        for key in ("logo", "hero_image"):
            f = request.FILES.get(key)
            if f:
                clean = _check_image(f, key)
                _replace_file(getattr(s, key), clean.name, clean)
        s.save()
        audit(request.user, "settings_branding", s, request=request)
    data = {f: getattr(s, f) for f in SETTINGS_FIELDS}
    data.update({"logo": ser.media_url(s.logo), "hero_image": ser.media_url(s.hero_image),
                 "orders_closed_default": site_content.ORDERS_CLOSED_DEFAULT,
                 "seo_defaults": site_content.seo_defaults(s),
                 "seo_page_list": [{"key": k, "path": p, "label": lbl} for k, p, lbl in site_content.SEO_PAGES],
                 "site_url": site_content.site_url()})
    return Response(data)


def _clean_zone(d, partial):
    out = {}
    if "name" in d or not partial:
        out["name"] = v.text(d.get("name"), "name", "Название района", required=True, min_len=2, max_len=120)
    if "description" in d:
        out["description"] = v.text(d["description"], "description", "Описание", max_len=255)
    if "price" in d or not partial:
        out["price"] = v.money(d.get("price"), "price", "Стоимость доставки", max_value=10_000_000)
    if "free_from" in d:
        out["free_from"] = v.money(d["free_from"], "free_from", "Бесплатно от", allow_none=True, min_value=100)
    if "polygons" in d:
        out["polygons"] = geo.validate_polygons(d["polygons"])
    if "color" in d:
        out["color"] = v.hex_color(d["color"], "color", "Цвет зоны")
    if "sort_order" in d:
        so = v.integer(d["sort_order"], "sort_order", "Порядок", min_value=-10000, max_value=10000, allow_none=True)
        out["sort_order"] = 100 if so is None else so
    if "is_active" in d:
        out["is_active"] = v.boolean(d["is_active"])
    return out


def _zones_admin():
    return [ser.zone(z, admin=True) for z in DeliveryZone.objects.filter(is_archived=False)]


@doc("Районы доставки")
@api_view(["GET", "POST"])
@permission_classes([OwnerOnly])
def zones(request):
    if request.method == "POST":
        data = _clean_zone(request.data, partial=False)
        if DeliveryZone.objects.filter(name__iexact=data["name"], is_archived=False).exists():
            v.fail("name", f"Район «{data['name']}» уже есть")
        z = DeliveryZone.objects.create(**data)
        audit(request.user, "zone_create", z, request=request)
    return Response(_zones_admin())


@doc("Изменить {name, price, free_from, is_active, polygons, color, sort_order} или удалить район")
@api_view(["PATCH", "DELETE"])
@permission_classes([OwnerOnly])
def zone_detail(request, zone_id):
    z = DeliveryZone.objects.filter(pk=_int(zone_id), is_archived=False).first()
    if not z:
        raise NotFound("Район не найден")
    if request.method == "DELETE":
        name = z.name
        if Delivery.objects.filter(zone=z).exists():
            # по району уже были заказы: скрываем его, история доставок остаётся
            z.is_archived = True
            z.is_active = False
            z.save(update_fields=["is_archived", "is_active"])
            audit(request.user, "zone_archive", z, request=request)
        else:
            audit(request.user, "zone_delete", z, request=request, name=name)
            z.delete()
        return Response({"ok": True, "message": f"Район «{name}» удалён", "zones": _zones_admin()})
    data = _clean_zone(request.data, partial=True)
    if "name" in data and DeliveryZone.objects.filter(name__iexact=data["name"], is_archived=False).exclude(pk=z.pk).exists():
        v.fail("name", f"Район «{data['name']}» уже есть")
    for f, val in data.items():
        setattr(z, f, val)
    z.save()
    audit(request.user, "zone_update", z, request=request,
          **{k: val for k, val in data.items() if k != "polygons"}, polygons_changed="polygons" in data)
    return Response(ser.zone(z, admin=True))


def _slots_admin():
    return [{"id": s.id, "start_time": s.start_time.strftime("%H:%M"), "end_time": s.end_time.strftime("%H:%M"),
             "capacity": s.capacity, "is_active": s.is_active} for s in DeliverySlot.objects.all()]


@doc("Интервалы доставки")
@api_view(["GET", "POST"])
@permission_classes([OwnerOnly])
def slots(request):
    if request.method == "POST":
        d = request.data
        start = v.hhmm(d.get("start_time"), "start_time", "Начало")
        end = v.hhmm(d.get("end_time"), "end_time", "Конец")
        if end <= start:
            v.fail("end_time", "Конец интервала должен быть позже начала")
        if (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute) < 30:
            v.fail("end_time", "Интервал должен быть не короче 30 минут")
        if DeliverySlot.objects.filter(start_time=start, end_time=end).exists():
            v.fail("start_time", "Такой интервал уже есть")
        cap = v.integer(d.get("capacity", 4), "capacity", "Доставок в интервал", min_value=1, max_value=100)
        s = DeliverySlot.objects.create(start_time=start, end_time=end, capacity=cap)
        audit(request.user, "slot_create", s, request=request)
    return Response(_slots_admin())


@doc("Изменить интервал {capacity, is_active} или удалить его")
@api_view(["PATCH", "DELETE"])
@permission_classes([OwnerOnly])
def slot_detail(request, slot_id):
    s = DeliverySlot.objects.filter(pk=_int(slot_id)).first()
    if not s:
        raise NotFound("Интервал не найден")
    if request.method == "DELETE":
        if Delivery.objects.filter(slot=s).exists():
            s.is_active = False
            s.save(update_fields=["is_active"])
            audit(request.user, "slot_disable", s, request=request)
            return Response({"ok": True, "message": "По интервалу уже есть доставки — он выключен, а не удалён",
                             "slots": _slots_admin()})
        audit(request.user, "slot_delete", s, request=request, label=s.label)
        s.delete()
        return Response({"ok": True, "message": "Интервал удалён", "slots": _slots_admin()})
    if "capacity" in request.data:
        s.capacity = v.integer(request.data["capacity"], "capacity", "Доставок в интервал", min_value=1, max_value=100)
    if "is_active" in request.data:
        s.is_active = v.boolean(request.data["is_active"])
    s.save()
    audit(request.user, "slot_update", s, request=request)
    return Response({"ok": True})


@doc("Журнал действий сотрудников")
@api_view(["GET"])
@permission_classes([OwnerOnly])
def audit_log(request):
    qs = AuditLog.objects.select_related("user")[:300]
    return Response([{"id": a.id, "at": a.created_at, "user": a.user.display_name if a.user else a.actor_label,
                      "action": a.action, "entity": f"{a.entity_type}#{a.entity_id}" if a.entity_type else "",
                      "data": a.data, "ip": a.ip} for a in qs])
