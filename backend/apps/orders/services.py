"""Бизнес-логика заказов: оформление, переходы статусов, отмена, истечение резервов, продажа в магазине."""
import logging
from datetime import date as date_cls, timedelta

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.carts import services as carts
from apps.carts.models import CartItem
from apps.catalog import builder
from apps.catalog.models import Product
from apps.core import validation as v
from apps.core.errors import DomainError, NotFound, PermissionDenied, ValidationError
from apps.core.models import ShopSettings, User
from apps.core.utils import local_today, normalize_phone, rub
from apps.customers.services import find_or_create_customer
from apps.delivery import geo
from apps.delivery import services as delivery_services
from apps.delivery.models import ASK_RECIPIENT_ADDRESS, Delivery
from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, consume_free, lock_balances
from apps.payments.providers import registry as payment_registry
from apps.reservations import services as reservations
from apps.reservations.models import StockReservation

from .models import Order, OrderEvent, OrderItem
from .state import COURIER_TRANSITIONS, HOLD_STATUSES, PRE_FULFILLMENT, TRANSITIONS, label

logger = logging.getLogger(__name__)
S = Order.Status
PS = Order.PaymentStatus


def log_event(order, event_type, message="", *, actor=None, actor_label="", from_status="", to_status="", **data):
    return OrderEvent.objects.create(
        order=order, event_type=event_type, message=message, actor=actor if getattr(actor, "pk", None) else None,
        actor_label=actor_label or (actor.display_name if getattr(actor, "pk", None) else "система"),
        from_status=from_status, to_status=to_status, data=data,
    )


def _notify(order, kind, **extra):
    from apps.notifications.services import order_event

    order_event(order, kind, **extra)


# ---------------------------------------------------------------- оформление

def _parse_date(value):
    if isinstance(value, date_cls):
        return value
    try:
        return date_cls.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError("Укажите дату получения", code="invalid_date")


def _hold_minutes_for(order, settings):
    if order.status == S.AWAITING_PAYMENT:
        return settings.online_reservation_minutes
    if order.status == S.AWAITING_CONFIRMATION:
        return settings.confirmation_hold_hours * 60
    if order.status == S.NEW and order.payment_method == Order.PaymentMethod.ON_DELIVERY:
        return settings.cod_unconfirmed_hold_minutes or None
    return None


def _set_hold(order, minutes):
    order.reservation_expires_at = timezone.now() + timedelta(minutes=minutes) if minutes else None
    reservations.set_expiry(order, order.reservation_expires_at)


def _update_signed_in(customer, name, phone, email):
    """Вошедший покупатель: дополняем профиль, но не объединяем его с чужими записями по телефону
    (телефон не подтверждён — иначе можно было бы «присвоить» чужую историю заказов)."""
    from apps.customers.models import Customer

    fields = []
    if name and customer.name != name:
        customer.name = name[:160]
        fields.append("name")
    if email and customer.email != email:
        customer.email = email
        fields.append("email")
    if phone and not customer.phone and not Customer.objects.filter(phone=phone).exclude(pk=customer.pk).exists():
        customer.phone = phone
        fields.append("phone")
    if fields:
        customer.save(update_fields=fields + ["updated_at"])
    return customer


def place_order(cart, data, actor_label="покупатель", customer=None):
    """Оформляет заказ из корзины. Источник заказа = канал корзины (сайт / Telegram / ВК).
    customer — покупатель, вошедший на сайт через Telegram/ВК: заказ привязывается к нему (уведомления уйдут
    в его мессенджер), а не ищется по введённому телефону."""
    expire_overdue_orders()
    data = data or {}
    key = (data.get("idempotency_key") or "").strip()[:64] or None
    if key:
        existing = Order.objects.filter(idempotency_key=key).first()
        if existing:
            return existing
    try:
        with transaction.atomic():
            order = _place_order_tx(cart, data, key, actor_label, customer)
    except IntegrityError:
        if key:
            existing = Order.objects.filter(idempotency_key=key).first()
            if existing:
                return existing
        raise
    return order


