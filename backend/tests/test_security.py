"""Защита: лимиты запросов, подбор паролей, смена пароля, загрузка файлов, спам-заказы, оплата, геокодер."""
import io
import json
from datetime import time
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.api.auth import is_internal_ip
from apps.carts import services as carts
from apps.core.errors import ValidationError
from apps.core.models import User
from apps.delivery import geo
from apps.delivery.models import DeliverySlot
from apps.delivery.services import today_unavailable_note
from apps.orders import services as orders
from apps.orders.models import Order
from apps.payments import services as payments
from apps.payments.models import Payment

from .conftest import make_user, staff_client

PUBLIC_IP = "93.184.216.34"  # обычный публичный адрес (диапазоны для документации Python считает частными)


def _client(ip=PUBLIC_IP):
    return APIClient(HTTP_X_FORWARDED_FOR=ip)


def _png(w=64, h=64, mode="RGB", exif=False):
    buf = io.BytesIO()
    img = Image.new(mode, (w, h), "red" if mode == "RGB" else 1)
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SpyCam"  # Make
        ex[0x8825] = {2: (57.0, 59.0, 0.0)}  # GPSInfo
        img.save(buf, "JPEG", exif=ex)
        return SimpleUploadedFile("photo.jpg", buf.getvalue(), content_type="image/jpeg")
    img.save(buf, "PNG")
    return SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png")


# ------------------------------------------------------------------ лимиты запросов

def test_internal_addresses_are_recognised():
    assert is_internal_ip("127.0.0.1") and is_internal_ip("172.18.0.5") and is_internal_ip("10.0.0.2")
    assert not is_internal_ip(PUBLIC_IP) and not is_internal_ip("garbage")


@pytest.mark.django_db
def test_order_lookup_is_rate_limited_per_ip(settings):
    settings.THROTTLE_INTERNAL_EXEMPT = False
    c = _client()
    codes = [c.post("/api/v1/orders/lookup", {"number": "1", "phone": "+79001112233"}, format="json").status_code
             for _ in range(11)]
    assert codes[:10] == [404] * 10 and codes[10] == 429
    # другой покупатель (другой IP) не страдает
    assert _client("151.101.1.69").post("/api/v1/orders/lookup", {"number": "1", "phone": "+79001112233"},
                                        format="json").status_code == 404


@pytest.mark.django_db
def test_spoofed_forwarded_for_does_not_break_login(staff):
    c = APIClient(HTTP_X_FORWARDED_FOR="<script>, not-an-ip")
    r = c.post("/api/v1/admin/auth/login", {"username": "owner", "password": "wrong"}, format="json")
    assert r.status_code == 400


# ------------------------------------------------------------------ вход сотрудников

@pytest.mark.django_db
def test_login_locks_after_repeated_failures(staff, settings):
    c = _client()
    for i in range(settings.LOGIN_MAX_FAILS):
        r = c.post("/api/v1/admin/auth/login", {"username": "owner", "password": f"bad-{i}"}, format="json")
        assert r.status_code == 400
        if i == settings.LOGIN_MAX_FAILS - 2:
            assert "Осталось попыток: 1" in r.json()["error"]["message"]
    r = c.post("/api/v1/admin/auth/login", {"username": "owner", "password": "Strong-pass-123"}, format="json")
    assert r.status_code == 429 and r.json()["error"]["code"] == "login_locked"
    # блокировка касается только этого логина
    assert c.post("/api/v1/admin/auth/login", {"username": "courier1", "password": "Strong-pass-123"},
                  format="json").status_code == 200


@pytest.mark.django_db
def test_demo_password_is_reported_as_weak(db):
    make_user("owner", User.Role.OWNER, password="owner12345")
    r = APIClient().post("/api/v1/admin/auth/login", {"username": "owner", "password": "owner12345"}, format="json")
    assert r.status_code == 200 and r.json()["user"]["weak_password"] is True


