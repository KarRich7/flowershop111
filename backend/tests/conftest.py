"""Общие фикстуры: минимальный каталог, клиенты API для сайта, ботов и сотрудников."""
from datetime import time, timedelta

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.carts import services as carts
from apps.catalog.models import Product
from apps.core.models import ShopSettings, User
from apps.core.utils import local_today
from apps.delivery.models import DeliverySlot, DeliveryZone
from apps.inventory import services as inv
from apps.inventory.models import InventoryItem, StockBalance
from apps.orders import services as orders
from apps.recipes import services as recipes

BOT_TOKEN = "test-bot-service-token"
CENTER_SQUARE = [[57.95, 56.05], [57.95, 56.30], [58.05, 56.30], [58.05, 56.05]]  # Кондратово и запад Перми
IN_ZONE = (57.98832, 56.12075)  # Кондратово, Красавинская улица, 8
OUT_OF_ZONE = (58.0822, 55.7479)  # Краснокамск


@pytest.fixture(autouse=True)
def _test_settings(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.BOT_SERVICE_TOKEN = BOT_TOKEN
    settings.BOT_SIMULATOR_ENABLED = True
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.VK_GROUP_TOKEN = ""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.GEOCODER_PROVIDER = "off"  # без сетевых запросов; проверка адреса — через моки в тестах
    settings.MAX_PENDING_ORDERS_PER_PHONE = 0  # во многих тестах один телефон; лимит проверяется в test_security
    settings.ONLINE_PAYMENTS_ENABLED = True
    settings.PAYMENT_PROVIDER = "simulator"
    cache.clear()
    yield
    cache.clear()


class Shop:
    """Тестовый магазин: цветы, зелень, упаковка, лента, открытка, букеты с рецептурами."""

    def __init__(self):
        s = ShopSettings.load()
        s.florist_fee = 30000
        s.allow_cash_on_delivery = True  # сценарии резервов используют оплату при получении; запрет — в отдельных тестах
        s.save()
        self.slot = DeliverySlot.objects.create(start_time=time(9), end_time=time(21), capacity=50)
        self.zone = DeliveryZone.objects.create(name="Центр", price=30000, polygons=[CENTER_SQUARE])
        self.rose = self.material("FL-ROSE", "Роза", InventoryItem.Category.FLOWER, 15000, 50, Product.Type.FLOWER)
        self.euc = self.material("GR-EUC", "Эвкалипт", InventoryItem.Category.GREENERY, 8000, 20, Product.Type.GREENERY)
        self.kraft = self.material("PK-KRAFT", "Крафт", InventoryItem.Category.PACKAGING, 15000, 20,
                                   Product.Type.PACKAGING)
        self.ribbon = self.material("RB-SAT", "Лента", InventoryItem.Category.RIBBON, 5000, 20, Product.Type.RIBBON)
        self.card = self.material("CD-LOVE", "Открытка", InventoryItem.Category.CARD, 10000, 10, Product.Type.CARD)

    def material(self, sku, name, cat, price, stock, ptype):
        item = InventoryItem.objects.create(sku=sku, name=name, category=cat, sale_price=price, purchase_price=price // 2)
        Product.objects.create(slug=sku.lower(), name=name, type=ptype, inventory_item=item, constructor_enabled=True)
        inv.receive_supply([inv.SupplyLine(item.id, stock)])
        return item

    def bouquet(self, slug="b1", *, assembled=0, made_to_order=False, price=300000, roses=3):
        item = InventoryItem.objects.create(sku=f"BQ-{slug}", name=f"Букет {slug}",
                                            category=InventoryItem.Category.BOUQUET, sale_price=price)
        p = Product.objects.create(slug=slug, name=f"Букет {slug}", type=Product.Type.BOUQUET, inventory_item=item,
                                   allow_made_to_order=made_to_order, category="Розы")
        r = recipes.get_or_create_recipe(item)
        recipes.set_components(r, [{"item_id": self.rose.id, "quantity": roses},
                                   {"item_id": self.kraft.id, "quantity": 1}])
        if assembled:
            recipes.assemble(r, assembled)
        return p

    @staticmethod
    def balance(item):
        return StockBalance.objects.get(item=item)

    @staticmethod
    def available(product):
        return carts.product_available(product)

    def custom_composition(self, roses=5):
        return {"flowers": [{"item_id": self.rose.id, "quantity": roses}],
                "greenery": [{"item_id": self.euc.id, "quantity": 2}],
                "packaging_id": self.kraft.id, "ribbon_id": self.ribbon.id, "card_id": self.card.id,
                "card_text": "С любовью"}

    def order_data(self, *, fulfillment="delivery", payment="online", days=1, address="ул. Ленина, 1", key=None):
        data = {"customer": {"name": "Тест Покупатель", "phone": "+7 900 123-45-67"},
                "fulfillment": fulfillment, "date": (local_today() + timedelta(days=days)).isoformat(),
                "slot_id": self.slot.id, "payment_method": payment}
        if fulfillment == "delivery":
            data["delivery"] = {"address": address, "lat": IN_ZONE[0], "lon": IN_ZONE[1]}
        if key:
            data["idempotency_key"] = key
        return data

    def place(self, *lines, channel="web", custom=None, **kw):
        cart = carts.create_cart(channel)
        for product, qty in lines:
            carts.add_product(cart, product.id, qty)
        if custom:
            carts.add_custom_bouquet(cart, custom, 1)
        return orders.place_order(cart, self.order_data(**kw))


@pytest.fixture
def shop(db):
    return Shop()


@pytest.fixture
def web():
    return APIClient()


def bot_client(channel="telegram"):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bot {BOT_TOKEN}", HTTP_X_BOT_CHANNEL=channel)
    return c


@pytest.fixture
def tg():
    return bot_client("telegram")


@pytest.fixture
def vk():
    return bot_client("vk")


def make_user(username, role, password="Strong-pass-123"):
    u = User(username=username, role=role)
    u.set_password(password)
    u.save()
    return u


def staff_client(username, password="Strong-pass-123"):
    c = APIClient()
    r = c.post("/api/v1/admin/auth/login", {"username": username, "password": password}, format="json")
    assert r.status_code == 200, r.content
    assert "token" not in r.json()  # токен — только в HttpOnly-cookie
    assert r.cookies["cu_staff"]["httponly"]
    # клиент хранит cookie cu_staff сам; заголовок ставит сайт — без него cookie для изменений не принимается
    c.credentials(HTTP_X_REQUESTED_WITH="fetch")
    return c


@pytest.fixture
def staff(db):
    owner = make_user("owner", User.Role.OWNER)
    florist = make_user("florist", User.Role.FLORIST)
    c1 = make_user("courier1", User.Role.COURIER)
    c2 = make_user("courier2", User.Role.COURIER)
    return {"owner": owner, "florist": florist, "courier1": c1, "courier2": c2}