def _check_pending_limit(phone, signed_in=None):
    """Защита от «заказов-спама»: не больше N неоплаченных/неподтверждённых заказов на один телефон.
    Каждый такой заказ резервирует цветы, поэтому массовые фейковые заказы могли бы «выкупить» витрину."""
    limit = int(getattr(dj_settings, "MAX_PENDING_ORDERS_PER_PHONE", 0) or 0)
    if limit <= 0:
        return
    q = Order.objects.filter(status__in=list(HOLD_STATUSES)).filter(
        Q(contact_phone=phone) | Q(customer_id=signed_in.pk) if signed_in is not None else Q(contact_phone=phone))
    if q.count() >= limit:
        raise ValidationError(
            f"У вас уже {limit} неоплаченных или неподтверждённых заказа. Оплатите или отмените их — "
            "или позвоните нам, и мы оформим заказ вручную.", code="too_many_pending_orders")


def _place_order_tx(cart, data, key, actor_label, signed_in=None):
    settings = ShopSettings.load()
    carts.assert_orders_open()  # владелец закрыл приём заказов — не принимаем ни с сайта, ни из ботов
    channel = cart.channel
    items = list(cart.items.select_related("product__inventory_item").select_for_update(of=("self",)))
    if not items:
        raise ValidationError("Корзина пуста", code="cart_empty")

    # --- повторная серверная проверка ограничений канала
    lines = []
    for ci in items:
        if ci.item_type == CartItem.ItemType.CUSTOM_BOUQUET:
            carts.assert_custom_allowed(channel)
            q = builder.quote(ci.composition, quantity=ci.quantity, check_stock=False)
            lines.append({"key": ci.id, "type": "custom_bouquet", "product": None, "composition": q["composition"],
                          "quantity": ci.quantity, "unit_price": q["unit_price"], "quote": q})
        else:
            p = ci.product
            if not p.is_active:
                raise ValidationError(f"«{p.name}» больше не продаётся — удалите его из корзины", code="product_inactive")
            carts.assert_product_allowed(channel, p)
            lines.append({"key": ci.id, "type": "product", "product": p, "composition": None,
                          "quantity": ci.quantity, "unit_price": p.price})

    # --- контакты
    customer_data = data.get("customer") or {}
    name = (customer_data.get("name") or "").strip()
    if not name:
        raise ValidationError("Укажите имя", code="name_required", details={"field": "name"})
    name = v.person_name(name, "name", "Имя")
    phone = normalize_phone(customer_data.get("phone"))
    if not phone:
        raise ValidationError("Укажите корректный телефон", code="invalid_phone", details={"field": "phone"})
    customer_email = v.email(customer_data.get("email"), "email", "E-mail")
    recipient = data.get("recipient") or {}
    recipient_name = v.person_name(recipient.get("name"), "recipient_name", "Имя получателя", required=False)
    recipient_phone = normalize_phone(recipient.get("phone")) if recipient.get("phone") else ""
    if recipient.get("phone") and not recipient_phone:
        raise ValidationError("Некорректный телефон получателя", code="invalid_phone",
                              details={"field": "recipient_phone"})
    comment = v.text(data.get("comment"), "comment", "Комментарий", max_len=1000, multiline=True)
    card_text = v.text(data.get("card_text"), "card_text", "Текст открытки", max_len=300, multiline=True)

    # --- получение
    fulfillment = data.get("fulfillment")
    if fulfillment not in (Order.Fulfillment.DELIVERY, Order.Fulfillment.PICKUP):
        raise ValidationError("Выберите доставку или самовывоз", code="fulfillment_required")
    the_date = _parse_date(data.get("date"))
    slot = delivery_services.validate_slot(the_date, data.get("slot_id"), fulfillment, lock=True)
    zone, place = None, None
    delivery_data = data.get("delivery") or {}
    ask_recipient = surprise = anonymous = False
    if fulfillment == Order.Fulfillment.DELIVERY:
        ask_recipient = bool(delivery_data.get("ask_recipient"))
        surprise, anonymous = bool(delivery_data.get("surprise")), bool(delivery_data.get("anonymous"))
        if ask_recipient:
            if not recipient_phone:
                raise ValidationError("Чтобы узнать адрес, укажите телефон получателя", code="recipient_phone_required",
                                      details={"field": "recipient_phone"})
            if surprise:
                raise ValidationError("Адрес узнаём звонком получателю, поэтому сюрприз без звонка выбрать нельзя",
                                      code="surprise_needs_address", details={"field": "surprise"})
            place = delivery_services.resolve_unknown_address(delivery_data)
        else:
            place = delivery_services.resolve_address(delivery_data, require_coords=channel == "web")
        zone = place["zone"]
    photo_before = bool(data.get("photo_before")) and fulfillment == Order.Fulfillment.DELIVERY

    has_custom = any(l["type"] == "custom_bouquet" for l in lines)
    online_ok = payment_registry.online_enabled()
    payment_method = data.get("payment_method") or (
        Order.PaymentMethod.ONLINE if online_ok else Order.PaymentMethod.ON_DELIVERY)
    if payment_method not in (Order.PaymentMethod.ONLINE, Order.PaymentMethod.ON_DELIVERY):
        raise ValidationError("Выберите способ оплаты", code="payment_method_required")
    if payment_method == Order.PaymentMethod.ONLINE and not online_ok:
        raise ValidationError("Онлайн-оплата пока не подключена — выберите оплату при получении",
                              code="online_payment_unavailable", details={"field": "payment_method"})
    if payment_method == Order.PaymentMethod.ON_DELIVERY and online_ok:
        # Без онлайн-кассы оплата при получении — единственный способ, поэтому ограничения ниже не действуют.
        if has_custom:
            raise ValidationError("Индивидуальный букет оплачивается только онлайн", code="online_payment_required")
        if not settings.allow_cash_on_delivery:
            raise ValidationError("Сейчас доступна только онлайн-оплата", code="online_payment_required")
    _check_pending_limit(phone, signed_in)

    is_preorder = the_date > local_today() + timedelta(days=settings.preorder_threshold_days)
    items_total = sum(l["unit_price"] * l["quantity"] for l in lines)
    delivery_cost = zone.cost_for(items_total) if zone else 0

    if signed_in is not None:
        customer = _update_signed_in(signed_in, name, phone, customer_email)
    else:
        customer = find_or_create_customer(name, phone, customer_email, preferred=cart.customer)
    order = Order.objects.create(
        idempotency_key=key, source=channel, customer=customer, contact_name=name[:160], contact_phone=phone,
        contact_email=customer_email, recipient_name=recipient_name,
        recipient_phone=recipient_phone or "", items_total=items_total, delivery_cost=delivery_cost,
        total=items_total + delivery_cost, payment_method=payment_method, fulfillment=fulfillment,
        pickup_point=f"{settings.address}" if fulfillment == Order.Fulfillment.PICKUP else "",
        fulfillment_date=the_date, slot=slot, time_from=slot.start_time, time_to=slot.end_time,
        comment=comment, card_text=card_text, photo_before=photo_before,
        status=S.NEW, is_preorder=is_preorder, requires_confirmation=has_custom or is_preorder or ask_recipient,
    )
    order.number = str(10000 + order.pk)

    # --- резервирование (предзаказы на дальние даты не резервируют физический остаток)
    if is_preorder:
        plans, planned, balances = {l["key"]: {"preorder": l["quantity"]} for l in lines}, [], {}
    else:
        plans, planned, balances = reservations.plan(lines)

    item_by_key, snapshot_items = {}, []
    for l in lines:
        p = l["product"]
        oi = OrderItem.objects.create(
            order=order, item_type=l["type"], product=p, inventory_item=p.inventory_item if p else None,
            name=p.name if p else "Индивидуальный букет", sku=p.inventory_item.sku if p else "CUSTOM",
            product_type=p.type if p else "custom_bouquet", unit_price=l["unit_price"], quantity=l["quantity"],
            line_total=l["unit_price"] * l["quantity"],
            composition=({**l["composition"], "lines": l["quote"]["lines"], "florist_fee": l["quote"]["florist_fee"]}
                         if l["type"] == "custom_bouquet" else None),
            fulfillment_plan=plans[l["key"]],
        )
        item_by_key[l["key"]] = oi
        snapshot_items.append({"name": oi.name, "sku": oi.sku, "type": oi.product_type, "unit_price": oi.unit_price,
                               "quantity": oi.quantity, "line_total": oi.line_total, "composition": oi.composition})
    if planned:
        reservations.apply(order, planned, balances, item_by_key)

    order.snapshot = {
        "currency": "RUB", "captured_at": timezone.now().isoformat(), "items": snapshot_items,
        "items_total": items_total, "delivery_cost": delivery_cost, "total": order.total,
        "zone": zone.name if zone else None, "florist_fee": settings.florist_fee,
        "address_verified": place["verified"] if place else None,
    }
    order.save(update_fields=["number", "snapshot"])

    if fulfillment == Order.Fulfillment.DELIVERY:
        Delivery.objects.create(
            order=order, zone=zone, address=place["address"], lat=place["lat"], lon=place["lon"],
            address_verified=place["verified"], ask_recipient=ask_recipient, surprise=surprise, anonymous=anonymous,
            apartment=("" if ask_recipient else (delivery_data.get("apartment") or ""))[:20],
            entrance=("" if ask_recipient else (delivery_data.get("entrance") or ""))[:20],
            floor=("" if ask_recipient else (delivery_data.get("floor") or ""))[:20], date=the_date, slot=slot,
        )
    log_event(order, "created", f"Заказ создан ({Order.Source(channel).label})", actor_label=actor_label,
              to_status=S.NEW, total=order.total, preorder=is_preorder)
    if place and place["note"]:
        log_event(order, "note", place["note"], actor_label="система")

    # --- маршрутизация статуса
    if order.requires_confirmation:
        why = ("адрес нужно узнать у получателя" if ask_recipient else
               "индивидуальный букет" if has_custom else "предзаказ")
        _do_transition(order, S.AWAITING_CONFIRMATION, actor_label="система", notify=False,
                       comment=f"Требуется подтверждение флориста: {why}")
    elif payment_method == Order.PaymentMethod.ONLINE:
        _do_transition(order, S.AWAITING_PAYMENT, actor_label="система", notify=False)
    else:
        _set_hold(order, _hold_minutes_for(order, settings))
        order.save(update_fields=["reservation_expires_at"])

    carts.clear(cart)
    _notify(order, "created")
    return order


