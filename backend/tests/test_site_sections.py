"""Разделы сайта «Цветы поштучно» и «Собрать букет»: владелец выключает их в настройках — сервер их закрывает."""
import pytest
from rest_framework.test import APIClient

from apps.carts import services as carts
from apps.catalog.models import Product
from apps.orders import services as orders

from .conftest import staff_client

pytestmark = pytest.mark.django_db
API = "/api/v1"


def _switch(owner, **flags):
    r = owner.patch(f"{API}/admin/settings", flags, format="json")
    assert r.status_code == 200, r.content
    for k, v in flags.items():
        assert r.json()[k] is v
    return r


def test_sections_are_on_by_default(shop, web):
    s = web.get(f"{API}/settings/public").json()
    assert s["flowers_section_enabled"] is True and s["constructor_section_enabled"] is True


def test_flowers_section_off_hides_and_blocks_single_stems(shop, web, staff):
    owner = staff_client("owner")
    rose = Product.objects.get(slug="fl-rose")
    bouquet = shop.bouquet("b1", assembled=2)
    old_cart = carts.create_cart("web")
    carts.add_product(old_cart, rose.id, 3)  # положили, пока раздел был включён

    _switch(owner, flowers_section_enabled=False)
    assert web.get(f"{API}/settings/public").json()["flowers_section_enabled"] is False
    assert web.get(f"{API}/catalog/products?type=flower,greenery").json() == []
    types = {p["type"] for p in web.get(f"{API}/catalog/products").json()}
    assert "flower" not in types and "greenery" not in types and "bouquet" in types
    assert web.get(f"{API}/catalog/products/fl-rose").status_code == 404
    assert web.get(f"{API}/catalog/categories?type=flower").json() == []

    token = web.post(f"{API}/carts", format="json").json()["token"]
    r = web.post(f"{API}/carts/{token}/items", {"product_id": rose.id, "quantity": 1}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "section_disabled"
    assert web.post(f"{API}/carts/{token}/items", {"product_id": bouquet.id, "quantity": 1},
                    format="json").status_code == 200

    # то, что уже лежит в корзине, помечено и не оформляется
    line = carts.summary(old_cart)["items"][0]
    assert line["ok"] is False and "поштучно" in line["error"]
    with pytest.raises(carts.SectionDisabled):
        orders.place_order(old_cart, shop.order_data())

    # конструктор и продажа в магазине цветы по-прежнему используют
    assert web.get(f"{API}/constructor/options").json()["flowers"]
    r = owner.post(f"{API}/admin/store-sale", {"lines": [{"product_id": rose.id, "quantity": 1}], "payment": "cash"},
                   format="json")
    assert r.status_code == 201, r.content

    _switch(owner, flowers_section_enabled=True)
    assert web.get(f"{API}/catalog/products/fl-rose").status_code == 200
    assert carts.summary(old_cart)["items"][0]["ok"] is True


def test_constructor_section_off_blocks_custom_bouquets(shop, web, staff):
    owner = staff_client("owner")
    comp = shop.custom_composition()
    old_cart = carts.create_cart("web")
    carts.add_custom_bouquet(old_cart, comp, 1)

    _switch(owner, constructor_section_enabled=False)
    assert web.get(f"{API}/settings/public").json()["constructor_section_enabled"] is False
    for r in (web.get(f"{API}/constructor/options"),
              web.post(f"{API}/constructor/quote", {"composition": comp}, format="json")):
        assert r.status_code == 409 and r.json()["error"]["code"] == "section_disabled"
    token = web.post(f"{API}/carts", format="json").json()["token"]
    r = web.post(f"{API}/carts/{token}/custom-bouquet", {"composition": comp}, format="json")
    assert r.status_code == 409

    line = carts.summary(old_cart)["items"][0]
    assert line["ok"] is False and line["total"] == 0 and "недоступна" in line["error"]
    with pytest.raises(carts.SectionDisabled):
        orders.place_order(old_cart, shop.order_data())
    # цветы поштучно при этом продаются
    rose = Product.objects.get(slug="fl-rose")
    assert web.post(f"{API}/carts/{token}/items", {"product_id": rose.id, "quantity": 1},
                    format="json").status_code == 200

    _switch(owner, constructor_section_enabled=True)
    assert web.get(f"{API}/constructor/options").status_code == 200
    assert carts.summary(old_cart)["items"][0]["ok"] is True


def test_only_owner_switches_sections(shop, staff):
    florist = staff_client("florist")
    r = florist.patch(f"{API}/admin/settings", {"flowers_section_enabled": False}, format="json")
    assert r.status_code == 403
    assert APIClient().get(f"{API}/settings/public").json()["flowers_section_enabled"] is True
