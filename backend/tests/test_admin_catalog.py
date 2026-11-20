"""Админка: категории, «О нас», районы, склад владельца, проверка данных форм."""
import os
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

from apps.catalog import builder
from apps.catalog.models import Category, Product
from apps.delivery.models import DeliveryZone
from apps.inventory.models import InventoryItem, StockBalance

from .conftest import staff_client

pytestmark = pytest.mark.django_db


def _img(size=(300, 360), fmt="JPEG", bud=True):
    im = Image.new("RGB", size, (239, 230, 216))
    if bud:
        ImageDraw.Draw(im).ellipse((90, 80, 210, 200), fill=(170, 20, 40))
    buf = BytesIO()
    im.save(buf, fmt)
    return SimpleUploadedFile(f"p.{fmt.lower()}", buf.getvalue(), content_type=f"image/{fmt.lower()}")


# ------------------------------------------------------------------ категории

def test_florist_manages_bouquet_categories(shop, staff, web):
    b1, b2 = shop.bouquet("b1", assembled=1), shop.bouquet("b2", assembled=1)
    florist = staff_client("florist")
    r = florist.post("/api/v1/admin/categories", {"kind": "bouquet", "name": "  Весенние  "}, format="json")
    assert r.status_code == 201, r.content
    spring = next(c for c in r.json()["categories"] if c["name"] == "Весенние")
    # дубль и слишком короткое название не принимаются, ошибка указывает на поле
    r = florist.post("/api/v1/admin/categories", {"kind": "bouquet", "name": "весенние"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "name"
    assert florist.post("/api/v1/admin/categories", {"kind": "bouquet", "name": "a"}, format="json").status_code == 400
    # добавляем существующие букеты в категорию
    r = florist.post(f"/api/v1/admin/categories/{spring['id']}/products", {"product_ids": [b1.id, b2.id]}, format="json")
    assert r.status_code == 200 and r.json()["updated"] == 2
    # цветок в категорию букетов добавить нельзя
    rose = Product.objects.get(inventory_item=shop.rose)
    r = florist.post(f"/api/v1/admin/categories/{spring['id']}/products", {"product_ids": [rose.id]}, format="json")
    assert r.status_code == 400
    # переименование переносит товары
    r = florist.patch(f"/api/v1/admin/categories/{spring['id']}", {"name": "Весна"}, format="json")
    assert r.status_code == 200
    b1.refresh_from_db()
    assert b1.category == "Весна"
    cats = web.get("/api/v1/catalog/categories?type=bouquet").json()
    assert {"name": "Весна", "count": 2, "in_stock": 2} in cats
    # удаление с переносом в другую категорию
    other = Category.objects.create(kind="bouquet", name="Классика", sort_order=1)
    r = florist.delete(f"/api/v1/admin/categories/{spring['id']}?move_to={other.id}")
    assert r.status_code == 200 and r.json()["moved"] == 2
    b2.refresh_from_db()
    assert b2.category == "Классика"
    assert not Category.objects.filter(name="Весна").exists()


def test_category_order_drives_storefront(shop, staff, web):
    a = Category.objects.create(kind="bouquet", name="Альфа", sort_order=10)
    z = Category.objects.create(kind="bouquet", name="Зета", sort_order=20)
    Product.objects.filter(pk=shop.bouquet("b1", assembled=1).pk).update(category="Альфа")
    Product.objects.filter(pk=shop.bouquet("b2", assembled=1).pk).update(category="Зета")
    florist = staff_client("florist")
    assert [c["name"] for c in web.get("/api/v1/catalog/categories?type=bouquet").json()] == ["Альфа", "Зета"]
    ids = [z.id, a.id] + list(Category.objects.filter(kind="bouquet").exclude(pk__in=[a.id, z.id])
                                .values_list("id", flat=True))
    assert florist.post("/api/v1/admin/categories/order", {"kind": "bouquet", "ids": ids}, format="json").status_code == 200
    assert [c["name"] for c in web.get("/api/v1/catalog/categories?type=bouquet").json()] == ["Зета", "Альфа"]
    # порядок без всех категорий раздела не принимается
    r = florist.post("/api/v1/admin/categories/order", {"kind": "bouquet", "ids": [a.id]}, format="json")
    assert r.status_code == 400


def test_flower_categories_include_greenery_and_courier_has_no_access(shop, staff, web):
    Category.objects.create(kind="flower", name="Зелень", sort_order=10)
    euc = Product.objects.get(inventory_item=shop.euc)
    florist = staff_client("florist")
    cat = Category.objects.get(kind="flower", name="Зелень")
    assert florist.post(f"/api/v1/admin/categories/{cat.id}/products", {"product_ids": [euc.id]},
                        format="json").status_code == 200
    assert {"name": "Зелень", "count": 1, "in_stock": 1} in web.get("/api/v1/catalog/categories?type=flower").json()
    assert staff_client("courier1").get("/api/v1/admin/categories?kind=flower").status_code == 403


def test_product_category_must_exist(shop, staff):
    florist = staff_client("florist")
    rose = Product.objects.get(inventory_item=shop.rose)
    r = florist.patch(f"/api/v1/admin/products/{rose.id}", {"category": "Нет такой"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "category"
    Category.objects.create(kind="flower", name="Роза", sort_order=1)
    r = florist.patch(f"/api/v1/admin/products/{rose.id}", {"category": "роза"}, format="json")
    assert r.status_code == 200 and r.json()["category"] == "Роза"


# ------------------------------------------------------------------ проверка полей товара

@pytest.mark.parametrize("payload,field", [
    ({"name": "x"}, "name"),
    ({"price": -100}, "price"),
    ({"price": "abc"}, "price"),
    ({"height_cm": 2}, "height_cm"),
    ({"color_hex": "red"}, "color_hex"),
    ({"stock": -1}, "stock"),
    ({"stock": 1.5}, "stock"),
    ({"min_stock": "много"}, "min_stock"),
    ({"unit": "kg"}, "unit"),
    ({"sku": "АРТ 1"}, "sku"),
])
def test_product_patch_rejects_invalid_values(shop, staff, payload, field):
    rose = Product.objects.get(inventory_item=shop.rose)
    r = staff_client("florist").patch(f"/api/v1/admin/products/{rose.id}", payload, format="json")
    assert r.status_code == 400, r.content
    assert r.json()["error"]["details"]["field"] == field


def test_florist_creates_packaging_and_ribbon_for_constructor(shop, staff, web):
    florist = staff_client("florist")
    r = florist.post("/api/v1/admin/products", {"type": "packaging", "name": "Матовая бумага лиловая",
                                                "species": "Бумага", "color_hex": "#b9a3d6", "price": 12000,
                                                "stock": 15, "unit": "sheet"}, format="json")
    assert r.status_code == 201, r.content
    pk = r.json()
    assert pk["constructor_enabled"] and pk["color_hex"] == "#B9A3D6" and pk["stock"]["quantity"] == 15
    r = florist.post("/api/v1/admin/products", {"type": "ribbon", "name": "Атлас фиолетовый", "species": "Атлас",
                                                "color_hex": "#6B3FA0", "price": 3000, "stock": 30}, format="json")
    assert r.status_code == 201
    opts = web.get("/api/v1/constructor/options").json()
    assert any(p["name"] == "Матовая бумага лиловая" for p in opts["packaging"])
    assert any(p["name"] == "Атлас фиолетовый" for p in opts["ribbons"])
    # флорист не задаёт закупочную цену
    r = florist.post("/api/v1/admin/products", {"type": "card", "name": "Открытка", "purchase_price": 100}, format="json")
    assert r.status_code == 403


def test_product_delete_removes_unused_and_archives_used(shop, staff):
    florist = staff_client("florist")
    r = florist.post("/api/v1/admin/products", {"type": "card", "name": "Новая открытка", "price": 5000}, format="json")
    new_id = r.json()["id"]
    r = florist.delete(f"/api/v1/admin/products/{new_id}")
    assert r.status_code == 200 and not r.json()["archived"]
    assert not Product.objects.filter(pk=new_id).exists()
    rose = Product.objects.get(inventory_item=shop.rose)  # была поставка — есть история
    r = florist.delete(f"/api/v1/admin/products/{rose.id}")
    assert r.status_code == 200 and r.json()["archived"]
    rose.refresh_from_db()
    assert not rose.is_active and Product.objects.filter(pk=rose.pk).exists()


def test_owner_deletes_any_product_forever(shop, staff, settings, tmp_path):
    from apps.carts import services as carts
    from apps.orders import services as orders
    from apps.orders.models import OrderItem

    settings.MEDIA_ROOT = tmp_path
    owner = staff_client("owner")
    bouquet = shop.bouquet("del", assembled=2)
    r = owner.post(f"/api/v1/admin/products/{bouquet.id}/images", {"image": _img()}, format="multipart")
    assert r.status_code == 200, r.content
    photo = bouquet.images.first().image.path
    order = shop.place((bouquet, 1))
    cart = carts.create_cart("web")
    carts.add_product(cart, bouquet.id, 1)
    # пока заказ не выполнен — товар только снимается с продажи, номер заказа в сообщении
    r = owner.delete(f"/api/v1/admin/products/{bouquet.id}")
    assert r.status_code == 200 and r.json()["archived"] and order.number in r.json()["message"]
    bouquet.refresh_from_db()
    assert not bouquet.is_active
    orders.cancel(order.id, user=staff["owner"], reason="Тест")
    # после отмены владелец удаляет товар навсегда, хотя у него есть продажи и движения склада
    r = owner.delete(f"/api/v1/admin/products/{bouquet.id}")
    assert r.status_code == 200 and not r.json()["archived"], r.content
    assert "навсегда" in r.json()["message"]
    assert not Product.objects.filter(pk=bouquet.pk).exists()
    assert not cart.items.exists()  # строки корзин удалены
    line = OrderItem.objects.get(order=order)
    assert line.product_id is None and line.name == "Букет del"  # в заказе осталось название
    item = InventoryItem.objects.get(pk=bouquet.inventory_item_id)  # складская история — в архиве
    assert not item.is_active
    assert not os.path.exists(photo)
    # цветок из рецептур удаляется с витрины, а складская позиция остаётся рабочей для букетов
    rose = Product.objects.get(inventory_item=shop.rose)
    r = owner.delete(f"/api/v1/admin/products/{rose.id}")
    assert r.status_code == 200 and not r.json()["archived"] and "рецептуры" in r.json()["message"]
    shop.rose.refresh_from_db()
    assert shop.rose.is_active and not Product.objects.filter(pk=rose.pk).exists()
    # новый товар без истории удаляется вместе со складской позицией
    r = owner.post("/api/v1/admin/products", {"type": "card", "name": "Открытка на удаление", "price": 5000, "stock": 3},
                   format="json")
    pid, iid = r.json()["id"], Product.objects.get(pk=r.json()["id"]).inventory_item_id
    assert owner.delete(f"/api/v1/admin/products/{pid}").status_code == 200
    assert not Product.objects.filter(pk=pid).exists() and not InventoryItem.objects.filter(pk=iid).exists()
    # список товаров админки и витрина открываются без удалённых позиций
    assert owner.get("/api/v1/admin/products").status_code == 200
    assert owner.get(f"/api/v1/admin/orders/{order.id}").status_code == 200


def test_custom_bouquet_sketch_survives_flower_deletion(shop, staff):
    from apps.orders import services as orders

    order = shop.place(custom=shop.custom_composition(roses=3))
    orders.cancel(order.id, user=staff["owner"])
    owner = staff_client("owner")
    rose = Product.objects.get(inventory_item=shop.rose)
    assert owner.delete(f"/api/v1/admin/products/{rose.id}").status_code == 200
    assert not Product.objects.filter(pk=rose.pk).exists()
    r = owner.get(f"/api/v1/admin/orders/{order.id}")
    assert r.status_code == 200, r.content
    line = next(i for i in r.json()["items"] if i.get("design"))
    names = {i["id"]: i["name"] for i in line["design"]["items"]}
    assert names[shop.rose.id] == "Роза"  # эскиз заказа по-прежнему знает цветок


# ------------------------------------------------------------------ фото конструктора и кадр

def test_constructor_photo_keeps_source_and_crop_can_be_changed(shop, staff, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.CUTOUT_MODEL_PATH = str(tmp_path / "no-model.onnx")  # без нейросети — простой алгоритм
    florist = staff_client("florist")
    r = florist.post("/api/v1/admin/products", {"type": "flower", "name": "Роза новая", "price": 20000, "stock": 5},
                     format="json")
    pid = r.json()["id"]
    r = florist.post(f"/api/v1/admin/products/{pid}/constructor-image", {"image": _img()}, format="multipart")
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["constructor_source"].startswith("/media/constructor/src/")
    assert set(data["constructor_crop"]) == {"x", "y", "w", "h"}
    first = data["constructor_image"]
    r = florist.post(f"/api/v1/admin/products/{pid}/constructor-image/crop",
                     {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["constructor_crop"] == {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}
    assert r.json()["constructor_image"] != first
    bad = florist.post(f"/api/v1/admin/products/{pid}/constructor-image/crop", {"x": 0, "y": 0, "w": 0.01, "h": 0.01},
                       format="json")
    assert bad.status_code == 400
    # не-изображение отклоняется понятной ошибкой
    junk = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
    r = florist.post(f"/api/v1/admin/products/{pid}/constructor-image", {"image": junk}, format="multipart")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "image"


# ------------------------------------------------------------------ конструктор: без упаковки, отражение

def test_bouquet_without_packaging_and_flip_in_layout(shop):
    comp = {"flowers": [{"item_id": shop.rose.id, "quantity": 5}], "ribbon_id": shop.ribbon.id,
            "layout": [{"item_id": shop.rose.id, "x": 0.5, "y": 0.4, "r": 15, "f": True},
                       {"item_id": shop.rose.id, "x": "nan", "y": 0.4}]}
    q = builder.quote(comp)
    names = [l["name"] for l in q["lines"]]
    assert "Крафт" not in names and "Лента" in names
    norm = builder.normalize_composition(comp)
    assert norm["layout"][0] == {"item_id": shop.rose.id, "x": 0.5, "y": 0.4, "r": 15.0, "f": True}
    assert len(norm["layout"]) == 1


# ------------------------------------------------------------------ «О нас»

def test_about_page_is_owner_only_and_public(shop, staff, web, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    owner, florist = staff_client("owner"), staff_client("florist")
    assert florist.patch("/api/v1/admin/about", {"text": "x"}, format="json").status_code == 403
    assert florist.post("/api/v1/admin/about/photos", {"image": _img()}, format="multipart").status_code == 403
    r = owner.patch("/api/v1/admin/about", {"title": "О мастерской", "lead": "Коротко", "text": "Абзац 1\n\nАбзац 2"},
                    format="json")
    assert r.status_code == 200
    assert owner.patch("/api/v1/admin/about", {"title": ""}, format="json").status_code == 400
    r1 = owner.post("/api/v1/admin/about/photos", {"image": _img(), "caption": "Витрина"}, format="multipart")
    r2 = owner.post("/api/v1/admin/about/photos", {"image": _img(fmt="PNG")}, format="multipart")
    assert r1.status_code == r2.status_code == 201
    ids = [p["id"] for p in r2.json()["photos"]]
    r = owner.post("/api/v1/admin/about/photos/order", {"ids": ids[::-1]}, format="json")
    assert [p["id"] for p in r.json()["photos"]] == ids[::-1]
    pub = web.get("/api/v1/about").json()
    assert pub["title"] == "О мастерской" and pub["text"] == "Абзац 1\n\nАбзац 2" and len(pub["photos"]) == 2
    assert owner.delete(f"/api/v1/admin/about/photos/{ids[0]}").status_code == 200
    assert len(web.get("/api/v1/about").json()["photos"]) == 1


def test_shop_settings_are_owner_only_and_validated(shop, staff):
    owner = staff_client("owner")
    assert staff_client("florist").patch("/api/v1/admin/settings", {"shop_name": "X"}, format="json").status_code == 403
    for payload, field in [({"online_reservation_minutes": 0}, "online_reservation_minutes"),
                           ({"min_custom_stems": 60}, "min_custom_stems"),
                           ({"max_custom_stems": 31}, "max_custom_stems"),  # конструктор — не больше 30 цветков
                           ({"min_custom_stems": 30, "max_custom_stems": 10}, "min_custom_stems"),
                           ({"primary_color": "зелёный"}, "primary_color"),
                           ({"email": "not-mail"}, "email"),
                           ({"telegram_url": "https://evil.example/bot"}, "telegram_url"),
                           ({"phone": "123"}, "phone"),
                           ({"shop_name": ""}, "shop_name")]:
        r = owner.patch("/api/v1/admin/settings", payload, format="json")
        assert r.status_code == 400, payload
        assert r.json()["error"]["details"]["field"] == field
    r = owner.patch("/api/v1/admin/settings", {"telegram_url": "https://t.me/cvety_urala", "min_custom_stems": 5,
                                               "primary_color": "#3e5b36"}, format="json")
    assert r.status_code == 200 and r.json()["primary_color"] == "#3E5B36"


# ------------------------------------------------------------------ районы доставки и интервалы

def test_owner_adds_and_deletes_zones(shop, staff, web):
    owner = staff_client("owner")
    r = owner.post("/api/v1/admin/delivery-zones", {"name": "Пригород", "price": 50000, "color": "#aa3300"},
                   format="json")
    assert r.status_code == 200
    zid = next(z["id"] for z in r.json() if z["name"] == "Пригород")
    assert owner.post("/api/v1/admin/delivery-zones", {"name": "", "price": 1}, format="json").status_code == 400
    assert owner.post("/api/v1/admin/delivery-zones", {"name": "Минус", "price": -5}, format="json").status_code == 400
    # неиспользованная зона удаляется полностью
    r = owner.delete(f"/api/v1/admin/delivery-zones/{zid}")
    assert r.status_code == 200 and not DeliveryZone.objects.filter(pk=zid).exists()
    # зона с доставками уходит в архив и пропадает из настроек и с сайта
    shop.place((shop.bouquet(assembled=1), 1))
    r = owner.delete(f"/api/v1/admin/delivery-zones/{shop.zone.id}")
    assert r.status_code == 200
    shop.zone.refresh_from_db()
    assert shop.zone.is_archived and not shop.zone.is_active
    assert all(z["id"] != shop.zone.id for z in owner.get("/api/v1/admin/delivery-zones").json())
    assert all(z["id"] != shop.zone.id for z in web.get("/api/v1/delivery/zones").json())
    assert staff_client("florist").delete(f"/api/v1/admin/delivery-zones/{shop.zone.id}").status_code == 403


def test_slots_are_validated(shop, staff):
    owner = staff_client("owner")
    assert owner.post("/api/v1/admin/delivery-slots", {"start_time": "12:00", "end_time": "11:00"},
                      format="json").status_code == 400
    assert owner.post("/api/v1/admin/delivery-slots", {"start_time": "25:00", "end_time": "26:00"},
                      format="json").status_code == 400
    r = owner.post("/api/v1/admin/delivery-slots", {"start_time": "10:00", "end_time": "12:00", "capacity": 0},
                   format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "capacity"
    r = owner.post("/api/v1/admin/delivery-slots", {"start_time": "10:00", "end_time": "12:00", "capacity": 3},
                   format="json")
    sid = next(s["id"] for s in r.json() if s["start_time"] == "10:00")
    assert owner.delete(f"/api/v1/admin/delivery-slots/{sid}").status_code == 200


# ------------------------------------------------------------------ склад: справочник владельца

def test_owner_manages_inventory_items(shop, staff):
    owner, florist = staff_client("owner"), staff_client("florist")
    payload = {"name": "Флористическая губка", "category": "consumable", "unit": "pcs", "purchase_price": 4000,
               "min_stock": 5, "quantity": 12}
    assert florist.post("/api/v1/admin/inventory", payload, format="json").status_code == 403
    r = owner.post("/api/v1/admin/inventory", payload, format="json")
    assert r.status_code == 201, r.content
    item = r.json()
    assert item["quantity"] == 12 and item["sku"].startswith("CON-") and item["purchase_price"] == 4000
    r = owner.patch(f"/api/v1/admin/inventory/{item['id']}", {"min_stock": 20, "sku": "SPONGE-1"}, format="json")
    assert r.status_code == 200 and r.json()["low"] and r.json()["sku"] == "SPONGE-1"
    assert owner.patch(f"/api/v1/admin/inventory/{item['id']}", {"sku": "FL-ROSE"}, format="json").status_code == 400
    assert owner.patch(f"/api/v1/admin/inventory/{item['id']}", {"unit": "литр"}, format="json").status_code == 400
    assert florist.patch(f"/api/v1/admin/inventory/{item['id']}", {"min_stock": 1}, format="json").status_code == 403
    # позиция с поставкой уходит в архив, новая без истории — удаляется
    assert owner.post("/api/v1/admin/inventory/supply", {"lines": [{"item_id": item["id"], "quantity": 3}]},
                      format="json").status_code == 200
    r = owner.delete(f"/api/v1/admin/inventory/{item['id']}")
    assert r.status_code == 200 and r.json()["archived"]
    r = owner.post("/api/v1/admin/inventory", {**payload, "name": "Проволока", "quantity": 4}, format="json")
    r = owner.delete(f"/api/v1/admin/inventory/{r.json()['id']}")
    assert r.status_code == 200 and not r.json()["archived"]
    assert not InventoryItem.objects.filter(name="Проволока").exists()


def test_stock_operations_validate_input_and_export_csv(shop, staff):
    florist, owner = staff_client("florist"), staff_client("owner")
    for url, payload, field in [
        ("supply", {"lines": [{"item_id": shop.rose.id, "quantity": 0}]}, "quantity"),
        ("supply", {"lines": []}, "lines"),
        ("supply", {"lines": [{"item_id": 999999, "quantity": 1}]}, "item_id"),
        ("write-off", {"item_id": shop.rose.id, "quantity": 1, "reason": ""}, "reason"),
        ("adjust", {"item_id": shop.rose.id, "delta": 0, "reason": "пересчёт"}, "delta"),
        ("count", {"counts": [{"item_id": shop.rose.id, "counted": -3}]}, "counted"),
    ]:
        r = florist.post(f"/api/v1/admin/inventory/{url}", payload, format="json")
        assert r.status_code == 400, (url, payload, r.content)
        assert r.json()["error"]["details"]["field"] == field, (url, r.json())
    assert florist.post("/api/v1/admin/inventory/write-off", {"item_id": shop.rose.id, "quantity": 2,
                                                              "reason": "Сломан стебель"}, format="json").status_code == 200
    rows = florist.get(f"/api/v1/admin/inventory/movements?item_id={shop.rose.id}&type=write_off").json()
    assert len(rows) == 1 and rows[0]["delta"] == -2 and rows[0]["unit_cost"] is None
    assert florist.get("/api/v1/admin/inventory/movements?date_from=2025-13-01").status_code == 400
    r = owner.get("/api/v1/admin/inventory/movements?export=csv")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("Дата;Позиция;Артикул") and "Сломан стебель" in body
    assert StockBalance.objects.get(item=shop.rose).quantity == 48


# ------------------------------------------------------------------ оформление заказа

@pytest.mark.parametrize("patch,field", [
    ({"customer": {"name": "1234", "phone": "+79001112233"}}, "name"),
    ({"customer": {"name": "Анна", "phone": "+79001112233", "email": "anna@"}}, "email"),
    ({"recipient": {"name": "Иван", "phone": "12"}}, "recipient_phone"),
])
def test_checkout_rejects_invalid_contacts(shop, patch, field):
    from apps.carts import services as carts
    from apps.core.errors import ValidationError
    from apps.orders.services import place_order

    cart = carts.create_cart("web")
    carts.add_product(cart, shop.bouquet(assembled=1).id, 1)
    with pytest.raises(ValidationError) as e:
        place_order(cart, {**shop.order_data(), **patch})
    assert e.value.details.get("field") == field
