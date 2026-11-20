"""Сценарий заказа через чат-бота (движок общий для Telegram и ВК, работает и в демо-симуляторе)."""
import pytest

from apps.bots.engine import BotEngine, Incoming
from apps.notifications.models import Notification
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def _buttons(out):
    return [b for m in out for row in m.buttons for b in row]


def _press(engine, uid, out, startswith):
    btn = next(b for b in _buttons(out) if b.text.startswith(startswith) or (b.payload or "").startswith(startswith))
    return engine.handle(Incoming(channel=engine.channel, user_id=uid, payload=btn.payload, simulated=True))


@pytest.mark.parametrize("channel", ["telegram", "vk"])
def test_full_bot_checkout(shop, channel):
    b = shop.bouquet(assembled=2)
    e = BotEngine(channel)
    uid = f"sim-{channel}-1"
    say = lambda **kw: e.handle(Incoming(channel=channel, user_id=uid, simulated=True, **kw))  # noqa: E731
    out = say(text="/start")
    assert "Каталог" in " ".join(b.text for b in _buttons(out))
    out = say(payload="cat:all:0")
    out = say(payload=f"add:{b.id}")
    assert shop.available(b) == 2  # в корзине бота ещё нет резерва
    out = say(payload="cart")
    out = _press(e, uid, out, "checkout")
    # самовывоз → дата → интервал → имя → телефон → получатель → комментарий → оплата → подтверждение
    from apps.bots.models import BotSession

    for _ in range(15):
        step = BotSession.objects.get(channel=channel, external_user_id=uid).data.get("checkout", {}).get("step")
        if step == "name":
            out = say(text="Ольга")
            continue
        if step == "phone":
            out = say(text="+7 (900) 111-22-33")
            continue
        btns = _buttons(out)
        pick = None
        for prefix in ("ful:pickup", "date:", "slot:", "rcpt:self", "comment:skip", "pay:on_delivery", "confirm:yes"):
            pick = next((x for x in btns if (x.payload or "").startswith(prefix)), None)
            if pick:
                break
        assert pick, (step, [m.text for m in out])
        out = say(payload=pick.payload)
        if Order.objects.exists():
            break
    assert "№" in " ".join(m.text for m in out)
    order = Order.objects.get()
    assert order.source == channel and order.fulfillment == "pickup"
    assert order.status == "new" and order.contact_phone == "+79001112233"
    assert shop.available(b) == 1


def test_bot_flowers_info_points_to_site(shop):
    out = BotEngine("telegram").handle(Incoming(channel="telegram", user_id="sim-x", payload="flowers", simulated=True))
    text = " ".join(m.text for m in out)
    assert "Роза" in text and "сайт" in text.lower()
    assert not any((b.payload or "").startswith("add:") for b in _buttons(out))


def test_simulator_api_roundtrip(shop, web):
    shop.bouquet(assembled=1)
    r = web.post("/api/v1/simulator/telegram/message", {"user_id": "sim-web-1", "text": "/start"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["messages"]
    r = web.post("/api/v1/simulator/telegram/message", {"user_id": "real-123", "text": "/start"}, format="json")
    assert r.status_code == 400


def test_support_request_creates_staff_notification(shop):
    e = BotEngine("vk")
    e.handle(Incoming(channel="vk", user_id="sim-s", payload="support", simulated=True))
    e.handle(Incoming(channel="vk", user_id="sim-s", text="Можно ли добавить открытку?", simulated=True))
    assert Notification.objects.filter(channel="staff", kind="support_request").exists()


def _step(channel, uid):
    from apps.bots.models import BotSession

    return BotSession.objects.get(channel=channel, external_user_id=uid).data.get("checkout", {}).get("step")


def test_bot_delivery_confirmation_and_edit(shop, monkeypatch, settings):
    """Перед созданием заказа бот спрашивает «Данные указаны правильно?» — «Да» / «Изменить»."""
    from apps.core.models import ShopSettings
    from apps.delivery import geo

    from .conftest import IN_ZONE, OUT_OF_ZONE

    s = ShopSettings.load()
    s.allow_cash_on_delivery = False
    s.save()
    settings.GEOCODER_PROVIDER = "nominatim"
    found = {"value": geo.GeoResult("Кондратово, Красавинская улица, 8", "", *IN_ZONE, True, "house")}
    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [found["value"]])
    b = shop.bouquet(assembled=2)
    e = BotEngine("telegram")
    uid = "sim-tg-confirm"
    say = lambda **kw: e.handle(Incoming(channel="telegram", user_id=uid, simulated=True, **kw))  # noqa: E731
    say(payload=f"add:{b.id}")
    say(payload="checkout")
    out = say(payload="ful:delivery")
    assert _step("telegram", uid) == "address"
    assert any(x.request_location for x in _buttons(out))  # в Telegram можно отправить геопозицию
    # адрес вне зон доставки — заказ с доставкой не оформить
    found["value"] = geo.GeoResult("Краснокамск, улица Ленина, 1", "", *OUT_OF_ZONE, True, "house")
    out = say(text="Краснокамск, Ленина 1")
    assert "не доставляем" in out[0].text and _step("telegram", uid) == "address"
    found["value"] = geo.GeoResult("Кондратово, Красавинская улица, 8", "", *IN_ZONE, True, "house")
    out = say(text="Красавинская, 8, кв. 12")
    assert "Красавинская улица, 8, кв. 12" in out[0].text and _step("telegram", uid) == "date"
    out = _press(e, uid, out, "date:")
    out = _press(e, uid, out, "slot:")
    out = say(text="Ольга")
    out = say(text="+7 900 111-22-33")
    out = _press(e, uid, out, "rcpt:self")
    out = _press(e, uid, out, "comment:skip")
    # оплата при получении выключена — шаг оплаты пропущен, сразу подтверждение
    assert _step("telegram", uid) == "confirm"
    assert "Данные указаны правильно?" in out[-1].text
    assert [x.text for x in out[-1].buttons[0]] == ["Да", "Изменить"]
    assert not Order.objects.exists()
    out = say(payload="confirm:edit")
    assert "edit:comment" in [x.payload for x in _buttons(out)] and "edit:payment" not in [x.payload for x in _buttons(out)]
    out = say(payload="edit:comment")
    assert _step("telegram", uid) == "comment"
    out = say(text="Позвонить за час")
    assert _step("telegram", uid) == "confirm" and "Позвонить за час" in out[-1].text
    out = say(text="Да")
    order = Order.objects.get()
    assert order.comment == "Позвонить за час" and order.payment_method == "online"
    assert order.delivery.address == "Кондратово, Красавинская улица, 8" and order.delivery.apartment == "12"
    assert order.delivery.address_verified and order.delivery.zone == shop.zone
    assert "Оплатить" in " ".join(x.text for x in _buttons(out))
