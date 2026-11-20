"""Вход покупателя на сайт через Telegram / ВКонтакте, профиль и привязка заказов к мессенджеру."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bots.engine import BotEngine, Incoming
from apps.customers.models import Customer, CustomerChannel, CustomerLogin, CustomerSession
from apps.notifications.models import Notification
from apps.orders.models import Order


@pytest.fixture
def bots_on(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.TELEGRAM_BOT_USERNAME = "cvety_test_bot"
    settings.VK_GROUP_TOKEN = "vk-token"
    settings.VK_GROUP_ID = "777"
    settings.CUSTOMER_LOGIN_TEST_MODE = False
    return settings


FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}  # заголовок ставит наш сайт; без него cookie для изменений не принимаются


def _start(client, channel="telegram", ua="", **extra):
    r = client.post("/api/v1/account/login/start", {"channel": channel, **extra}, format="json", HTTP_USER_AGENT=ua)
    assert r.status_code == 201, r.content
    data = r.json()
    # секретный токен входа — только в HttpOnly-cookie, в JSON (и в JavaScript страницы) его нет
    assert "token" not in data
    cookie = r.cookies["cu_login"]
    assert cookie["httponly"] and cookie["samesite"] == "Strict" and cookie["path"] == "/api/v1/account/login"
    return {**data, "token": cookie.value}


def _status(client, st=None):
    """Статус входа: по cookie браузера или (st) — по токену в теле запроса."""
    body = {"token": st["token"]} if st else {}
    return client.post("/api/v1/account/login/status", body, format="json", **FETCH).json()


def _tg(text=None, payload=None, user="5001", name="Анна Петрова", username="anna"):
    return BotEngine("telegram").handle(Incoming(channel="telegram", user_id=user, chat_id=user, text=text, payload=payload,
                                                 display_name=name, username=username))


def _confirm_tg(start, user="5001"):
    link = start["link"].split("start=login_")[1]
    out = _tg(f"/start login_{link}", user=user)
    btn = out[0].buttons[0][0]
    assert btn.payload.startswith("login_ok:")
    return _tg(payload=btn.payload, user=user)


def _session(client, start):
    # сайт спрашивает статус POST-запросом с cookie cu_login: токен не попадает ни в адрес, ни в JavaScript
    r = client.post("/api/v1/account/login/status", format="json", **FETCH)
    assert r.json()["status"] == "confirmed" and "session_token" not in r.json(), r.json()
    cookie = r.cookies["cu_customer"]
    assert cookie["httponly"] and cookie["samesite"] == "Strict" and cookie["path"] == "/api/v1"
    assert r.cookies["cu_login"].value == ""  # незавершённый вход больше не нужен
    return cookie.value


def _cart_checkout(client, shop, product, token=None, **kw):
    cart = client.post("/api/v1/carts", format="json").json()["token"]
    client.post(f"/api/v1/carts/{cart}/items", {"product_id": product.id, "quantity": 1}, format="json")
    headers = {"HTTP_X_CUSTOMER_TOKEN": token} if token else {}
    return client.post("/api/v1/checkout", {"cart_token": cart, **shop.order_data(**kw)}, format="json", **headers)


def test_login_unavailable_without_bots(db, web, settings):
    settings.CUSTOMER_LOGIN_TEST_MODE = False
    r = web.post("/api/v1/account/login/start", {"channel": "telegram"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "channel_unavailable"
    s = web.get("/api/v1/settings/public").json()["customer_login"]
    assert s == {"telegram": False, "vk": False, "test_mode": False, "enabled": True}


def test_telegram_login_flow(db, web, bots_on):
    assert web.get("/api/v1/settings/public").json()["customer_login"]["telegram"] is True
    st = _start(web, ua="Mozilla/5.0 (Windows NT 10.0) Chrome/120.0")
    assert st["link"].startswith("https://t.me/cvety_test_bot?start=login_") and len(st["code"]) == 6
    assert _status(web, st)["status"] == "pending"
    link = st["link"].split("start=login_")[1]
    ask = _tg(f"/start login_{link}")
    assert "(Chrome, Windows)" in ask[0].text
    out = _tg(payload=ask[0].buttons[0][0].payload)
    assert "вошли на сайт" in out[0].text
    token = _session(web, st)
    # токен сессии выдаётся один раз, в базе — только хеш
    assert _status(web, st) == {"status": "used"}
    assert not CustomerSession.objects.filter(key_hash=token).exists()
    me = web.get("/api/v1/account/me", HTTP_X_CUSTOMER_TOKEN=token).json()
    assert me["name"] == "Анна Петрова"
    assert me["channels"][0]["channel"] == "telegram" and me["channels"][0]["username"] == "anna"
    assert APIClient().get("/api/v1/account/me").status_code == 401
    # старый способ GET ?token= больше не работает — токен не должен оказываться в адресе
    assert web.get(f"/api/v1/account/login/status?token={st['token']}").status_code == 405


def test_confirm_requires_same_messenger_user(db, web, bots_on):
    st = _start(web)
    link = st["link"].split("start=login_")[1]
    btn = _tg(f"/start login_{link}", user="5001")[0].buttons[0][0]
    # чужой аккаунт не может ни перехватить ссылку, ни нажать «Войти» за другого
    assert "устарели" in _tg(f"/start login_{link}", user="6666")[0].text
    assert "устарел" in _tg(payload=btn.payload, user="6666")[0].text
    assert _status(web, st)["status"] == "pending"
    _tg(payload=btn.payload, user="5001")
    assert _status(web, st)["status"] == "confirmed"


def test_cancel_and_expired(db, web, bots_on):
    st = _start(web)
    link = st["link"].split("start=login_")[1]
    _tg(f"/start login_{link}")
    login = CustomerLogin.objects.get(token=st["token"])
    assert "отменён" in _tg(payload=f"login_no:{login.pk}")[0].text
    assert _status(web, st)["status"] == "cancelled"
    st2 = _start(web)
    CustomerLogin.objects.filter(token=st2["token"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert _status(web, st2)["status"] == "expired"
    assert "устарели" in _tg(f"/start login_{st2['link'].split('login_')[1]}")[0].text


def test_manual_code_and_attempt_limit(db, web, bots_on):
    st = _start(web)
    out = _tg(f"{st['code'][:3]} {st['code'][3:]}")
    assert out[0].buttons[0][0].payload.startswith("login_ok:")
    for _ in range(5):
        assert "устарели" in _tg("000000", user="7007")[0].text
    assert "Слишком много" in _tg(st["code"], user="7007")[0].text


def test_vk_login_by_ref(db, web, bots_on):
    st = _start(web, channel="vk")
    assert st["link"].startswith("https://vk.me/club777?ref=login_")
    link = st["link"].split("ref=")[1].split("&")[0]
    eng = BotEngine("vk")
    out = eng.handle(Incoming(channel="vk", user_id="9001", chat_id="9001", text="Начать", ref=link, display_name="Иван"))
    eng.handle(Incoming(channel="vk", user_id="9001", chat_id="9001", payload=out[0].buttons[0][0].payload))
    token = _session(web, st)
    me = web.get("/api/v1/account/me", HTTP_X_CUSTOMER_TOKEN=token).json()
    assert me["channels"][0]["channel"] == "vk" and me["channels"][0]["display_name"] == "Иван"


def test_checkout_signed_in_links_order_and_notifies_messenger(shop, web, bots_on):
    st = _start(web)
    _confirm_tg(st)
    token = _session(web, st)
    # у этого телефона уже есть «чужой» клиент — вошедшего покупателя с ним не объединяем
    other = Customer.objects.create(name="Другой", phone="+79001234567")
    r = _cart_checkout(web, shop, shop.bouquet(assembled=1), token=token)
    assert r.status_code == 201, r.content
    order = Order.objects.get(number=r.json()["number"])
    tg_customer = CustomerChannel.objects.get(channel="telegram", external_id="5001").customer
    assert order.customer_id == tg_customer.pk and order.customer_id != other.pk
    assert not CustomerChannel.objects.filter(customer=other).exists()
    assert Notification.objects.filter(order=order, channel="telegram", recipient="5001", kind="order_created").exists()
    assert r.json()["notify_channels"] == [{"channel": "telegram", "label": "Telegram"}]
    me = web.get("/api/v1/account/me", HTTP_X_CUSTOMER_TOKEN=token).json()
    assert [o["number"] for o in me["orders"]] == [order.number]
    assert me["last_delivery"]["address"] == "ул. Ленина, 1"
    assert me["phone"] == ""  # телефон занят другим клиентом — в профиль не переносим


def test_anonymous_order_connects_notifications_later(shop, web, bots_on):
    r = _cart_checkout(web, shop, shop.bouquet(assembled=1))
    data = r.json()
    assert data["notify_channels"] == []
    st = _start(web, order_token=data["token"])
    link = st["link"].split("start=login_")[1]
    out = _tg(f"/start login_{link}")
    assert f"заказе №{data['number']}" in out[0].text
    done = _tg(payload=out[0].buttons[0][0].payload)
    assert "подключены" in done[0].text
    order = Order.objects.get(number=data["number"])
    assert CustomerChannel.objects.filter(customer=order.customer, channel="telegram", external_id="5001").exists()
    status = _status(web, st)
    assert status["status"] == "confirmed" and status["order_token"] == data["token"]
    assert web.get(f"/api/v1/orders/track/{data['token']}").json()["notify_channels"][0]["channel"] == "telegram"


def test_profile_update_and_logout(db, web, bots_on):
    st = _start(web)
    _confirm_tg(st)
    token = _session(web, st)
    h = {"HTTP_X_CUSTOMER_TOKEN": token}
    bad = web.patch("/api/v1/account/me", {"phone": "123"}, format="json", **h)
    assert bad.status_code == 400 and bad.json()["error"]["details"]["field"] == "phone"
    ok = web.patch("/api/v1/account/me", {"name": "Анна", "phone": "8 (912) 000-11-22", "email": "a@b.ru"}, format="json", **h)
    assert ok.status_code == 200 and ok.json()["phone"] == "+79120001122"
    assert web.post("/api/v1/account/logout", format="json", **h).status_code == 200
    assert web.get("/api/v1/account/me", **h).status_code == 401


def test_test_mode_confirm(db, web, settings):
    settings.CUSTOMER_LOGIN_TEST_MODE = True
    st = _start(web, channel="vk")
    assert st["test_mode"] is True
    assert web.post("/api/v1/account/login/test-confirm", {"token": st["token"]}, format="json").status_code == 200
    token = _session(web, st)
    me = APIClient().get("/api/v1/account/me", HTTP_X_CUSTOMER_TOKEN=token).json()
    assert me["channels"][0]["test"] is True
    settings.CUSTOMER_LOGIN_TEST_MODE = False
    assert web.post("/api/v1/account/login/test-confirm", {"token": st["token"]}, format="json").status_code == 404


def test_confirmed_login_expires_if_not_collected(db, web, bots_on):
    """Подтверждённый в боте вход нужно забрать за 10 минут — потом он не превращается в сессию."""
    st = _start(web)
    _confirm_tg(st)
    CustomerLogin.objects.filter(token=st["token"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = web.post("/api/v1/account/login/status", format="json", **FETCH)
    assert r.json() == {"status": "expired"} and "cu_customer" not in r.cookies
    assert not CustomerSession.objects.exists()
    assert _status(web, st)["status"] == "cancelled"


def test_cookie_session_requires_site_header_for_changes(db, web, bots_on):
    st = _start(web)
    _confirm_tg(st)
    _session(web, st)
    # браузер присылает cookie сам; чтение работает без заголовка
    assert web.get("/api/v1/account/me").status_code == 200
    # изменение без заголовка X-Requested-With (так выглядит подделанный запрос с чужого сайта) — как без входа
    assert web.patch("/api/v1/account/me", {"name": "Взлом"}, format="json").status_code == 401
    web.post("/api/v1/account/logout", format="json")
    assert CustomerSession.objects.count() == 1
    ok = web.patch("/api/v1/account/me", {"name": "Анна"}, format="json", **FETCH)
    assert ok.status_code == 200 and ok.json()["name"] == "Анна"
    out = web.post("/api/v1/account/logout", format="json", **FETCH)
    assert out.status_code == 200 and out.cookies["cu_customer"].value == ""
    assert not CustomerSession.objects.exists()


def test_customer_adopts_legacy_header_session(db, web, bots_on):
    """Старая версия сайта хранила токен покупателя в localStorage: он переносится в HttpOnly-cookie."""
    st = _start(web)
    _confirm_tg(st)
    token = _session(web, st)
    legacy = APIClient()
    r = legacy.post("/api/v1/account/session/adopt", format="json", HTTP_X_CUSTOMER_TOKEN=token)
    assert r.status_code == 200 and r.cookies["cu_customer"].value == token
    assert legacy.get("/api/v1/account/me").status_code == 200
    bad = APIClient().post("/api/v1/account/session/adopt", format="json", HTTP_X_CUSTOMER_TOKEN="nope")
    assert bad.status_code == 401
