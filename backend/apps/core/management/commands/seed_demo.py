"""Демо-данные «Цветы Урала». Все записи помечены is_demo=True.

    python manage.py seed_demo          # заполнить, если демо-данных ещё нет
    python manage.py seed_demo --reset  # очистить БД и заполнить заново
"""
import os
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.carts import services as carts
from apps.catalog.models import Product, ProductImage
from apps.core.models import ShopSettings, User
from apps.core.utils import local_today
from apps.customers.models import Customer, CustomerChannel
from apps.delivery import geo
from apps.delivery.models import DeliverySlot, DeliveryZone
from apps.delivery.zones_data import DEMO_ZONES, ZONE_COLORS, demo_polygons
from apps.delivery.services import slots_for_date
from apps.inventory import services as inv
from apps.inventory.models import InventoryItem
from apps.notifications.models import Notification
from apps.orders import services as orders
from apps.orders.models import Order
from apps.payments import services as payments
from apps.recipes import services as recipes

C = InventoryItem.Category
U = InventoryItem.Unit
S = Order.Status

DEMO_NOTE = "Демо-данные. Фото — AI-сгенерированные демо-изображения, не фото реальных букетов."

# key, sku, name, unit, purchase, sale, stock, species, color, hex, height
FLOWERS = [
    ("f01", "FL-ROSE-RED", "Роза красная «Ред Наоми» 60 см", 9000, 19000, 140, "Роза", "Красный", "#A3172B", 60),
    ("f02", "FL-ROSE-WHT", "Роза белая «Аваланш» 60 см", 8500, 18000, 80, "Роза", "Белый", "#F4F1EA", 60),
    ("f03", "FL-ROSE-PNK", "Роза розовая «Свит Аваланш» 60 см", 8500, 18000, 70, "Роза", "Розовый", "#F2B8C6", 60),
    ("f04", "FL-ROSE-GRD", "Роза пионовидная кремовая", 22000, 45000, 30, "Роза пионовидная", "Кремовый", "#F3E4C8", 50),
    ("f05", "FL-ROSE-SPR", "Роза кустовая розовая", 9000, 19000, 40, "Роза кустовая", "Розовый", "#EFA7BC", 50),
    ("f06", "FL-TUL-RED", "Тюльпан красный", 4500, 9900, 60, "Тюльпан", "Красный", "#D3232F", 40),
    ("f07", "FL-TUL-WHT", "Тюльпан белый", 4500, 9900, 50, "Тюльпан", "Белый", "#F7F5EE", 40),
    ("f08", "FL-PEONY-PNK", "Пион розовый «Сара Бернар»", 18000, 39000, 30, "Пион", "Розовый", "#F1B3C8", 50),
    ("f09", "FL-HYD-BLU", "Гортензия голубая", 30000, 65000, 14, "Гортензия", "Голубой", "#9DB8E3", 50),
    ("f10", "FL-EUS-WHT", "Эустома белая", 12000, 25000, 45, "Эустома", "Белый", "#F6F4EC", 60),
    ("f11", "FL-CHR-WHT", "Хризантема кустовая белая", 7000, 15000, 40, "Хризантема", "Белый", "#F2F1E6", 60),
    ("f12", "FL-ALS-PNK", "Альстромерия розовая", 6000, 13000, 50, "Альстромерия", "Розовый", "#EE9DB5", 60),
    ("f13", "FL-GER-MIX", "Гербера", 5000, 11000, 40, "Гербера", "Микс", "#F6B23C", 50),
    ("f14", "FL-RAN-PCH", "Ранункулюс персиковый", 11000, 24000, 30, "Ранункулюс", "Персиковый", "#F6B48F", 40),
    ("f15", "FL-LIL-WHT", "Лилия белая «Касабланка»", 20000, 42000, 12, "Лилия", "Белый", "#F7F4EA", 70),
]
GREENERY = [
    ("g01", "GR-EUC", "Эвкалипт цинерея", 6000, 12000, 50, "#8FA8A0"),
    ("g02", "GR-PIST", "Фисташка (писташ)", 4000, 9000, 50, "#3F6B3A"),
    ("g03", "GR-RUSC", "Рускус итальянский", 4000, 8000, 40, "#2F6B2F"),
    ("g04", "GR-GYPS", "Гипсофила", 7000, 15000, 30, "#F3F1EA"),
]
PACKAGING = [
    ("p01", "PK-KRAFT", "Крафт-бумага", 3000, 15000, 120, "#C49A6C"),
    ("p02", "PK-FILM-PWD", "Плёнка матовая «Пудра»", 4000, 20000, 100, "#EBC7C8"),
    ("p03", "PK-FELT-OLV", "Фетр оливковый", 7000, 30000, 60, "#66783E"),
    ("p04", "PK-HATBOX", "Шляпная коробка (бархат, пудра)", 35000, 90000, 15, "#C99A9E"),
]
RIBBONS = [
    ("r01", "RB-SATIN-PWD", "Лента атласная пудровая", 1500, 8000, 200, "#C9918F"),
    ("r02", "RB-SILK-SAGE", "Лента шёлковая шалфей", 6000, 25000, 80, "#9DB59A"),
    ("r03", "RB-JUTE", "Шпагат джутовый", 800, 6000, 200, "#B8A07A"),
]
CARDS = [
    ("c01", "CD-BDAY", "Открытка «С днём рождения»", 3000, 15000, 60),
    ("c02", "CD-LOVE", "Открытка «С любовью»", 3000, 15000, 60),
    ("c03", "CD-JUST", "Открытка «Просто так»", 3000, 15000, 60),
]
ADDONS = [
    ("a01", "AD-CHOCO", "Конфеты ручной работы, 16 шт.", 70000, 149000, 10, "Нежные трюфели в подарочной коробке."),
    ("a02", "AD-BEAR", "Плюшевый мишка, 30 см", 90000, 199000, 6, "Мягкий мишка с пудровым бантом."),
    ("a03", "AD-VASE", "Ваза стеклянная, 25 см", 55000, 129000, 8, "Прозрачная ваза-цилиндр с тяжёлым дном."),
]
# key, sku, slug, name, category, sale, featured, made_to_order, preassembled, recipe{sku: qty}, short, desc
BOUQUETS = [
    ("b01", "BQ-001", "alye-parusa", "Алые паруса", "Розы", 590000, True, True, 3,
     {"FL-ROSE-RED": 25, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "25 красных роз «Ред Наоми» в пудровой упаковке",
     "Классика, которая всегда попадает в сердце: 25 насыщенных красных роз длиной 60 см в матовой пудровой плёнке с атласной лентой."),
    ("b02", "BQ-002", "beloe-oblako", "Белое облако", "Розы", 390000, True, True, 2,
     {"FL-ROSE-WHT": 15, "GR-EUC": 5, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "15 белых роз с эвкалиптом",
     "Светлый и свежий букет: белые розы «Аваланш» и серебристый эвкалипт цинерея. Подходит для любого повода."),
    ("b03", "BQ-003", "nezhnost", "Нежность", "Розы", 490000, True, True, 2,
     {"FL-ROSE-PNK": 21, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "21 розовая роза в матовой плёнке",
     "Округлый букет из 21 нежно-розовой розы — мягкий, романтичный и очень фотогеничный."),
    ("b04", "BQ-004", "101-roza", "101 роза", "Розы", 1990000, True, True, 0,
     {"FL-ROSE-RED": 101, "RB-SATIN-PWD": 2},
     "Большой букет из 101 красной розы",
     "Тот самый жест, который запоминается надолго. Собираем под заказ из свежих роз «Ред Наоми»."),
    ("b05", "BQ-005", "pionovyy-rassvet", "Пионовый рассвет", "Пионы", 690000, True, True, 0,
     {"FL-PEONY-PNK": 7, "FL-ROSE-GRD": 5, "GR-EUC": 4, "PK-KRAFT": 2, "RB-JUTE": 1},
     "Пионы, пионовидные розы и эвкалипт в крафте",
     "Сезонный хит: розовые пионы «Сара Бернар», кремовые пионовидные розы и эвкалипт в натуральном крафте."),
    ("b06", "BQ-006", "oblako-pionov", "Облако пионов", "Пионы", 650000, False, True, 0,
     {"FL-PEONY-PNK": 15, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "15 пышных розовых пионов",
     "Воздушное облако из 15 розовых пионов в лавандовой упаковке."),
    ("b07", "BQ-007", "vesenniy-etyud", "Весенний этюд", "Тюльпаны", 249000, True, True, 3,
     {"FL-TUL-RED": 8, "FL-TUL-WHT": 7, "GR-PIST": 3, "PK-KRAFT": 2, "RB-JUTE": 1},
     "Красные и белые тюльпаны с фисташкой",
     "Яркий весенний букет из 15 тюльпанов с зеленью фисташки в крафтовой бумаге."),
    ("b08", "BQ-008", "belye-tyulpany", "Белые тюльпаны", "Тюльпаны", 329000, False, True, 0,
     {"FL-TUL-WHT": 25, "PK-FILM-PWD": 1, "RB-SILK-SAGE": 1},
     "25 белых тюльпанов с шёлковой лентой",
     "Минималистичный букет из 25 белоснежных тюльпанов с лентой цвета шалфея."),
    ("b09", "BQ-009", "uralskiy-rassvet", "Уральский рассвет", "Авторские", 520000, True, True, 1,
     {"FL-RAN-PCH": 5, "FL-ROSE-SPR": 3, "FL-EUS-WHT": 3, "FL-ROSE-GRD": 2, "GR-PIST": 3, "PK-FILM-PWD": 2,
      "RB-SATIN-PWD": 1},
     "Авторский букет в рассветных тонах",
     "Ранункулюсы, кустовые розы, эустома и пионовидные розы — наш фирменный букет в тонах уральского рассвета."),
    ("b10", "BQ-010", "provans", "Прованс", "Авторские", 380000, False, True, 0,
     {"FL-EUS-WHT": 9, "GR-GYPS": 3, "PK-FELT-OLV": 1, "RB-JUTE": 1},
     "Эустома и гипсофила в оливковом фетре",
     "Нежная эустома с облаком гипсофилы в оливковом фетре — лёгкий букет в стиле Прованс."),
    ("b11", "BQ-011", "malahitovaya-shkatulka", "Малахитовая шкатулка", "Авторские", 560000, True, True, 0,
     {"FL-ROSE-WHT": 9, "FL-EUS-WHT": 5, "GR-RUSC": 4, "GR-PIST": 3, "GR-EUC": 3, "PK-FELT-OLV": 2,
      "RB-SILK-SAGE": 1},
     "Белые розы и эустома в изумрудной зелени",
     "Бело-зелёный букет по мотивам уральских сказов: белые розы, эустома, рускус, фисташка и эвкалипт."),
    ("b12", "BQ-012", "chistoe-nebo", "Чистое небо", "Авторские", 450000, False, True, 0,
     {"FL-HYD-BLU": 3, "FL-ROSE-WHT": 5, "GR-EUC": 3, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "Голубые гортензии с белыми розами",
     "Три облака голубой гортензии, белые розы и эвкалипт — свежо, как небо над Исетью."),
    ("b13", "BQ-013", "solnechnyy-den", "Солнечный день", "Моно", 260000, False, True, 2,
     {"FL-GER-MIX": 13, "GR-PIST": 4, "PK-KRAFT": 2, "RB-JUTE": 1},
     "Яркие герберы с фисташкой",
     "13 солнечных гербер в жёлто-оранжевой гамме — поднимают настроение с первого взгляда."),
    ("b14", "BQ-014", "kamennyy-tsvetok", "Каменный цветок", "Авторские", 480000, False, True, 0,
     {"FL-RAN-PCH": 15, "GR-EUC": 4, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "Персиковые ранункулюсы с эвкалиптом",
     "Изысканный букет из 15 персиковых ранункулюсов — многослойные лепестки, как резьба по камню."),
    ("b15", "BQ-015", "shlyapnaya-korobka-pudra", "Шляпная коробка «Пудра»", "В коробке", 650000, True, True, 1,
     {"FL-ROSE-PNK": 15, "FL-ROSE-SPR": 6, "GR-EUC": 3, "PK-HATBOX": 1},
     "Розы и кустовые розы в бархатной коробке",
     "Розовые и кустовые розы в бархатной шляпной коробке пудрового цвета. Не нужна ваза."),
    ("b16", "BQ-016", "korzina-izobilie", "Корзина «Изобилие»", "В коробке", 890000, False, True, 0,
     {"FL-ROSE-PNK": 7, "FL-ROSE-GRD": 4, "FL-CHR-WHT": 4, "FL-ALS-PNK": 5, "FL-EUS-WHT": 4, "GR-EUC": 5,
      "RB-SATIN-PWD": 1},
     "Плетёная корзина с розами, хризантемами и альстромерией",
     "Щедрая композиция в плетёной корзине — для юбилеев и больших праздников."),
    ("b17", "BQ-017", "hrizantemy", "Хризантемы", "Моно", 230000, False, True, 2,
     {"FL-CHR-WHT": 9, "PK-KRAFT": 2, "RB-SILK-SAGE": 1},
     "Белые кустовые хризантемы в крафте",
     "Свежие и стойкие кустовые хризантемы — простой и душевный подарок."),
    ("b18", "BQ-018", "alstromeriya", "Альстромерия", "Моно", 240000, False, True, 0,
     {"FL-ALS-PNK": 15, "PK-FILM-PWD": 2, "RB-SATIN-PWD": 1},
     "15 розовых альстромерий",
     "Моно-букет из розовой альстромерии в пудровой плёнке. Долго стоит в вазе."),
    ("b19", "BQ-019", "kompliment", "Комплимент", "Комплименты", 129000, True, True, 5,
     {"FL-ROSE-GRD": 1, "FL-ROSE-WHT": 2, "GR-EUC": 1, "GR-GYPS": 1, "PK-KRAFT": 1, "RB-JUTE": 1},
     "Маленький букет из трёх роз",
     "Небольшой знак внимания: кремовые розы, эвкалипт и гипсофила в крафте."),
    ("b20", "BQ-020", "nevesta", "Невеста", "Свадебные", 790000, False, False, 0,
     {"FL-ROSE-GRD": 9, "FL-EUS-WHT": 5, "GR-GYPS": 2, "RB-SATIN-PWD": 2},
     "Свадебный букет из пионовидных роз и эустомы",
     "Классический круглый свадебный букет. Собирается только по предварительному согласованию с флористом."),
]
ZONES = DEMO_ZONES  # Кондратово, районы Перми и пригород; границы — apps/delivery/data/perm_zones.json
SLOTS = [("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "18:00"), ("18:00", "21:00")]
# В админке после заполнения есть только владелец. Флористов и курьеров владелец заводит сам
# (Админка → Сотрудники). Демо-курьеры ниже нужны лишь для истории демо-заказов и сразу удаляются —
# войти под ними нельзя.
OWNER = ("owner", User.Role.OWNER, "Анна", "Соколова", "+79000001000")
DEMO_OWNER_PASSWORD = "owner12345"
DEMO_COURIERS = [("demo-courier-1", "Дмитрий", "Петров"), ("demo-courier-2", "Алексей", "Смирнов")]
CUSTOMERS = [
    ("Елена Кузнецова", "+79000000001", "elena@example.com"),
    ("Ольга Морозова", "+79000000002", "olga@example.com"),
    ("Игорь Волков", "+79000000003", "igor@example.com"),
    ("Наталья Лебедева", "+79000000004", "natalia@example.com"),
    ("Сергей Новиков", "+79000000005", "sergey@example.com"),
]
# Демо-адреса с координатами (проверены геокодером OpenStreetMap)
ADDRESSES = [
    ("Кондратово, Красавинская улица, 8", 57.98832, 56.12075),
    ("Пермь, шоссе Космонавтов, 111", 57.99078, 56.20541),
    ("Кондратово, Камская улица, 5Б", 57.97888, 56.1053),
    ("Пермь, улица Ленина, 50", 58.0119, 56.2424),
    ("Пермь, улица Мира, 41", 57.97662, 56.18713),
    ("Пермь, Комсомольский проспект, 30", 58.01018, 56.24046),
]


def demo_constructor_image(key):
    """Путь к демо-фото для конструктора (вырезанный бутон / текстура упаковки), если оно есть."""
    for ext in ("webp", "png", "jpg"):
        if (Path(settings.DEMO_MEDIA_ROOT) / "constructor" / f"{key}.{ext}").is_file():
            return f"constructor/{key}.{ext}"
    return ""


def attach_constructor_images():
    """Для уже заполненной базы: копирует демо-фото конструктора и привязывает их к демо-товарам без фото.
    Повторный запуск ничего не меняет; фото, загруженные флористом, не трогаются."""
    src = Path(settings.DEMO_MEDIA_ROOT) / "constructor"
    if not src.is_dir():
        return 0
    dst = Path(settings.MEDIA_ROOT) / "constructor"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*"):
        if f.is_file() and not (dst / f.name).exists():
            shutil.copy2(f, dst / f.name)
    n = 0
    for p in Product.objects.filter(is_demo=True, constructor_image="").prefetch_related("images"):
        first = p.images.first()
        key = Path(first.image.name).stem if first else ""
        cut = demo_constructor_image(key) if key else ""
        if cut:
            Product.objects.filter(pk=p.pk).update(constructor_image=cut)
            n += 1
    return n


class Command(BaseCommand):
    help = "Заполняет базу демо-данными магазина «Цветы Урала»"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Полностью очистить БД перед заполнением")
        parser.add_argument("--if-empty", action="store_true", help="Заполнить только если в БД нет товаров")

    def handle(self, *args, reset=False, if_empty=False, **kw):
        if reset:
            self.stdout.write("Очистка базы…")
            call_command("flush", interactive=False, verbosity=0)
        elif Product.objects.exists():
            n = attach_constructor_images()
            if n:
                self.stdout.write(f"Добавлены фото для конструктора: {n}")
            if self.about():
                self.stdout.write("Заполнена страница «О нас» (демо-текст и фото)")
            self.stdout.write(self.style.WARNING("Товары уже есть — пропускаю (используйте --reset для пересоздания)."))
            return
        self.media()
        with transaction.atomic():
            self.settings()
            self.users()
            self.catalog()
            self.delivery()
            self.customers()
            self.about()
        # исторические демо-заказы включают оплату при получении; после заполнения — снова только онлайн
        ShopSettings.objects.filter(pk=1).update(allow_cash_on_delivery=True)
        try:
            self.orders()
        finally:
            ShopSettings.objects.filter(pk=1).update(allow_cash_on_delivery=False)
            User.objects.filter(username__in=[c[0] for c in DEMO_COURIERS]).delete()
            Order.objects.update(is_demo=True)  # удаляются командой clear_demo перед запуском магазина
        pwd_note = "пароль из OWNER_PASSWORD" if os.environ.get("OWNER_PASSWORD") else f"пароль {DEMO_OWNER_PASSWORD}"
        self.stdout.write(self.style.SUCCESS(
            f"Готово: {Product.objects.count()} товаров, {Order.objects.count()} заказов. "
            f"Вход в админку: логин owner, {pwd_note}. Смените пароль: Админка → «Сменить пароль»."))

    # ------------------------------------------------------------------ media
    def media(self):
        src = Path(settings.DEMO_MEDIA_ROOT)
        dst = Path(settings.MEDIA_ROOT)
        for sub, target in (("products", "products"), ("brand", "branding"), ("constructor", "constructor")):
            (dst / target).mkdir(parents=True, exist_ok=True)
            for f in (src / sub).glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst / target / f.name)

    def about(self):
        """Демо-содержимое страницы «О нас»; не трогает то, что владелец уже заполнил."""
        from apps.core.models import AboutPhoto

        s = ShopSettings.load()
        if s.about_text.strip() or AboutPhoto.objects.exists():
            return False
        s.about_title = "О нас"
        s.about_lead = "Небольшая цветочная мастерская в Кондратово (ЖК «Медовый»): собираем букеты из свежих цветов к нужному часу."
        s.about_text = (
            "Мы работаем с цветами каждый день: принимаем поставки утром, сами обрабатываем стебли "
            "и следим за температурой в холодильной витрине.\n\n"
            "Готовые букеты собираем по рецептурам, а индивидуальный букет можно составить в конструкторе — "
            "флорист проверит состав и подтвердит заказ.\n\n"
            "Доставляем по Кондратово и Медовому в выбранный интервал, перед выездом пришлём фото букета. "
            "Самовывоз — из мастерской, без очереди.\n\n"
            "Это демо-текст: владелец меняет его в админке, раздел «О нас»."
        )
        s.save(update_fields=["about_title", "about_lead", "about_text", "updated_at"])
        src = Path(settings.DEMO_MEDIA_ROOT)
        dst = Path(settings.MEDIA_ROOT) / "about"
        dst.mkdir(parents=True, exist_ok=True)
        photos = [("products/b02.jpg", "Букеты собираем по рецептурам"),
                  ("products/b05.jpg", "Сезонные цветы — каждую неделю"),
                  ("products/b08.jpg", "Упаковка и ленты — под настроение"),
                  ("brand/banner.jpg", "«Цветы Урала» — цветочная мастерская в Кондратово")]
        for n, (rel, caption) in enumerate(photos):
            f = src / rel
            if not f.is_file():
                continue
            name = f"demo-{n + 1}{f.suffix}"
            shutil.copy2(f, dst / name)
            AboutPhoto.objects.create(image=f"about/{name}", caption=caption, sort_order=(n + 1) * 10, is_demo=True)
        return True

    def settings(self):
        s = ShopSettings.load()
        s.shop_name = "Цветы Урала"
        s.tagline = "Цветочный магазин"
        s.city = "Кондратово"
        s.address = "Пермский край, д. Кондратово, ЖК «Медовый» (демо-адрес — укажите точный в настройках)"
        s.phone = "+7 (900) 000-00-00"
        s.email = "hello@example.com"
        s.working_hours = "Ежедневно 08:00–21:00"
        s.shop_lat, s.shop_lon = 57.98644, 56.11818  # ЖК «Медовый», Кондратово
        s.allow_cash_on_delivery = False  # по умолчанию — только онлайн-оплата
        s.primary_color, s.accent_color, s.background_color = "#3E5B36", "#9C6FA0", "#FAF7F1"
        s.save()

    def users(self):
        username, role, first, last, phone = OWNER
        owner = User.objects.filter(username=os.environ.get("OWNER_USERNAME") or username).first()
        if owner is None:
            owner = User(username=os.environ.get("OWNER_USERNAME") or username, role=role, first_name=first,
                         last_name=last, phone=phone, is_demo=False, email="", is_staff=True,
                         is_superuser=True)
            owner.set_password(os.environ.get("OWNER_PASSWORD") or DEMO_OWNER_PASSWORD)
            owner.save()
        self.owner = owner
        self.florist = owner  # демо-действия «флориста» выполняет владелец
        self.couriers = []
        for uname, first, last in DEMO_COURIERS:
            c = User(username=uname, role=User.Role.COURIER, first_name=first, last_name=last, is_demo=True,
                     is_active=True)
            c.set_unusable_password()  # войти нельзя; учётка удаляется сразу после демо-заказов
            c.save()
            self.couriers.append(c)

    def _item(self, sku, name, cat, unit, purchase, sale, min_stock=0):
        return InventoryItem.objects.create(sku=sku, name=name, category=cat, unit=unit, purchase_price=purchase,
                                            sale_price=sale, min_stock=min_stock, is_demo=True)

    def _product(self, key, item, ptype, slug, name, order, **kw):
        p = Product.objects.create(slug=slug, name=name, type=ptype, inventory_item=item, sort_order=order,
                                   is_demo=True, photo_credit="AI-сгенерированное демо-изображение"
                                   if not key.startswith("c") else "Демо-изображение (Pillow)", **kw)
        ProductImage.objects.create(product=p, image=f"products/{key}.jpg", alt=name, sort_order=0)
        cut = demo_constructor_image(key)
        if cut:
            Product.objects.filter(pk=p.pk).update(constructor_image=cut)
        return p

    def catalog(self):
        supply = []
        self.items = {}
        for i, (key, sku, name, pur, sale, stock, species, color, hx, h) in enumerate(FLOWERS):
            it = self._item(sku, name, C.FLOWER, U.STEM, pur, sale, min_stock=10)
            self.items[sku] = it
            self._product(key, it, Product.Type.FLOWER, f"flower-{sku.lower()}", name, 200 + i, species=species,
                          color=color, color_hex=hx, height_cm=h, constructor_enabled=True,
                          category=species, short_description=f"{species}, {color.lower()}, {h} см — цена за стебель")
            supply.append(inv.SupplyLine(it.id, stock, pur))
        for i, (key, sku, name, pur, sale, stock, hx) in enumerate(GREENERY):
            it = self._item(sku, name, C.GREENERY, U.BRANCH, pur, sale, min_stock=10)
            self.items[sku] = it
            self._product(key, it, Product.Type.GREENERY, f"greenery-{sku.lower()}", name, 300 + i, color_hex=hx,
                          constructor_enabled=True, category="Зелень", short_description="Цена за ветку")
            supply.append(inv.SupplyLine(it.id, stock, pur))
        for i, (key, sku, name, pur, sale, stock, hx) in enumerate(PACKAGING):
            it = self._item(sku, name, C.PACKAGING, U.SHEET if i < 3 else U.PCS, pur, sale, min_stock=10)
            self.items[sku] = it
            self._product(key, it, Product.Type.PACKAGING, f"packaging-{sku.lower()}", name, 400 + i, color_hex=hx,
                          constructor_enabled=True, category="Упаковка")
            supply.append(inv.SupplyLine(it.id, stock, pur))
        for i, (key, sku, name, pur, sale, stock, hx) in enumerate(RIBBONS):
            it = self._item(sku, name, C.RIBBON, U.CUT, pur, sale, min_stock=20)
            self.items[sku] = it
            self._product(key, it, Product.Type.RIBBON, f"ribbon-{sku.lower()}", name, 500 + i, color_hex=hx,
                          constructor_enabled=True, category="Ленты")
            supply.append(inv.SupplyLine(it.id, stock, pur))
        for i, (key, sku, name, pur, sale, stock) in enumerate(CARDS):
            it = self._item(sku, name, C.CARD, U.PCS, pur, sale, min_stock=10)
            self.items[sku] = it
            self._product(key, it, Product.Type.CARD, f"card-{sku.lower()}", name, 600 + i,
                          constructor_enabled=True, category="Открытки",
                          short_description="Подпишем от руки — текст укажите при оформлении")
            supply.append(inv.SupplyLine(it.id, stock, pur))
        for i, (key, sku, name, pur, sale, stock, desc) in enumerate(ADDONS):
            it = self._item(sku, name, C.ADDON, U.PCS, pur, sale, min_stock=2)
            self.items[sku] = it
            self._product(key, it, Product.Type.ADDON, f"addon-{sku.lower()}", name, 700 + i, category="К букету",
                          short_description=desc, description=desc)
            supply.append(inv.SupplyLine(it.id, stock, pur))
        self._item("CS-TAPE", "Тейп-лента флористическая", C.CONSUMABLE, U.PCS, 15000, None, min_stock=2)
        inv.receive_supply(supply, user=self.owner, reason="Демо: стартовая поставка")
        # небольшое списание для истории движений
        inv.write_off(self.items["FL-TUL-RED"].id, 2, "Демо: брак при приёмке", user=self.florist)

        self.bouquets = {}
        for i, (key, sku, slug, name, cat, sale, featured, mto, pre, comp, short, desc) in enumerate(BOUQUETS):
            it = self._item(sku, name, C.BOUQUET, U.PCS, 0, sale)
            p = self._product(key, it, Product.Type.BOUQUET, slug, name, 10 + i, category=cat, is_featured=featured,
                              allow_made_to_order=mto, short_description=short, description=desc,
                              height_cm=60 if "101" not in name else 80)
            r = recipes.get_or_create_recipe(it)
            recipes.set_components(r, [{"item_id": self.items[s].id, "quantity": q} for s, q in comp.items()])
            InventoryItem.objects.filter(pk=it.pk).update(purchase_price=recipes.cost(r))
            if pre:
                recipes.assemble(r, pre, user=self.florist)
            self.bouquets[slug] = p

    def delivery(self):
        polygons = demo_polygons()
        for name, desc, price, free_from, order in ZONES:
            DeliveryZone.objects.create(name=name, description=desc, price=price, free_from=free_from, sort_order=order,
                                        polygons=polygons.get(name, []), color=ZONE_COLORS.get(name, ""))
        for a, b in SLOTS:
            DeliverySlot.objects.create(start_time=a, end_time=b, capacity=4)

    def customers(self):
        self.custs = []
        for name, phone, email in CUSTOMERS:
            self.custs.append(Customer.objects.create(name=name, phone=phone, email=email, is_demo=True))
        CustomerChannel.objects.create(customer=self.custs[1], channel="telegram", external_id="sim-tg-1001",
                                       chat_id="sim-tg-1001", display_name="Ольга М.", is_simulated=True)
        CustomerChannel.objects.create(customer=self.custs[2], channel="vk", external_id="sim-vk-2001",
                                       chat_id="sim-vk-2001", display_name="Игорь В.", is_simulated=True)

    # ------------------------------------------------------------------ orders
    def _date_slot(self, fulfillment, days=None):
        start = 0 if days is None else days
        for d in range(start, start + 5):
            day = local_today() + timedelta(days=d)
            for s in slots_for_date(day, fulfillment):
                if s["available"]:
                    return day, s["id"]
        raise RuntimeError("Нет доступных интервалов")

    def _order(self, *, channel="web", cust=0, products=(), custom=None, fulfillment="delivery", payment="online",
               days=1, comment="", card_text="", recipient=None):
        customer = None
        if channel != "web":
            link = CustomerChannel.objects.filter(channel=channel).first()
            customer = link.customer if link else None
        cart = carts.create_cart(channel=channel, customer=customer)
        for slug, qty in products:
            p = self.bouquets.get(slug) or Product.objects.get(slug=slug)
            carts.add_product(cart, p.id, qty)
        if custom:
            carts.add_custom_bouquet(cart, custom, 1)
        day, slot_id = self._date_slot(fulfillment, days)
        name, phone, email = CUSTOMERS[cust]
        data = {
            "customer": {"name": name, "phone": phone, "email": email}, "fulfillment": fulfillment,
            "date": day.isoformat(), "slot_id": slot_id, "payment_method": payment, "comment": comment,
            "card_text": card_text, "recipient": recipient or {},
        }
        if fulfillment == "delivery":
            address, lat, lon = ADDRESSES[cust % len(ADDRESSES)]
            data["delivery"] = {"address": address, "lat": lat, "lon": lon, "address_token": geo.sign(address, lat, lon),
                                "apartment": str(10 + cust * 7)}
        return orders.place_order(cart, data, actor_label="демо")

    def _pay(self, order):
        p = order.payments.order_by("-id").first()
        payments.simulator_action(p.token, "succeed")
        order.refresh_from_db()
        return order

    def _go(self, order, *statuses, user=None):
        for st in statuses:
            order = orders.transition(order.id, st, user=user or self.florist)
        return order

    def orders(self):
        own, fl = self.owner, self.florist
        c1, c2 = self.couriers
        # 1. Выполненный онлайн-заказ с доставкой (позавчера)
        o = self._order(products=[("beloe-oblako", 1)], cust=0, days=0, card_text="С днём рождения, мама!")
        o = self._pay(o)
        o = self._go(o, S.ASSEMBLING, S.READY)
        orders.assign_courier(o.id, c1.id, own)
        o = self._go(o, S.HANDED_TO_COURIER, user=c1)
        o = self._go(o, S.DELIVERED, user=c1)
        o = self._go(o, S.COMPLETED, user=own)
        self._age(o, days=2)
        # 2. Самовывоз, оплачен, подтверждён
        o = self._order(products=[("vesenniy-etyud", 1)], cust=3, fulfillment="pickup", days=0)
        self._pay(o)
        # 3. Telegram, оплата при получении → подтверждён → собирается
        o = self._order(channel="telegram", products=[("nezhnost", 1)], cust=1, payment="on_delivery",
                        comment="Позвонить получателю за 30 минут", recipient={"name": "Ирина", "phone": "+79000000011"})
        o = orders.staff_confirm(o.id, fl)
        self._go(o, S.ASSEMBLING)
        # 4. ВКонтакте, оплата при получении, ждёт подтверждения магазина
        self._order(channel="vk", products=[("solnechnyy-den", 1)], cust=2, payment="on_delivery")
        # 5. Сайт, онлайн, ждёт оплаты (резерв 15 минут)
        self._order(products=[("alye-parusa", 1)], cust=4)
        # 6. Индивидуальный букет из конструктора — ждёт подтверждения флориста
        it = self.items
        self._order(custom={"flowers": [{"item_id": it["FL-PEONY-PNK"].id, "quantity": 5},
                                        {"item_id": it["FL-ROSE-GRD"].id, "quantity": 4}],
                            "greenery": [{"item_id": it["GR-EUC"].id, "quantity": 3}],
                            "packaging_id": it["PK-FELT-OLV"].id, "ribbon_id": it["RB-SILK-SAGE"].id,
                            "card_id": it["CD-LOVE"].id, "card_text": "Люблю тебя!",
                            "wishes": "Побольше воздуха, нежные тона"},
                    cust=0, days=1)
        # 7. Предзаказ на дату через 10 дней
        self._order(products=[("pionovyy-rassvet", 1)], cust=3, days=10, comment="Предзаказ на годовщину")
        # 8. В пути у курьера (оплата при получении)
        o = self._order(products=[("kompliment", 2)], cust=4, payment="on_delivery", days=0)
        o = orders.staff_confirm(o.id, fl)
        o = self._go(o, S.ASSEMBLING, S.READY)
        orders.assign_courier(o.id, c2.id, own)
        self._go(o, S.HANDED_TO_COURIER, user=c2)
        # 9. Самовывоз — готов и ждёт клиента
        o = self._order(products=[("hrizantemy", 1)], cust=1, fulfillment="pickup", days=0)
        o = self._pay(o)
        self._go(o, S.ASSEMBLING, S.READY, S.AWAITING_PICKUP)
        # 10. Отменённый оплаченный заказ с возвратом
        o = self._order(products=[("shlyapnaya-korobka-pudra", 1)], cust=2, days=1)
        o = self._pay(o)
        orders.cancel(o.id, user=own, reason="Клиент передумал (демо)")
        p = o.payments.order_by("-id").first()
        try:
            payments.simulator_action(p.token, "refund_succeed")
        except Exception:
            pass
        # 11. Доставлен курьером, оплата наличными при получении (вчера)
        o = self._order(products=[("hrizantemy", 1), ("addon-ad-choco", 1)], cust=3, payment="on_delivery", days=0)
        o = orders.staff_confirm(o.id, fl)
        o = self._go(o, S.ASSEMBLING, S.READY)
        orders.assign_courier(o.id, c1.id, own)
        self._go(o, S.HANDED_TO_COURIER, S.DELIVERED, user=c1)
        self._age(o, days=1)
        # 12. Подтверждён, доставка завтра (курьер назначен)
        o = self._order(products=[("malahitovaya-shkatulka", 1)], cust=0, days=1)
        o = self._pay(o)
        orders.assign_courier(o.id, c1.id, own)
        # 13–14. Продажи в магазине
        o = orders.store_sale([{"product_id": self.bouquets["kompliment"].id, "quantity": 1}], "card", fl)
        self._age(o, days=3)
        orders.store_sale([{"product_id": self.bouquets["vesenniy-etyud"].id, "quantity": 1},
                           {"product_id": Product.objects.get(slug="card-cd-just").id, "quantity": 1}], "cash", fl)
        # демо-уведомления по умолчанию не должны висеть как «необработанные»
        Notification.objects.filter(channel="staff").update(is_handled=True)

    def _age(self, order, days):
        """Сдвигает дату создания демо-заказа в прошлое (для графиков и истории)."""
        when = timezone.now() - timedelta(days=days, hours=2)
        Order.objects.filter(pk=order.pk).update(created_at=when)