# ---------------------------------------------------------------- переходы статусов

def _check_role(order, frm, to, user):
    if user is None:
        return
    if user.role == User.Role.COURIER:
        delivery = getattr(order, "delivery", None)
        if (frm, to) not in COURIER_TRANSITIONS or not delivery or delivery.courier_id != user.id:
            raise PermissionDenied("Курьер может менять статус только назначенных ему доставок")


def _guards(order, to):
    PM = Order.PaymentMethod
    if to == S.AWAITING_PAYMENT and order.payment_method != PM.ONLINE:
        raise DomainError("Ожидание оплаты возможно только для онлайн-оплаты", code="invalid_transition", http_status=409)
    if to == S.CONFIRMED and order.payment_method == PM.ONLINE and order.payment_status != PS.PAID:
        raise DomainError("Онлайн-заказ подтверждается после успешной оплаты", code="payment_required", http_status=409)
    if to == S.HANDED_TO_COURIER:
        if order.fulfillment != Order.Fulfillment.DELIVERY:
            raise DomainError("Заказ оформлен на самовывоз", code="invalid_transition", http_status=409)
        if not getattr(order, "delivery", None) or not order.delivery.courier_id:
            raise DomainError("Сначала назначьте курьера", code="courier_required", http_status=409)
    delivery = getattr(order, "delivery", None) if order.fulfillment == Order.Fulfillment.DELIVERY else None
    if delivery and delivery.address_pending and to in (S.AWAITING_PAYMENT, S.CONFIRMED, S.ASSEMBLING, S.READY,
                                                         S.HANDED_TO_COURIER):
        raise DomainError("Сначала позвоните получателю и впишите адрес доставки в заказ", code="address_pending",
                          http_status=409)
    if to == S.HANDED_TO_COURIER and order.photo_before and not order.photos.exists():
        raise DomainError("Покупатель просил фото букета перед отправкой — флорист загружает его в карточке заказа",
                          code="photo_required", http_status=409)
    if to == S.AWAITING_PICKUP and order.fulfillment != Order.Fulfillment.PICKUP:
        raise DomainError("Заказ оформлен на доставку", code="invalid_transition", http_status=409)
    if to == S.COMPLETED and order.payment_status != PS.PAID:
        raise DomainError("Нельзя завершить неоплаченный заказ", code="payment_required", http_status=409)


