"""Приём заказов (вкл/выкл), кнопка «Войти» (вкл/выкл), «Частые вопросы» и заголовки для поисковиков из админки."""
import pytest
from rest_framework.test import APIClient

from apps.bots.engine import BotEngine, Incoming
from apps.carts import services as carts
from apps.core.models import ShopSettings
from apps.core.site_content import ORDERS_CLOSED_DEFAULT
from apps.orders import services as orders
from apps.orders.models import Order

from .conftest import staff_client

pytestmark = pytest.mark.django_db
API = "/api/v1"


def _patch(client, **data):
    return client.patch(f"{API}/admin/settings", data, format="json")


def _buttons(out):
    return [b for m in out for row in m.buttons for b in row]


# ------------------------------------------------------------------ приём заказов

def test_orders_open_by_default(shop, web):
    s = web.get(f"{API}/settings/public").json()
    assert s["orders_enabled"] is True and s["orders_closed_message"] == ORDERS_CLOSED_DEFAULT


def test_closed_orders_block_site_and_bots_but_not_store(shop, web, staff):
    owner = staff_client("owner")
    bouquet = shop.bouquet("b1", assembled=3)
    old_cart = carts.create_cart("web")
    carts.add_product(old_cart, bouquet.id, 1)  # положили, пока приём был открыт

    r = _patch(owner, orders_enabled=False, orders_closed_message="  Уехали за цветами до понедельника  ")
    assert r.status_code == 200, r.content
    assert r.json()["orders_enabled"] is False
    s = web.get(f"{API}/settings/public").json()
    assert s["orders_enabled"] is False and s["orders_closed_message"] == "Уехали за цветами до понедельника"

    # витрина работает
    assert web.get(f"{API}/catalog/products/{bouquet.slug}").status_code == 200
    # в корзину и оформить — нельзя
    token = web.post(f"{API}/carts", format="json").json()["token"]
    r = web.post(f"{API}/carts/{token}/items", {"product_id": bouquet.id, "quantity": 1}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "orders_closed"
    assert "до понедельника" in r.json()["error"]["message"]
    r = web.post(f"{API}/carts/{token}/custom-bouquet", {"composition": shop.custom_composition()}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "orders_closed"
    with pytest.raises(carts.OrdersClosed):
        orders.place_order(old_cart, shop.order_data())
    r = web.post(f"{API}/checkout", {"cart_token": str(old_cart.token), **shop.order_data()}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "orders_closed"
    assert not Order.objects.exists()

    # бот: в меню и каталоге — сообщение, кнопок «В корзину» нет, добавить и оформить нельзя
    e = BotEngine("telegram")
    say = lambda **kw: e.handle(Incoming(channel="telegram", user_id="u-closed", simulated=True, **kw))  # noqa: E731
    out = say(text="/start")
    assert "до понедельника" in out[0].text
    out = say(payload="cat:all:0")
    assert not [b for b in _buttons(out) if (b.payload or "").startswith("add:")]
    out = say(payload=f"add:{bouquet.id}")
    assert "до понедельника" in out[0].text
    out = say(payload="checkout")
    assert "до понедельника" in out[0].text

    # продажа в магазине (касса) работает всегда
    r = owner.post(f"{API}/admin/store-sale", {"lines": [{"product_id": bouquet.id, "quantity": 1}],
                                               "payment": "cash"}, format="json")
    assert r.status_code == 201, r.content

    # сводка показывает, что приём закрыт
    d = owner.get(f"{API}/admin/dashboard").json()
    assert d["orders_enabled"] is False and "до понедельника" in d["orders_closed_message"]

    # открыли — снова можно
    _patch(owner, orders_enabled=True)
    assert web.post(f"{API}/carts/{token}/items", {"product_id": bouquet.id, "quantity": 1},
                    format="json").status_code == 200
    order = orders.place_order(old_cart, shop.order_data())
    assert order.pk


def test_only_owner_closes_orders(shop, staff):
    florist = staff_client("florist")
    assert _patch(florist, orders_enabled=False).status_code == 403
    assert ShopSettings.load().orders_enabled is True


def test_empty_message_means_default(shop, web, staff):
    owner = staff_client("owner")
    _patch(owner, orders_enabled=False, orders_closed_message="")
    assert web.get(f"{API}/settings/public").json()["orders_closed_message"] == ORDERS_CLOSED_DEFAULT


# ------------------------------------------------------------------ кнопка «Войти»

def test_customer_login_switch(shop, web, staff, settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.TELEGRAM_BOT_USERNAME = "cvety_test_bot"
    settings.VK_GROUP_TOKEN = "vk-token"
    settings.VK_GROUP_ID = "777"
    settings.CUSTOMER_LOGIN_TEST_MODE = False
    owner = staff_client("owner")
    s = web.get(f"{API}/settings/public").json()["customer_login"]
    assert s["telegram"] and s["vk"] and s["enabled"]

    r = _patch(owner, customer_login_enabled=False)
    assert r.status_code == 200 and r.json()["customer_login_enabled"] is False
    s = web.get(f"{API}/settings/public").json()["customer_login"]
    assert not s["telegram"] and not s["vk"] and s["enabled"] is False
    r = web.post(f"{API}/account/login/start", {"channel": "telegram"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "channel_unavailable"

    _patch(owner, customer_login_enabled=True)
    assert web.post(f"{API}/account/login/start", {"channel": "telegram"}, format="json").status_code == 201


# ------------------------------------------------------------------ «Частые вопросы»

def test_faq_default_edit_and_reset(shop, web, staff):
    owner = staff_client("owner")
    blocks = web.get(f"{API}/faq").json()["blocks"]
    assert len(blocks) == 2
    questions = [it["q"] for b in blocks for it in b["items"]]
    assert "Сколько стоит доставка?" in questions
    assert "[«Доставка и оплата»](/delivery)" in blocks[0]["items"][0]["a"]

    got = owner.get(f"{API}/admin/faq").json()
    assert got["custom"] is False and got["blocks"] == blocks

    new = [
        {"title": "Доставка", "items": [{"q": "Возите ночью?", "a": "Нет.\n\n- днём\n- вечером"},
                                         {"q": "", "a": ""}]},  # пустая строка формы — убирается
        {"title": "", "items": []},  # пустой блок без названия — убирается
        {"title": "Подарки", "items": [{"q": "Есть открытки?", "a": "Да, **бесплатно**."}]},
    ]
    r = owner.put(f"{API}/admin/faq", {"blocks": new}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["custom"] is True
    pub = web.get(f"{API}/faq").json()["blocks"]
    assert [b["title"] for b in pub] == ["Доставка", "Подарки"]
    assert pub[0]["items"] == [{"q": "Возите ночью?", "a": "Нет.\n\n- днём\n- вечером"}]

    # вопрос без ответа — ошибка с указанием поля
    r = owner.put(f"{API}/admin/faq", {"blocks": [{"title": "X", "items": [{"q": "Вопрос?", "a": ""}]}]}, format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "faq.0.0.a"
    r = owner.put(f"{API}/admin/faq", {"blocks": "нет"}, format="json")
    assert r.status_code == 400

    # можно сохранить и пустой список — блок вопросов на сайте пропадёт
    r = owner.put(f"{API}/admin/faq", {"blocks": []}, format="json")
    assert r.status_code == 200 and web.get(f"{API}/faq").json()["blocks"] == []

    r = owner.delete(f"{API}/admin/faq")
    assert r.status_code == 200 and r.json()["custom"] is False
    assert len(web.get(f"{API}/faq").json()["blocks"]) == 2


def test_faq_owner_only(shop, staff):
    florist = staff_client("florist")
    assert florist.get(f"{API}/admin/faq").status_code == 403
    assert florist.put(f"{API}/admin/faq", {"blocks": []}, format="json").status_code == 403
    assert APIClient().get(f"{API}/admin/faq").status_code in (401, 403)


# ------------------------------------------------------------------ поисковики

def test_seo_titles_and_verification(shop, web, staff):
    owner = staff_client("owner")
    seo = web.get(f"{API}/settings/public").json()["seo"]
    s = ShopSettings.load()
    assert s.shop_name in seo["pages"]["home"]["title"]
    assert "{name}" in seo["pages"]["product"]["title"]
    assert seo["organization"]["@type"] == "Florist" and seo["organization"]["name"] == s.shop_name
    assert seo["site_url"].startswith("http")

    adm = owner.get(f"{API}/admin/settings").json()
    assert adm["seo_defaults"]["home"]["title"] == seo["pages"]["home"]["title"]
    assert [p["key"] for p in adm["seo_page_list"]][:2] == ["home", "bouquets"]

    r = _patch(owner, seo_pages={"home": {"title": "Цветы в Кондратово — доставка за 2 часа", "description": ""},
                                 "unknown": {"title": "x"}},
               yandex_verification='<meta name="yandex-verification" content="0123abcd4567ef89" />',
               google_verification="AbC-123_xyzXYZ")
    assert r.status_code == 200, r.content
    assert r.json()["seo_pages"] == {"home": {"title": "Цветы в Кондратово — доставка за 2 часа", "description": ""}}
    seo = web.get(f"{API}/settings/public").json()["seo"]
    assert seo["pages"]["home"]["title"] == "Цветы в Кондратово — доставка за 2 часа"
    assert seo["pages"]["home"]["description"] == adm["seo_defaults"]["home"]["description"]  # пустое — стандартное
    assert seo["yandex_verification"] == "0123abcd4567ef89" and seo["google_verification"] == "AbC-123_xyzXYZ"

    r = _patch(owner, yandex_verification="<script>alert(1)</script>")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "yandex_verification"
    r = _patch(owner, seo_pages={"home": {"title": "x" * 121}})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "seo.home.title"
