from datetime import timedelta

from django.conf import settings

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.errors import ValidationError
from apps.core.models import ShopSettings
from apps.core.utils import combine_local, local_today

from . import geo
from .models import Delivery, DeliverySlot, DeliveryZone


def booked_counts(date):
    rows = (
        Delivery.objects.filter(date=date)
        .exclude(order__status="cancelled")
        .values("slot_id")
        .annotate(n=Count("id"))
    )
    return {r["slot_id"]: r["n"] for r in rows}


def slots_for_date(date, fulfillment="delivery"):
    settings = ShopSettings.load()
    today = local_today()
    if date < today or date > today + timedelta(days=settings.max_order_days_ahead):
        return []
    now = timezone.now()
    lead = settings.pickup_ready_minutes if fulfillment == "pickup" else settings.min_lead_minutes
    booked = booked_counts(date) if fulfillment == "delivery" else {}
    out = []
    for slot in DeliverySlot.objects.filter(is_active=True):
        start = combine_local(date, slot.start_time)
        end = combine_local(date, slot.end_time)
        # слот доступен, если успеваем подготовить заказ хотя бы к концу интервала
        too_late = end - timedelta(minutes=30) < now + timedelta(minutes=lead)
        remaining = slot.capacity - booked.get(slot.id, 0) if fulfillment == "delivery" else None
        out.append({
            "id": slot.id, "label": slot.label, "start": slot.start_time.strftime("%H:%M"),
            "end": slot.end_time.strftime("%H:%M"), "remaining": remaining,
            "available": not too_late and (remaining is None or remaining > 0),
            "reason": "Время уже недоступно" if too_late else ("Интервал заполнен" if remaining == 0 else ""),
        })
    return out


def today_unavailable_note(fulfillment="delivery"):
    """Почему на сегодня оформить нельзя — понятным языком (для бота). None, если на сегодня есть свободное время."""
    settings = ShopSettings.load()
    today = local_today()
    slots = slots_for_date(today, fulfillment)
    if not slots or any(s["available"] for s in slots):
        return None
    what = "самовывоз" if fulfillment == "pickup" else "доставку"
    late = [s for s in slots if s["reason"] == "Время уже недоступно"]
    if len(late) == len(slots):
        lead = settings.pickup_ready_minutes if fulfillment == "pickup" else settings.min_lead_minutes
        last = max(combine_local(today, sl.end_time) for sl in DeliverySlot.objects.filter(is_active=True))
        cutoff = timezone.localtime(last - timedelta(minutes=30 + lead))
        return (f"На сегодня {what} уже не успеваем: заказ на сегодня нужно оформить до {cutoff:%H:%M} "
                f"(букету нужно время на сборку{'' if fulfillment == 'pickup' else ' и дорогу'}).")
    return f"На сегодня все интервалы на {what} уже заняты."


def validate_slot(date, slot_id, fulfillment, lock=True):
    """Проверка даты/интервала. Для доставки блокирует строку слота — лимит доставок не превысится при гонке."""
    qs = DeliverySlot.objects.filter(pk=slot_id, is_active=True)
    if lock:
        qs = qs.select_for_update()
    slot = qs.first()
    if not slot:
        raise ValidationError("Выберите доступный интервал времени", code="invalid_slot")
    info = next((s for s in slots_for_date(date, fulfillment) if s["id"] == slot.id), None)
    if not info:
        raise ValidationError("На эту дату заказ оформить нельзя", code="invalid_date")
    if not info["available"]:
        raise ValidationError(f"Интервал {slot.label} недоступен: {info['reason'].lower()}", code="slot_unavailable")
    return slot


def ready_time(order):
    settings = ShopSettings.load()
    earliest = timezone.localtime() + timedelta(minutes=settings.pickup_ready_minutes)
    if order.fulfillment_date and order.time_from:
        slot_start = combine_local(order.fulfillment_date, order.time_from)
        return max(slot_start, earliest) if order.fulfillment_date == local_today() else slot_start
    return earliest