def _consume_for_ready(order, user):
    """Фактическое списание: резервы → движения. Для предзаказа сначала резервируем по текущему остатку."""
    if not order.reservations.exists():  # предзаказ: физический резерв не создавался
        lines = []
        for oi in order.items.select_related("product__inventory_item"):
            if oi.item_type == OrderItem.ItemType.CUSTOM_BOUQUET:
                lines.append({"key": oi.id, "type": "custom_bouquet", "product": None, "composition": oi.composition,
                              "quantity": oi.quantity})
            elif oi.product:
                lines.append({"key": oi.id, "type": "product", "product": oi.product, "composition": None,
                              "quantity": oi.quantity})
        try:
            _, planned, balances = reservations.plan(lines)
        except InsufficientStock as e:
            raise DomainError(f"Для сборки не хватает материалов: {e.message}. Оформите поставку.",
                              code="insufficient_stock", http_status=409)
        reservations.apply(order, planned, balances, {oi.id: oi for oi in order.items.all()})
    reservations.consume(order, user=user)


def _record_cash_payment(order):
    from apps.payments.models import Payment

    Payment.objects.create(order=order, provider="cash_on_delivery", amount=order.total, status=Payment.Status.PAID,
                           paid_at=timezone.now())
    order.payment_status = PS.PAID


