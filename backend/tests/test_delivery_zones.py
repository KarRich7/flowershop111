"""Зоны доставки на карте, проверка адреса, бесплатная доставка от 1 500 ₽ и правила оплаты."""
import pytest

from apps.carts import services as carts
from apps.core.errors import ValidationError
from apps.core.models import ShopSettings
from apps.delivery import geo
from apps.delivery.models import DeliveryZone
from apps.orders import services as orders
from apps.orders.models import Order

from .conftest import IN_ZONE, OUT_OF_ZONE, staff_client

pytestmark = pytest.mark.django_db


def _cart(shop, product, qty=1):
    cart = carts.create_cart("web")
    carts.add_product(cart, product.id, qty)
    return cart


def _delivery(address="Кондратово, Красавинская улица, 8", point=IN_ZONE, token=None, **extra):
    d = {"address": address, "lat": point[0], "lon": point[1], **extra}
    if token:
        d["address_token"] = token
    return d


def test_point_in_polygon_and_zone_lookup(shop):
    assert geo.find_zone(*IN_ZONE) == shop.zone
    assert geo.find_zone(*OUT_OF_ZONE) is None
    DeliveryZone.objects.create(name="Неактивная", price=1, is_active=False, polygons=[[[56, 60], [56, 61], [57, 61]]])
    assert geo.find_zone(*OUT_OF_ZONE) is None


def test_web_delivery_requires_point_on_map(shop):
    b = shop.bouquet(assembled=1)
    data = shop.order_data()
    data["delivery"] = {"zone_id": shop.zone.id, "address": "Кондратово, Красавинская улица, 8"}  # старый формат без координат
    with pytest.raises(ValidationError) as e:
        orders.place_order(_cart(shop, b), data)
    assert e.value.code == "location_required"


def test_delivery_outside_zones_is_rejected(shop):
    b = shop.bouquet(assembled=1)
    data = shop.order_data()
    data["delivery"] = _delivery("Краснокамск, улица Ленина, 1", OUT_OF_ZONE)
    with pytest.raises(ValidationError) as e:
        orders.place_order(_cart(shop, b), data)
    assert e.value.code == "address_out_of_zone"
    assert not Order.objects.exists()


def test_signed_address_is_verified_and_zone_set_by_server(shop):
    other = DeliveryZone.objects.create(name="Пригород", price=90000, polygons=[[[57, 60], [57, 61], [58, 61]]])
    b = shop.bouquet(assembled=1)
    data = shop.order_data()
    addr = "Кондратово, Красавинская улица, 8"
    data["delivery"] = {**_delivery(addr, token=geo.sign(addr, *IN_ZONE)), "zone_id": other.id}  # зону клиента игнорируем
    order = orders.place_order(_cart(shop, b), data)
    assert order.delivery.zone == shop.zone and order.delivery.address_verified
    assert (order.delivery.lat, order.delivery.lon) == IN_ZONE
    assert order.snapshot["address_verified"] is True


def test_forged_token_triggers_geocoder_check(shop, monkeypatch, settings):
    settings.GEOCODER_PROVIDER = "nominatim"
    far = geo.GeoResult("Кондратово, Красавинская улица, 8", "", IN_ZONE[0] + 0.05, IN_ZONE[1], True, "house")
    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [far])
    b = shop.bouquet(assembled=1)
    data = shop.order_data()
    data["delivery"] = _delivery(token="forged")
    with pytest.raises(ValidationError) as e:
        orders.place_order(_cart(shop, b), data)
    assert e.value.code == "address_mismatch"

    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [])
    with pytest.raises(ValidationError) as e:
        orders.place_order(_cart(shop, b), data)
    assert e.value.code == "address_not_found"

    near = geo.GeoResult("Кондратово, Красавинская улица, 8", "", IN_ZONE[0] + 0.001, IN_ZONE[1], True, "house")
    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [near])
    order = orders.place_order(_cart(shop, b), data)
    assert order.delivery.address_verified


def test_geocoder_unavailable_keeps_zone_check_and_logs_note(shop):
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1))  # GEOCODER_PROVIDER=off в тестах
    assert order.delivery.zone == shop.zone and not order.delivery.address_verified
    assert order.events.filter(event_type="note", message__icontains="не проверен").exists()


