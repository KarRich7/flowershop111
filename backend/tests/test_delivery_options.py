"""Опции вручения, как у крупных цветочных сервисов: адрес узнаём у получателя, сюрприз, анонимно, фото до отправки."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.carts import services as carts
from apps.core.errors import ValidationError
from apps.delivery.models import ASK_RECIPIENT_ADDRESS
from apps.notifications.models import Notification
from apps.orders import services as orders
from apps.orders.models import Order

from .conftest import IN_ZONE, staff_client

S = Order.Status


def _photo():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 60, 90)).save(buf, "JPEG")
    return SimpleUploadedFile("bouquet.jpg", buf.getvalue(), content_type="image/jpeg")


def _place(shop, product, *, delivery, recipient_phone="", photo_before=False):
    cart = carts.create_cart("web")
    carts.add_product(cart, product.id, 1)
    data = shop.order_data(payment="on_delivery")
    data["delivery"] = delivery
    data["photo_before"] = photo_before
    if recipient_phone:
        data["recipient"] = {"name": "Мария", "phone": recipient_phone}
    return orders.place_order(cart, data)


def _florist(staff):
    return staff_client("florist")


def test_unknown_address_is_asked_from_recipient(shop, staff, monkeypatch):
    """Покупатель не знает адрес: выбирает зону, флорист звонит получателю и вписывает адрес до подтверждения."""
    b = shop.bouquet(assembled=1)
    o = _place(shop, b, delivery={"ask_recipient": True, "zone_id": shop.zone.id, "address_hint": "Кондратово"},
               recipient_phone="+7 912 000-11-22")
    assert o.status == S.AWAITING_CONFIRMATION and o.requires_confirmation
    assert o.delivery.address_pending and o.delivery.address.startswith(ASK_RECIPIENT_ADDRESS)
    assert o.delivery_cost == shop.zone.price  # цена — по выбранной зоне

    c = _florist(staff)
    r = c.post(f"/api/v1/admin/orders/{o.id}/confirm", format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "address_pending"

    from apps.delivery import geo

    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [geo.GeoResult(
        address="Кондратово, Красавинская улица, 8", full_address="Пермский край, Кондратово, Красавинская улица, 8",
        lat=IN_ZONE[0], lon=IN_ZONE[1], house=True)])
    r = c.patch(f"/api/v1/admin/orders/{o.id}/delivery",
                {"address": "Кондратово, Красавинская улица, 8", "apartment": "12"}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["delivery"]["address_pending"] is False and body["delivery"]["address_verified"] is True
    assert body["warning"] == ""
    assert c.post(f"/api/v1/admin/orders/{o.id}/confirm", format="json").status_code == 200
    o.refresh_from_db()
    assert o.status == S.CONFIRMED and o.delivery.apartment == "12"


def test_unknown_address_needs_recipient_phone_and_no_surprise(shop):
    b = shop.bouquet(assembled=1)

    with pytest.raises(ValidationError) as e:
        _place(shop, b, delivery={"ask_recipient": True, "zone_id": shop.zone.id})
    assert e.value.code == "recipient_phone_required"
    with pytest.raises(ValidationError) as e:
        _place(shop, b, delivery={"ask_recipient": True, "zone_id": shop.zone.id, "surprise": True},
               recipient_phone="+7 912 000-11-22")
    assert e.value.code == "surprise_needs_address"
    with pytest.raises(ValidationError) as e:
        _place(shop, b, delivery={"ask_recipient": True}, recipient_phone="+7 912 000-11-22")
    assert e.value.code == "zone_required"
    assert shop.balance(b.inventory_item).reserved == 0


def test_surprise_and_anonymous_are_visible_to_courier(shop, staff):
    b = shop.bouquet(assembled=1)
    o = _place(shop, b, delivery={"address": "Кондратово, Красавинская улица, 8", "lat": IN_ZONE[0], "lon": IN_ZONE[1],
                                  "surprise": True, "anonymous": True})
    assert o.delivery.surprise and o.delivery.anonymous and not o.delivery.address_pending
    orders.staff_confirm(o.id, staff["florist"])
    orders.assign_courier(o.id, staff["courier1"].id, staff["florist"])
    c = staff_client("courier1")
    row = c.get(f"/api/v1/admin/deliveries?date={o.fulfillment_date}").json()["deliveries"][0]
    assert row["surprise"] is True and row["anonymous"] is True
    card = c.get(f"/api/v1/admin/orders/{o.id}").json()
    assert card["delivery"]["surprise"] and card["delivery"]["anonymous"]


def test_photo_before_dispatch(shop, staff, settings, tmp_path):
    """Покупатель просил фото: без фото заказ не передать курьеру; первое фото уходит покупателю."""
    settings.MEDIA_ROOT = tmp_path
    b = shop.bouquet(assembled=1)
    o = _place(shop, b, delivery={"address": "Кондратово, Красавинская улица, 8", "lat": IN_ZONE[0], "lon": IN_ZONE[1]},
               photo_before=True)
    assert o.photo_before
    florist = staff["florist"]
    orders.staff_confirm(o.id, florist)
    orders.assign_courier(o.id, staff["courier1"].id, florist)
    orders.transition(o.id, S.ASSEMBLING, user=florist)
    orders.transition(o.id, S.READY, user=florist)
    c = _florist(staff)
    r = c.post(f"/api/v1/admin/orders/{o.id}/transition", {"status": "handed_to_courier"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "photo_required"

    r = c.post(f"/api/v1/admin/orders/{o.id}/photos", {"image": _photo()}, format="multipart")
    assert r.status_code == 201, r.content
    photos = r.json()["photos"]
    assert len(photos) == 1 and photos[0]["url"]
    assert Notification.objects.filter(order=o, kind="order_photo").exists()
    # покупатель видит фото по секретной ссылке
    public = c.get(f"/api/v1/orders/track/{o.public_token}").json()
    assert public["photo_before"] is True and len(public["photos"]) == 1

    r = c.post(f"/api/v1/admin/orders/{o.id}/transition", {"status": "handed_to_courier"}, format="json")
    assert r.status_code == 200, r.content

    # курьер не может загружать и удалять фото
    courier = staff_client("courier1")
    assert courier.post(f"/api/v1/admin/orders/{o.id}/photos", {"image": _photo()}, format="multipart").status_code == 403
    assert courier.delete(f"/api/v1/admin/order-photos/{photos[0]['id']}").status_code == 403
    r = c.delete(f"/api/v1/admin/order-photos/{photos[0]['id']}")
    assert r.status_code == 200 and r.json()["photos"] == []


def test_photo_upload_rejects_non_image(shop, staff, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    b = shop.bouquet(assembled=1)
    o = shop.place((b, 1), payment="on_delivery")
    junk = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
    r = _florist(staff).post(f"/api/v1/admin/orders/{o.id}/photos", {"image": junk}, format="multipart")
    assert r.status_code == 400


def test_address_can_not_be_changed_after_handover(shop, staff):
    b = shop.bouquet(assembled=1)
    o = shop.place((b, 1), payment="on_delivery")
    florist = staff["florist"]
    orders.staff_confirm(o.id, florist)
    orders.assign_courier(o.id, staff["courier1"].id, florist)
    for st in (S.ASSEMBLING, S.READY, S.HANDED_TO_COURIER):
        orders.transition(o.id, st, user=florist)
    r = _florist(staff).patch(f"/api/v1/admin/orders/{o.id}/delivery", {"address": "Пермь, ул. Ленина, 50"},
                              format="json")
    assert r.status_code == 409