@pytest.mark.django_db
def test_staff_can_be_signed_in_on_phone_and_computer(staff):
    phone = staff_client("florist")
    computer = staff_client("florist")  # второй вход не выкидывает с первого устройства
    assert phone.get("/api/v1/admin/auth/me").status_code == 200
    assert computer.get("/api/v1/admin/auth/me").status_code == 200
    assert computer.post("/api/v1/admin/auth/logout").status_code == 200  # выход — только на этом устройстве
    assert computer.get("/api/v1/admin/auth/me").status_code == 401
    assert phone.get("/api/v1/admin/auth/me").status_code == 200
    owner = staff_client("owner")
    u = User.objects.get(username="florist")
    assert owner.patch(f"/api/v1/admin/staff/{u.pk}", {"is_active": False}, format="json").status_code == 200
    assert phone.get("/api/v1/admin/auth/me").status_code == 401  # отключение — выход на всех устройствах


@pytest.mark.django_db
def test_change_password_rotates_token(staff):
    c = staff_client("florist")
    old_auth = f"Bearer {c.cookies['cu_staff'].value}"
    r = c.post("/api/v1/admin/auth/password", {"old_password": "nope", "new_password": "Another-strong-77"},
               format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "old_password"
    r = c.post("/api/v1/admin/auth/password", {"old_password": "Strong-pass-123", "new_password": "12345678901"},
               format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "new_password"
    r = c.post("/api/v1/admin/auth/password", {"old_password": "Strong-pass-123", "new_password": "Another-strong-77"},
               format="json")
    assert r.status_code == 200, r.content
    stale = APIClient(HTTP_AUTHORIZATION=old_auth)
    assert stale.get("/api/v1/admin/auth/me").status_code == 401
    assert "token" not in r.json() and r.cookies["cu_staff"]["httponly"]
    fresh = APIClient(HTTP_AUTHORIZATION=f"Bearer {r.cookies['cu_staff'].value}")
    assert fresh.get("/api/v1/admin/auth/me").status_code == 200
    staff_client("florist", "Another-strong-77")


@pytest.mark.django_db
def test_security_check_only_for_owner(staff, settings):
    settings.PRODUCTION = True
    settings.PAYMENT_PROVIDER = "simulator"
    r = staff_client("owner").get("/api/v1/admin/security/check")
    assert r.status_code == 200
    body = r.json()
    assert body["production"] is True and "items" in body
    assert "Strong-pass-123" not in json.dumps(body)
    assert staff_client("florist").get("/api/v1/admin/security/check").status_code == 403


@pytest.mark.django_db
def test_owner_deletes_staff_but_not_self(staff):
    c = staff_client("owner")
    assert c.delete(f"/api/v1/admin/staff/{staff['owner'].id}").status_code == 400
    assert c.delete(f"/api/v1/admin/staff/{staff['courier2'].id}").status_code == 200
    assert not User.objects.filter(username="courier2").exists()
    assert staff_client("florist").delete(f"/api/v1/admin/staff/{staff['courier1'].id}").status_code == 403


@pytest.mark.django_db
def test_new_staff_password_must_be_strong(staff):
    c = staff_client("owner")
    r = c.post("/api/v1/admin/staff", {"username": "anna", "role": "florist", "password": "qwerty"}, format="json")
    assert r.status_code == 400
    r = c.post("/api/v1/admin/staff", {"username": "anna", "role": "florist", "password": "Lilac-Vase-2024!"},
               format="json")
    assert r.status_code == 201


# ------------------------------------------------------------------ загрузка изображений

@pytest.mark.django_db
def test_uploaded_photo_is_reencoded_without_metadata(shop, staff, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    b = shop.bouquet(assembled=1)
    c = staff_client("florist")
    r = c.post(f"/api/v1/admin/products/{b.id}/images", {"image": _png(exif=True)}, format="multipart")
    assert r.status_code == 200, r.content
    img = b.images.get()
    assert img.image.name.endswith(".jpg") and "photo" not in img.image.name  # случайное имя
    with Image.open(img.image.path) as saved:
        assert not saved.getexif()


@pytest.mark.django_db
def test_upload_rejects_fake_and_giant_images(shop, staff, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    b = shop.bouquet(assembled=1)
    c = staff_client("florist")
    fake = SimpleUploadedFile("evil.png", b"<?php echo 1; ?>", content_type="image/png")
    assert c.post(f"/api/v1/admin/products/{b.id}/images", {"image": fake}, format="multipart").status_code == 400
    gif = io.BytesIO()
    Image.new("RGB", (32, 32)).save(gif, "GIF")
    r = c.post(f"/api/v1/admin/products/{b.id}/images",
               {"image": SimpleUploadedFile("a.gif", gif.getvalue(), content_type="image/gif")}, format="multipart")
    assert r.status_code == 400
    giant = _png(9000, 5000, mode="1")  # 45 Мп — «бомба» по разрешению
    r = c.post(f"/api/v1/admin/products/{b.id}/images", {"image": giant}, format="multipart")
    assert r.status_code == 400 and "мегапиксел" in r.json()["error"]["message"]
    assert not b.images.exists()


@pytest.mark.django_db
def test_settings_logo_upload_uses_clean_file(staff, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    r = staff_client("owner").post("/api/v1/admin/settings", {"logo": _png()}, format="multipart")
    assert r.status_code == 200, r.content
    assert r.json()["logo"].endswith(".png")


# ------------------------------------------------------------------ спам-заказы

def _cart_with(web, product):
    token = web.post("/api/v1/carts", format="json").json()["token"]
    web.post(f"/api/v1/carts/{token}/items", {"product_id": product.id, "quantity": 1}, format="json")
    return token


@pytest.mark.django_db
def test_checkout_honeypot_rejects_bots(shop, web):
    b = shop.bouquet(assembled=2)
    data = {**shop.order_data(), "cart_token": _cart_with(web, b), "website": "http://spam.example"}
    r = web.post("/api/v1/checkout", data, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "spam_detected"
    assert not Order.objects.exists()


@pytest.mark.django_db
def test_pending_orders_per_phone_are_limited(shop, settings):
    settings.MAX_PENDING_ORDERS_PER_PHONE = 2
    b = shop.bouquet(assembled=5)
    shop.place((b, 1))
    shop.place((b, 1))
    with pytest.raises(ValidationError) as e:
        shop.place((b, 1))
    assert e.value.code == "too_many_pending_orders"


@pytest.mark.django_db
def test_checkout_is_rate_limited_per_ip(shop, settings):
    settings.THROTTLE_INTERNAL_EXEMPT = False
    c = _client()
    codes = [c.post("/api/v1/checkout", {"cart_token": "nope"}, format="json").status_code for _ in range(7)]
    assert codes[-1] == 429 and 429 not in codes[:6]


# ------------------------------------------------------------------ онлайн-оплата выключена

@pytest.mark.django_db
def test_without_online_payments_orders_are_cash_on_delivery(shop, web, settings):
    settings.ONLINE_PAYMENTS_ENABLED = False
    from apps.core.models import ShopSettings

    ShopSettings.objects.filter(pk=1).update(allow_cash_on_delivery=False)
    pub = web.get("/api/v1/settings/public").json()
    assert pub["online_payment_enabled"] is False and pub["allow_cash_on_delivery"] is True
    assert pub["payment_test_mode"] is False
    b = shop.bouquet(assembled=3)
    with pytest.raises(ValidationError) as e:
        shop.place((b, 1), payment="online")
    assert e.value.code == "online_payment_unavailable"
    data = shop.order_data()
    data.pop("payment_method")
    cart = carts.create_cart("web")
    carts.add_product(cart, b.id, 1)
    o = orders.place_order(cart, data)
    assert o.payment_method == Order.PaymentMethod.ON_DELIVERY and not o.payments.exists()
    # индивидуальный букет без онлайн-кассы тоже можно оплатить при получении
    o2 = shop.place(custom=shop.custom_composition(), payment="on_delivery", days=2)
    assert o2.payment_method == Order.PaymentMethod.ON_DELIVERY


# ------------------------------------------------------------------ ЮKassa (запросы к API замоканы)

class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data


@pytest.mark.django_db
def test_yookassa_payment_flow_with_verified_webhook(shop, settings):
    settings.PAYMENT_PROVIDER = "yookassa"
    settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY = "123456", "test_secret"
    b = shop.bouquet(assembled=2, price=250000)
    calls = []
    state = {"status": "pending"}

    def fake(method, url, **kw):
        calls.append((method, url, kw.get("headers", {}), kw.get("data")))
        if method == "POST" and url.endswith("/payments"):
            body = json.loads(kw["data"])
            assert body["amount"] == {"value": f"{(250000 + 30000) / 100:.2f}", "currency": "RUB"}
            assert kw["auth"] == ("123456", "test_secret") and kw["headers"]["Idempotence-Key"]
            return _Resp({"id": "2f0c-yk-1", "status": "pending",
                          "confirmation": {"type": "redirect", "confirmation_url": "https://yoomoney.ru/checkout/x"}})
        if method == "GET" and url.endswith("/payments/2f0c-yk-1"):
            return _Resp({"id": "2f0c-yk-1", "status": state["status"], "amount": {"value": "2800.00", "currency": "RUB"}})
        raise AssertionError(url)

    with mock.patch("apps.payments.providers.yookassa.requests.request", side_effect=fake):
        o = shop.place((b, 1))
        p = o.payments.get()
        assert p.provider == "yookassa" and not p.is_test and p.confirmation_url.startswith("https://yoomoney.ru/")
        hook = json.dumps({"type": "notification", "event": "payment.succeeded", "object": {"id": "2f0c-yk-1"}}).encode()
        # пока платёж в ЮKassa не оплачен, «поддельное» уведомление об успехе ничего не меняет
        with pytest.raises(Exception):
            payments.process_webhook("yookassa", hook, {})
        p.refresh_from_db()
        assert p.status == Payment.Status.PENDING
        state["status"] = "succeeded"
        r = payments.process_webhook("yookassa", hook, {})
        assert r["status"] == "processed"
        assert payments.process_webhook("yookassa", hook, {})["status"] == "duplicate"
    o.refresh_from_db()
    p.refresh_from_db()
    assert p.status == Payment.Status.PAID and o.status == Order.Status.CONFIRMED


@pytest.mark.django_db
def test_yookassa_webhook_endpoint_rejects_garbage(web, settings):
    settings.PAYMENT_PROVIDER = "yookassa"
    r = web.post("/api/v1/payments/webhook/yookassa", data="{bad", content_type="application/json")
    assert r.status_code == 400
    r = web.post("/api/v1/payments/webhook/yookassa", {"event": "payment.succeeded", "object": {"id": "../../x"}},
                 format="json")
    assert r.status_code == 400


# ------------------------------------------------------------------ геокодер

def test_yandex_daily_limit_switches_to_nominatim(settings):
    settings.GEOCODER_PROVIDER = "auto"
    settings.YANDEX_GEOCODER_API_KEY = "key"
    settings.YANDEX_GEOCODER_DAILY_LIMIT = 3
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    cache.clear()
    assert geo.provider() == "yandex"
    for _ in range(3):
        geo._yandex_count()
    assert geo.yandex_used_today() == 3 and geo.provider() == "nominatim"


# ------------------------------------------------------------------ бот: почему нет «Сегодня»

@pytest.mark.django_db
def test_today_note_explains_cutoff(shop):
    DeliverySlot.objects.update(is_active=False)
    DeliverySlot.objects.create(start_time=time(0, 0), end_time=time(0, 31), capacity=5)
    note = today_unavailable_note("delivery")
    assert note and "до " in note and "сегодня" in note
    DeliverySlot.objects.update(is_active=False)
    DeliverySlot.objects.create(start_time=time(0, 0), end_time=time(23, 59), capacity=5)
    # до 21:29 по местному времени на сегодня ещё можно — подсказки нет (или все занято — тоже понятная фраза)
    note2 = today_unavailable_note("delivery")
    assert note2 is None or "сегодня" in note2


def test_secret_tokens_are_masked_in_access_logs():
    from config.log_masking import mask_secrets

    assert mask_secrets("GET /order/AbC123xyz HTTP/1.1") == "GET /order/*** HTTP/1.1"
    assert mask_secrets("/api/v1/orders/track/tok123/pay") == "/api/v1/orders/track/***/pay"
    assert mask_secrets("/api/v1/carts/c4rt/items/5") == "/api/v1/carts/***/items/5"
    assert mask_secrets("/api/v1/account/login/status?token=s3cr3t&x=1") == "/api/v1/account/login/status?token=***&x=1"
    assert mask_secrets("https://cvetyurala.ru/pay/p4y?from=bot") == "https://cvetyurala.ru/pay/***?from=bot"
    # обычные адреса не трогаем
    assert mask_secrets("/api/v1/admin/orders/12") == "/api/v1/admin/orders/12"
    assert mask_secrets("/bouquets?type=rose") == "/bouquets?type=rose"
    assert mask_secrets("token=s3cr3t") == "token=***"  # строка запроса отдельно (gunicorn %(q)s)
    assert mask_secrets(None) is None


def test_django_request_warnings_hide_tokens():
    import logging

    from config.log_masking import MaskSecretsFilter

    rec = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "Not Found: %s", ("/api/v1/orders/track/T0KEN",), None)
    MaskSecretsFilter().filter(rec)
    assert rec.getMessage() == "Not Found: /api/v1/orders/track/***"


@pytest.mark.django_db
def test_staff_session_in_httponly_cookie(staff):
    from apps.core.models import StaffToken

    c = APIClient()
    r = c.post("/api/v1/admin/auth/login", {"username": "florist", "password": "Strong-pass-123"}, format="json")
    assert r.status_code == 200 and "token" not in r.json()
    cookie = r.cookies["cu_staff"]
    assert cookie["httponly"] and cookie["samesite"] == "Strict" and cookie["path"] == "/api/v1/admin"
    # чтение работает по cookie, а изменения — только с заголовком нашего сайта (защита от подделки запросов)
    assert c.get("/api/v1/admin/auth/me").status_code == 200
    assert c.patch("/api/v1/admin/me/notify", {"notify_mode": "off"}, format="json").status_code == 401
    assert c.patch("/api/v1/admin/me/notify", {"notify_mode": "off"}, format="json",
                   HTTP_X_REQUESTED_WITH="fetch").status_code == 200
    # испорченный cookie — просто «не вошли», а не ошибка
    bad = APIClient()
    bad.cookies["cu_staff"] = "x" * 40
    assert bad.get("/api/v1/admin/auth/me").status_code == 401
    # выход удаляет токен на сервере и cookie в браузере
    out = c.post("/api/v1/admin/auth/logout", format="json", HTTP_X_REQUESTED_WITH="fetch")
    assert out.status_code == 200 and out.cookies["cu_staff"].value == ""
    assert not StaffToken.objects.filter(key=cookie.value).exists()
    assert APIClient().post("/api/v1/admin/auth/logout", format="json").status_code == 200


@pytest.mark.django_db
def test_staff_adopts_legacy_token(staff):
    """Старая версия сайта хранила токен в localStorage: при первом входе он переносится в cookie."""
    from apps.core.models import StaffToken

    token = StaffToken.issue(staff["owner"])
    legacy = APIClient(HTTP_AUTHORIZATION=f"Bearer {token.key}")
    r = legacy.post("/api/v1/admin/auth/adopt", format="json")
    assert r.status_code == 200 and r.cookies["cu_staff"].value == token.key and "token" not in r.json()
    assert APIClient().post("/api/v1/admin/auth/adopt", format="json").status_code == 401