def test_free_delivery_from_1500(shop):
    shop.zone.free_from = 150000
    shop.zone.save()
    cheap = shop.bouquet("cheap", assembled=1, price=140000)
    rich = shop.bouquet("rich", assembled=1, price=150000)
    assert shop.place((cheap, 1)).delivery_cost == 30000
    assert shop.place((rich, 1)).delivery_cost == 0


def test_only_online_payment_by_default(shop):
    s = ShopSettings.load()
    s.allow_cash_on_delivery = False
    s.save()
    b = shop.bouquet(assembled=2)
    with pytest.raises(ValidationError) as e:
        shop.place((b, 1), payment="on_delivery")
    assert e.value.code == "online_payment_required"
    order = shop.place((b, 1), payment=None)  # способ не передан — онлайн
    assert order.payment_method == "online" and order.status == "awaiting_payment"


def test_custom_bouquet_is_online_only(shop):
    with pytest.raises(ValidationError) as e:
        shop.place(custom=shop.custom_composition(), payment="on_delivery")
    assert e.value.code == "online_payment_required"


def test_public_zones_and_settings_expose_map_data(shop, web):
    shop.zone.free_from = 150000
    shop.zone.save()
    z = web.get("/api/v1/delivery/zones").json()[0]
    assert z["polygons"] and z["free_from"] == 150000
    s = web.get("/api/v1/settings/public").json()
    assert s["free_delivery_from"] == 150000 and s["allow_cash_on_delivery"] is True
    assert "yandex_api_key" in s["maps"]


def test_geocode_and_reverse_api(shop, web, monkeypatch):
    res = geo.GeoResult("Кондратово, Красавинская улица, 8", "Пермский край, Кондратово, Красавинская улица, 8", *IN_ZONE, True, "house")
    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [res])
    r = web.get("/api/v1/delivery/geocode", {"q": "Красавинская 8"})
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert row["zone"]["id"] == shop.zone.id and geo.verify(row["address"], row["lat"], row["lon"], row["token"])
    monkeypatch.setattr(geo, "reverse", lambda lat, lon: geo.GeoResult("Краснокамск, улица Ленина, 1", "", lat, lon, True))
    r = web.get("/api/v1/delivery/reverse", {"lat": OUT_OF_ZONE[0], "lon": OUT_OF_ZONE[1]})
    assert r.status_code == 200 and r.json()["zone"] is None and r.json()["result"]["zone"] is None
    # геокодер выключен — понятная ошибка 503
    monkeypatch.undo()
    assert web.get("/api/v1/delivery/geocode", {"q": "Красавинская 8"}).status_code == 503


def test_owner_edits_zone_polygon(shop, staff):
    owner = staff_client("owner")
    r = owner.patch(f"/api/v1/admin/delivery-zones/{shop.zone.id}", {"polygons": [[[57.9, 56.1], [58.0, 56.1]]]},
                    format="json")
    assert r.status_code == 400
    poly = [[56.7, 60.4], [56.7, 60.8], [56.95, 60.8], [56.95, 60.4]]
    r = owner.patch(f"/api/v1/admin/delivery-zones/{shop.zone.id}", {"polygons": [poly], "free_from": 150000},
                    format="json")
    assert r.status_code == 200, r.content
    shop.zone.refresh_from_db()
    assert shop.zone.polygons == [poly] and shop.zone.free_from == 150000
    assert staff_client("florist").patch(f"/api/v1/admin/delivery-zones/{shop.zone.id}", {"price": 1},
                                         format="json").status_code == 403


def test_rejected_yandex_key_falls_back_to_nominatim(settings, monkeypatch):
    from django.core.cache import cache

    settings.GEOCODER_PROVIDER, settings.YANDEX_GEOCODER_API_KEY = "auto", "bad-key"
    cache.delete(geo.YANDEX_DOWN_KEY)
    calls = []

    def yandex(q, limit):
        calls.append("yandex")
        raise geo.GeocoderUnavailable("Сервис проверки адресов временно недоступен", "HTTP 403: Invalid api key")

    def nominatim(q, limit):
        calls.append("nominatim")
        return [geo.GeoResult("Кондратово, Красавинская улица, 8", "Пермский край, Кондратово, Красавинская улица, 8", 57.9884, 56.1204, True)]

    monkeypatch.setattr(geo, "_yandex_search", yandex)
    monkeypatch.setattr(geo, "_nominatim_search", nominatim)
    try:
        rows = geo.geocode("Красавинская 8 (fallback-1)")
        assert rows and rows[0].house and calls[0] == "yandex" and "nominatim" in calls
        assert geo.provider() == "nominatim"  # Яндекс отключён на 10 минут — без лишних задержек
        calls.clear()
        geo.geocode("Красавинская 8 (fallback-2)")
        assert "yandex" not in calls
        # явно выбранный Яндекс не подменяется — ошибка видна сразу
        settings.GEOCODER_PROVIDER = "yandex"
        cache.delete(geo.YANDEX_DOWN_KEY)
        with pytest.raises(geo.GeocoderUnavailable) as e:
            geo.geocode("Красавинская 8 (fallback-3)")
        assert str(e.value) == "Сервис проверки адресов временно недоступен"
    finally:
        cache.delete(geo.YANDEX_DOWN_KEY)