def _do_transition(order, to, *, user=None, actor_label="", comment="", notify=True):
    """Переход статуса для уже заблокированного заказа (внутри транзакции)."""
    settings = ShopSettings.load()
    frm = order.status
    if to not in TRANSITIONS[S(frm)]:
        raise DomainError(f"Нельзя перевести заказ из «{label(frm)}» в «{label(to)}»", code="invalid_transition",
                          http_status=409)
    _check_role(order, frm, to, user)
    _guards(order, to)
    extra = {}
    if to == S.CANCELLED:
        if frm in PRE_FULFILLMENT:
            reservations.release(order, status=StockReservation.Status.RELEASED)
        else:
            returned, lost = reservations.return_finished(order, user=user)
            if lost:
                extra["warning"] = "Индивидуальный букет уже собран — его материалы не возвращаются на склад. При необходимости оформите списание или продайте букет в магазине"
        if getattr(order, "delivery", None):
            order.delivery.status = Delivery.Status.CANCELLED
            order.delivery.save(update_fields=["status"])
        order.cancel_reason = (comment or "")[:255]
        order.reservation_expires_at = None
    order.status = to
    if to in HOLD_STATUSES:
        _set_hold(order, _hold_minutes_for(order, settings))
    elif to != S.CANCELLED:
        if order.reservation_expires_at:
            _set_hold(order, None)
    if to == S.CONFIRMED:
        order.confirmed_at = timezone.now()
    if to == S.READY:
        _consume_for_ready(order, user)
    if to == S.HANDED_TO_COURIER:
        order.delivery.status = Delivery.Status.IN_TRANSIT
        order.delivery.save(update_fields=["status"])
    if to == S.DELIVERED:
        if order.payment_method == Order.PaymentMethod.ON_DELIVERY and order.payment_status != PS.PAID:
            _record_cash_payment(order)
        if getattr(order, "delivery", None):
            order.delivery.status = Delivery.Status.DELIVERED
            order.delivery.delivered_at = timezone.now()
            order.delivery.save(update_fields=["status", "delivered_at"])
    order.save()
    message = " · ".join(x for x in (comment, extra.get("warning", "")) if x)
    log_event(order, "status", message, actor=user, actor_label=actor_label,
              from_status=frm, to_status=to, **extra)

    from apps.payments import services as payments

    if to == S.AWAITING_PAYMENT:
        payments.start_payment(order)
    if to == S.CANCELLED:
        payments.on_order_cancelled(order)
    if notify:
        _notify(order, "status", from_status=frm)
    return order