def _coord(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if -180 <= v <= 180 else None


def resolve_unknown_address(delivery_data):
    """«Не знаю адрес — узнайте у получателя»: покупатель выбирает только зону (район / населённый пункт),
    флорист созванивается с получателем и вписывает адрес до передачи курьеру."""
    zone = DeliveryZone.objects.filter(pk=delivery_data.get("zone_id") or 0, is_active=True, is_archived=False).first()
    if not zone:
        raise ValidationError("Выберите, куда примерно везти: район или населённый пункт",
                              code="zone_required", details={"field": "zone_id"})
    hint = " ".join(str(delivery_data.get("address_hint") or "").split())[:120]
    from .models import ASK_RECIPIENT_ADDRESS

    address = f"{ASK_RECIPIENT_ADDRESS}{f' ({hint})' if hint else ''}"
    return {"zone": zone, "address": address, "lat": None, "lon": None, "verified": False,
            "note": "Адрес нужно узнать у получателя: позвоните ему, впишите адрес в заказ и после этого подтверждайте"}


def resolve_address(delivery_data, *, require_coords):
    """Проверяет адрес доставки и определяет зону по координатам (на сервере, данным клиента не доверяем).

    * Сайт передаёт адрес, координаты метки и подпись адреса из геокодера (address_token).
      Без подписи адрес повторно ищется геокодером и сверяется с точкой на карте.
    * Боты могут передать только текст адреса — сервер сам найдёт координаты.
    * Если геокодер недоступен, зона всё равно определяется по координатам; адрес помечается как непроверенный.
    """
    address = (delivery_data.get("address") or "").strip()[:255]
    if not address:
        raise ValidationError("Укажите адрес доставки", code="address_required")
    lat, lon = _coord(delivery_data.get("lat")), _coord(delivery_data.get("lon"))
    verified, note = False, ""
    if lat is None or lon is None:
        if require_coords:
            raise ValidationError("Отметьте адрес доставки на карте", code="location_required")
        try:
            rows = geo.geocode(address, 3)
        except geo.GeocoderUnavailable:
            rows = None
        if rows is None:  # запасной вариант для ботов: район выбран кнопкой, адрес проверит флорист
            zone = DeliveryZone.objects.filter(pk=delivery_data.get("zone_id") or 0, is_active=True).first()
            if not zone:
                raise ValidationError("Выберите район доставки", code="zone_required")
            return {"zone": zone, "address": address, "lat": None, "lon": None, "verified": False,
                    "note": "Адрес не проверен автоматически (геокодер недоступен) — уточните у покупателя"}
        best = next((r for r in rows if r.house), None)
        if not best:
            raise ValidationError("Не нашли такой адрес. Укажите улицу и номер дома", code="address_not_found")
        lat, lon, verified = best.lat, best.lon, True
    elif geo.verify(address, lat, lon, delivery_data.get("address_token")):
        verified = True
    else:
        try:
            rows = geo.geocode(address, 5)
        except geo.GeocoderUnavailable:
            rows, note = None, "Адрес не проверен геокодером (сервис был недоступен) — точка взята с карты"
        if rows is not None:
            houses = [r for r in rows if r.house]
            if not houses:
                raise ValidationError("Не нашли такой адрес. Проверьте улицу и номер дома", code="address_not_found")
            if min(geo.haversine_m(lat, lon, r.lat, r.lon) for r in houses) > settings.ADDRESS_MAX_DISTANCE_M:
                raise ValidationError("Адрес не совпадает с точкой на карте. Выберите адрес из подсказок или передвиньте метку",
                                      code="address_mismatch")
            verified = True
    zone = geo.find_zone(lat, lon)
    if not zone:
        raise ValidationError("По этому адресу мы пока не доставляем. Выберите другой адрес или самовывоз",
                              code="address_out_of_zone")
    return {"zone": zone, "address": address, "lat": lat, "lon": lon, "verified": verified, "note": note}