def test_migration_replaces_old_ekaterinburg_demo_zones(shop):
    """Миграция 0006: старые демо-зоны → зоны Кондратово/Перми; зона с доставками уходит в архив, демо-адреса переезжают."""
    import importlib

    from apps.customers.models import Customer
    from apps.delivery.models import Delivery, DeliveryZone

    mig = importlib.import_module("apps.delivery.migrations.0006_kondratovo_demo_zones")
    DeliveryZone.objects.filter(pk=shop.zone.pk).update(name="Центр (Ленинский, Октябрьский)")
    unused = DeliveryZone.objects.create(name="Кировский район", price=40000)
    b = shop.bouquet(assembled=1)
    order = shop.place((b, 1), payment="on_delivery")
    Customer.objects.filter(pk=order.customer_id).update(is_demo=True)
    Delivery.objects.filter(order=order).update(address="Екатеринбург, ул. Малышева, 51")

    mig.replace_zones(DeliveryZone, Delivery)
    mig.remap_demo_addresses(DeliveryZone, Delivery)

    assert not DeliveryZone.objects.filter(pk=unused.pk).exists()
    old = DeliveryZone.objects.get(pk=shop.zone.pk)
    assert old.is_archived and not old.is_active  # история заказа не потеряна
    names = list(DeliveryZone.objects.filter(is_archived=False).order_by("sort_order").values_list("name", flat=True))
    assert names[0].startswith("Кондратово") and any(n.startswith("Пермь") for n in names)
    d = Delivery.objects.get(order=order)
    assert d.address.startswith("Кондратово") and d.zone.name.startswith("Кондратово")


def test_migration_keeps_owner_zones(shop):
    """Если владелец уже завёл свои зоны, миграция их не трогает."""
    import importlib

    from apps.delivery.models import Delivery, DeliveryZone

    mig = importlib.import_module("apps.delivery.migrations.0006_kondratovo_demo_zones")
    mig.replace_zones(DeliveryZone, Delivery)
    assert list(DeliveryZone.objects.values_list("name", flat=True)) == ["Центр"]


def test_maps_check_for_owner_only_and_hides_key(shop, staff, settings, monkeypatch):
    """Карточка «Карта и поиск адресов»: владелец видит, принят ли ключ; сам ключ наружу не отдаётся."""
    from apps.delivery import geo, maps_check

    from .conftest import staff_client

    key = "0123abcd-1111-2222-3333-444455556666"
    settings.YANDEX_MAPS_API_KEY = settings.YANDEX_GEOCODER_API_KEY = key
    settings.GEOCODER_PROVIDER = "auto"
    monkeypatch.setattr(maps_check, "_check_map", lambda k, origin: {"ok": True, "message": "Ключ принят"})

    def forbidden(*a, **kw):
        raise geo.GeocoderUnavailable("недоступен", 'HTTP 403: {"message":"Invalid api key"}')

    monkeypatch.setattr(geo, "_yandex_request", forbidden)
    monkeypatch.setattr(geo, "_nominatim_search", lambda q, limit: [object()])
    assert staff_client("florist").get("/api/v1/admin/maps/check").status_code == 403
    r = staff_client("owner").get("/api/v1/admin/maps/check")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["maps"]["ok"] is True and body["geocoder"]["ok"] is False and "15 минут" in body["geocoder"]["hint"]
    assert body["active"] == "nominatim" and body["yandex_paused"] is True  # сайт работает через OpenStreetMap
    assert key not in r.content.decode()