def transition(order_id, to, *, user=None, actor_label="", comment=""):
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=order_id)
        except Order.DoesNotExist:
            raise NotFound("Заказ не найден")
        return _do_transition(order, to, user=user, actor_label=actor_label, comment=comment)


def staff_confirm(order_id, user):
    """Подтверждение сотрудником: звонок по заказу с оплатой при получении или проверка флористом."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status not in (S.NEW, S.AWAITING_CONFIRMATION):
            raise DomainError("Заказ уже подтверждён или закрыт", code="invalid_transition", http_status=409)
        target = S.AWAITING_PAYMENT if order.payment_method == Order.PaymentMethod.ONLINE and order.payment_status != PS.PAID else S.CONFIRMED
        comment = "Подтверждено флористом" if order.status == S.AWAITING_CONFIRMATION else "Заказ подтверждён"
        return _do_transition(order, target, user=user, comment=comment)


ADDRESS_EDITABLE = {S.NEW, S.AWAITING_CONFIRMATION, S.AWAITING_PAYMENT, S.CONFIRMED, S.ASSEMBLING, S.READY}
MAX_ORDER_PHOTOS = 6


def set_delivery_address(order_id, user, data):
    """Флорист вписывает адрес, который назвал получатель (или исправляет адрес после звонка).

    Цена доставки не пересчитывается — она уже показана покупателю. Если адрес попал в другую зону,
    в журнал пишется подсказка, чтобы флорист согласовал доплату."""
    address = " ".join(str(data.get("address") or "").split())[:255]
    if not address or address.startswith(ASK_RECIPIENT_ADDRESS):
        raise ValidationError("Впишите адрес: улицу и номер дома", code="address_required", details={"field": "address"})
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        delivery = getattr(order, "delivery", None)
        if order.fulfillment != Order.Fulfillment.DELIVERY or not delivery:
            raise DomainError("Заказ оформлен на самовывоз", code="invalid_transition", http_status=409)
        if order.status not in ADDRESS_EDITABLE:
            raise DomainError("Адрес меняют до передачи курьеру", code="invalid_transition", http_status=409)
        try:
            rows = geo.geocode(address, 3)
        except geo.GeocoderUnavailable:
            rows = None
        best = next((r for r in rows or [] if r.house), None)
        note = ""
        if best:
            delivery.lat, delivery.lon, delivery.address_verified = best.lat, best.lon, True
            found = geo.find_zone(best.lat, best.lon)
            if not found:
                note = "Адрес вне зон доставки — уточните у покупателя, сможем ли довезти"
            elif delivery.zone_id and found.id != delivery.zone_id:
                note = (f"Адрес в зоне «{found.name}» ({rub(found.cost_for(order.items_total))}), а покупатель выбрал "
                        f"«{delivery.zone.name}» ({rub(order.delivery_cost)}) — согласуйте доплату")
        else:
            delivery.lat = delivery.lon = None
            delivery.address_verified = False
            note = "Адрес не найден геокодером — проверьте его по карте" if rows is not None else \
                "Геокодер недоступен — адрес сохранён без проверки"
        delivery.address = address
        for f in ("apartment", "entrance", "floor"):
            setattr(delivery, f, " ".join(str(data.get(f) or "").split())[:20])
        delivery.save(update_fields=["address", "apartment", "entrance", "floor", "lat", "lon", "address_verified"])
        log_event(order, "address", f"Адрес доставки: {address}", actor=user)
        if note:
            log_event(order, "note", note, actor_label="система")
        return order, note


def add_photo(order_id, user, image):
    """Фото собранного букета. Первое фото отправляем покупателю в мессенджер — он видит его на странице заказа."""
    from .models import OrderPhoto

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == S.CANCELLED:
            raise DomainError("Заказ отменён", code="invalid_transition", http_status=409)
        if order.photos.count() >= MAX_ORDER_PHOTOS:
            raise ValidationError(f"Не больше {MAX_ORDER_PHOTOS} фото к заказу", code="too_many_photos")
        first = not order.photos.exists()
        photo = OrderPhoto.objects.create(order=order, image=image, uploaded_by=user)
        log_event(order, "photo", "Загружено фото букета", actor=user)
    if first:
        from apps.notifications.services import order_photo

        order_photo(order)
    return photo


def delete_photo(photo_id, user):
    from .models import OrderPhoto

    photo = OrderPhoto.objects.select_related("order").filter(pk=photo_id).first()
    if not photo:
        raise NotFound("Фото не найдено")
    order, name = photo.order, photo.image.name
    photo.delete()
    if name:
        photo.image.storage.delete(name)
    log_event(order, "photo", "Фото букета удалено", actor=user)
    return order


def cancel(order_id, *, user=None, actor_label="", reason=""):
    return transition(order_id, S.CANCELLED, user=user, actor_label=actor_label, comment=reason or "Отменён")


def expire_overdue_orders(now=None):
    """Отменяет заказы с истёкшим резервом (неоплаченные онлайн, неподтверждённые). Подтверждённые — не трогает."""
    now = now or timezone.now()
    ids = list(Order.objects.filter(status__in=list(HOLD_STATUSES), reservation_expires_at__lt=now)
               .values_list("id", flat=True)[:200])
    expired = []
    from apps.payments import services as payments

    for oid in ids:
        pending = Order.objects.filter(pk=oid, status=S.AWAITING_PAYMENT).first()
        if pending:  # перед отменой сверяем оплату с кассой: уведомление могло не дойти
            try:
                payments.sync_pending(pending, min_interval=0)
            except Exception:  # noqa: BLE001 — сверка не должна мешать снятию резерва
                pass
        with transaction.atomic():
            order = Order.objects.select_for_update(skip_locked=True).filter(pk=oid).first()
            if not order or order.status not in HOLD_STATUSES or not order.reservation_expires_at \
                    or order.reservation_expires_at >= now:
                continue
            frm = order.status
            reservations.release(order, status=StockReservation.Status.EXPIRED)
            order.status = S.CANCELLED
            order.cancel_reason = "Истёк срок резерва"
            order.reservation_expires_at = None
            if getattr(order, "delivery", None):
                order.delivery.status = Delivery.Status.CANCELLED
                order.delivery.save(update_fields=["status"])
            order.save()
            log_event(order, "status", "Истёк срок резерва — товар возвращён в продажу", actor_label="система",
                      from_status=frm, to_status=S.CANCELLED)
            payments.on_order_cancelled(order)
            _notify(order, "status", from_status=frm)
            expired.append(order.pk)
    return expired


def assign_courier(order_id, courier_id, user):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        delivery = getattr(order, "delivery", None)
        if not delivery:
            raise ValidationError("У заказа нет доставки")
        if order.status in (S.DELIVERED, S.COMPLETED, S.CANCELLED):
            raise DomainError("Заказ уже закрыт", code="invalid_transition", http_status=409)
        courier = None
        if courier_id:
            courier = User.objects.filter(pk=courier_id, role=User.Role.COURIER, is_active=True).first()
            if not courier:
                raise ValidationError("Курьер не найден")
        delivery.courier = courier
        delivery.assigned_at = timezone.now() if courier else None
        if delivery.status in (Delivery.Status.PENDING, Delivery.Status.ASSIGNED):
            delivery.status = Delivery.Status.ASSIGNED if courier else Delivery.Status.PENDING
        delivery.save()
        log_event(order, "courier", f"Курьер: {courier.display_name if courier else 'снят'}", actor=user)
        return order


def add_note(order_id, user, text):
    order = Order.objects.get(pk=order_id)
    if not (text or "").strip():
        raise ValidationError("Пустой комментарий")
    return log_event(order, "note", text.strip()[:2000], actor=user)


# ---------------------------------------------------------------- продажа в магазине

@transaction.atomic
def store_sale(lines, payment_kind, user, customer_phone="", customer_name=""):
    from apps.payments.models import Payment

    if payment_kind not in ("cash", "card"):
        raise ValidationError("Выберите способ оплаты: наличные или карта")
    if not lines:
        raise ValidationError("Добавьте товары")
    qty_by_product = {}
    for l in lines:
        q = int(l.get("quantity") or 0)
        if q <= 0:
            raise ValidationError("Количество должно быть больше нуля")
        qty_by_product[int(l["product_id"])] = qty_by_product.get(int(l["product_id"]), 0) + q
    products = {p.id: p for p in Product.objects.select_related("inventory_item").filter(pk__in=qty_by_product, is_active=True)}
    if len(products) != len(qty_by_product):
        raise ValidationError("Некоторые товары не найдены или неактивны")
    balances = lock_balances([p.inventory_item_id for p in products.values()])
    for pid, q in qty_by_product.items():
        bal = balances[products[pid].inventory_item_id]
        if bal.available < q:
            hint = " Сначала соберите букеты по рецептуре." if products[pid].type == Product.Type.BOUQUET else ""
            raise DomainError(f"«{products[pid].name}»: свободно {bal.available}, нужно {q}.{hint}",
                              code="insufficient_stock", http_status=409)
    customer = None
    if customer_phone:
        customer = find_or_create_customer(customer_name or "Покупатель в магазине", customer_phone)
    total = sum(products[pid].price * q for pid, q in qty_by_product.items())
    order = Order.objects.create(
        source=Order.Source.STORE, customer=customer, contact_name=customer_name or "Покупатель в магазине",
        contact_phone=customer.phone if customer else "", items_total=total, delivery_cost=0, total=total,
        payment_method=Order.PaymentMethod.IN_STORE, payment_status=PS.PAID, fulfillment=Order.Fulfillment.IN_STORE,
        status=S.COMPLETED, confirmed_at=timezone.now(), fulfillment_date=local_today(), created_by=user,
    )
    order.number = str(10000 + order.pk)
    items = []
    for pid, q in qty_by_product.items():
        p = products[pid]
        OrderItem.objects.create(order=order, item_type="product", product=p, inventory_item=p.inventory_item,
                                 name=p.name, sku=p.inventory_item.sku, product_type=p.type, unit_price=p.price,
                                 quantity=q, line_total=p.price * q, fulfillment_plan={"stock": q})
        consume_free(balances[p.inventory_item_id], q, StockMovement.Type.STORE_SALE, order=order, user=user,
                     reason=f"Продажа в магазине №{order.number}")
        items.append({"name": p.name, "quantity": q, "unit_price": p.price, "line_total": p.price * q})
    order.snapshot = {"currency": "RUB", "captured_at": timezone.now().isoformat(), "items": items,
                      "items_total": total, "delivery_cost": 0, "total": total}
    order.save(update_fields=["number", "snapshot"])
    Payment.objects.create(order=order, provider=f"store_{payment_kind}", amount=total, status=Payment.Status.PAID,
                           paid_at=timezone.now())
    log_event(order, "created", f"Продажа в магазине ({'наличные' if payment_kind == 'cash' else 'карта'})",
              actor=user, to_status=S.COMPLETED)
    return order
