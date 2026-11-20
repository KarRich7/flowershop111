"""Движок диалога для чат-ботов (Telegram и ВК). Не зависит от канала: адаптеры превращают входящие
сообщения в Incoming, а ответы OutMessage — в сообщения конкретной платформы.

Бот работает с той же бизнес-логикой и той же БД, что и сайт: каталог, остатки, корзина и заказы.
Через бота можно заказать только готовые букеты — ограничение повторно проверяется в сервисах корзины
и заказов (apps.carts.services / apps.orders.services)."""
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date as date_cls, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.carts import services as carts
from apps.catalog.models import Product
from apps.core.errors import DomainError
from apps.core.models import ShopSettings
from apps.core.site_content import orders_closed_message
from apps.core.utils import local_today, normalize_phone, rub
from apps.customers import login as customer_login
from apps.customers.services import get_or_create_channel_customer
from apps.delivery import geo
from apps.delivery.models import DeliveryZone
from apps.delivery.services import slots_for_date, today_unavailable_note
from apps.inventory.services import availability_map
from apps.notifications import services as notifications
from apps.notifications import staff as staff_notify
from apps.orders.models import Order
from apps.orders.services import place_order
from apps.payments.providers.registry import is_test_mode, online_enabled, pay_label
from apps.payments.services import ensure_payment_link

from .models import BotSession

PAGE_SIZE = 4
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass
class Button:
    text: str
    payload: str | None = None
    url: str | None = None
    request_contact: bool = False
    request_location: bool = False


@dataclass
class OutMessage:
    text: str
    photo: str | None = None  # путь относительно MEDIA_ROOT
    buttons: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class Incoming:
    channel: str
    user_id: str
    chat_id: str = ""
    text: str | None = None
    payload: str | None = None
    contact_phone: str | None = None
    location: tuple | None = None  # (широта, долгота) — геопозиция из мессенджера
    display_name: str = ""
    username: str = ""
    simulated: bool = False
    ref: str | None = None  # ВК: параметр ref из ссылки vk.me/…?ref=login_…


def B(text, payload=None, url=None, **kw):
    return Button(text=text, payload=payload, url=url, **kw)


MAIN_MENU = [
    [B("💐 Каталог букетов", "cat")],
    [B("🌷 Наличие цветов", "flowers"), B("🛒 Корзина", "cart")],
    [B("📦 Мои заказы", "orders"), B("💬 Флорист", "support")],
    [B("ℹ️ Доставка и оплата", "info")],
]
TEXT_ALIASES = {
    "/start": "menu", "start": "menu", "начать": "menu", "меню": "menu", "/menu": "menu", "привет": "menu",
    "каталог": "cat", "букеты": "cat", "/catalog": "cat", "корзина": "cart", "/cart": "cart",
    "заказы": "orders", "мои заказы": "orders", "/orders": "orders", "цветы": "flowers", "наличие": "flowers",
    "флорист": "support", "помощь": "support", "/help": "support", "доставка": "info", "оплата": "info",
}


def _norm(text):
    return re.sub(r"[^\wа-яё/ ]", "", text.lower()).strip()


for _row in MAIN_MENU:
    for _b in _row:
        TEXT_ALIASES[_norm(_b.text)] = _b.payload


LOGIN_START_RE = re.compile(r"^/start\s+login_([A-Za-z0-9_-]{8,40})$")
STAFF_START_RE = re.compile(r"^(?:/start\s+staff_|/?staff[\s_]+)([A-Za-z0-9_-]{8,40})$", re.IGNORECASE)
SHIFT_WORDS = {"/smena", "/shift", "смена", "моя смена", "начать смену", "закончить смену"}
LOGIN_CODE_RE = re.compile(r"^\s*(\d{3})[\s-]?(\d{3})\s*$")

CHECKOUT_CMDS = {"ful", "zone", "date", "slot", "name", "rcpt", "comment", "pay", "confirm", "edit"}
EDIT_FIELDS = [  # что можно исправить на шаге «Данные указаны правильно?»
    ("ful", "Способ получения"), ("address", "Адрес доставки"), ("date", "Дату и время"), ("name", "Имя"),
    ("phone", "Телефон"), ("recipient", "Получателя"), ("comment", "Комментарий"), ("payment", "Способ оплаты"),
]
EDIT_CLEARS = {
    "ful": ["fulfillment", "slot_id", "slot_label"],
    "address": ["address", "lat", "lon", "zone_id", "needs_zone", "address_token", "apartment", "entrance", "floor"],
    "date": ["date", "slot_id", "slot_label"], "name": ["name"], "phone": ["phone"],
    "recipient": ["recipient_name", "recipient_phone"], "comment": ["comment"], "payment": ["payment"],
}


class BotEngine:
    def __init__(self, channel):
        assert channel in ("telegram", "vk")
        self.channel = channel
        self.channel_title = "Telegram" if channel == "telegram" else "ВКонтакте"

    # ------------------------------------------------------------ вход
    def handle(self, inc: Incoming):
        with transaction.atomic():
            session = self._session(inc)
            try:
                staff_out = self._staff_hook(session, inc)
                login_out = self._login_hook(session, inc) if staff_out is None else None
                if staff_out is not None:
                    out = staff_out
                elif login_out is not None:
                    out = login_out
                elif inc.contact_phone and session.state == "checkout":
                    out = self._checkout_text(session, inc.contact_phone)
                elif inc.location and session.state == "checkout":
                    out = self._checkout_location(session, *inc.location)
                elif inc.payload:
                    out = self._route(session, inc.payload, inc)
                else:
                    out = self._on_text(session, (inc.text or "").strip(), inc)
            except DomainError as e:
                out = [OutMessage(f"⚠️ {e.message}", buttons=[[B("🛒 Корзина", "cart"), B("☰ Меню", "menu")]])]
            session.save()
        return out

    def _session(self, inc):
        session, created = BotSession.objects.select_for_update().get_or_create(
            channel=self.channel, external_user_id=str(inc.user_id),
            defaults={"chat_id": str(inc.chat_id or inc.user_id), "is_simulated": inc.simulated},
        )
        if not session.customer_id:
            customer, _ = get_or_create_channel_customer(
                self.channel, inc.user_id, chat_id=inc.chat_id or inc.user_id, display_name=inc.display_name,
                username=inc.username, simulated=inc.simulated,
            )
            session.customer = customer
        if not session.cart_id:
            session.cart = carts.create_cart(self.channel, customer=session.customer)
        elif session.cart.customer_id != session.customer_id:
            session.cart.customer = session.customer
            session.cart.save(update_fields=["customer"])
        session.data.setdefault("name", inc.display_name)
        return session

    def _on_text(self, session, text, inc):
        if session.state == "checkout":
            return self._checkout_text(session, text)
        if session.state == "support":
            return self._support_message(session, text, inc)
        payload = TEXT_ALIASES.get(_norm(text))
        if payload:
            return self._route(session, payload, inc)
        return [OutMessage("Я пока понимаю только команды меню. Выберите, что вас интересует:", buttons=MAIN_MENU)]

    def _route(self, session, payload, inc):
        cmd, _, arg = payload.partition(":")
        if session.state == "checkout" and cmd in CHECKOUT_CMDS:
            return self._checkout_button(session, cmd, arg)
        if session.state != "idle" and cmd not in CHECKOUT_CMDS:
            session.state = "idle"
        handler = {
            "menu": self.menu, "cat": self.catalog, "add": self.add, "cart": self.cart, "inc": self.inc,
            "dec": self.dec, "del": self.delete, "clear": self.clear, "checkout": self.checkout_start,
            "orders": self.orders, "order": self.order_detail, "payorder": self.pay_order, "flowers": self.flowers,
            "info": self.info, "support": self.support, "login_ok": self.login_ok, "login_no": self.login_no,
        }.get(cmd)
        if not handler:
            return self.menu(session, "")
        return handler(session, arg)

    # ------------------------------------------------------------ сотрудники: привязка и смена
    def _staff_hook(self, session, inc):
        code = inc.ref[6:] if inc.ref and inc.ref.startswith("staff_") else None
        m = STAFF_START_RE.match((inc.text or "").strip())
        if m:
            code = m.group(1)
        if code:
            session.state = "idle"
            user = staff_notify.link(self.channel, code, inc.user_id)
            if not user:
                return [OutMessage("Ссылка для сотрудника устарела или уже использована. Получите новую в админке: "
                                   "«Уведомления» (внизу меню) → «Привязать».", buttons=MAIN_MENU)]
            return [self._shift_view(user, linked=True)]
        payload = inc.payload or ""
        if not (payload.startswith("shift") or (not payload and _norm(inc.text or "") in SHIFT_WORDS)):
            return None
        user = staff_notify.staff_for(self.channel, inc.user_id)
        if not user:
            return None if not payload else [OutMessage("Эта команда — только для сотрудников магазина.",
                                                        buttons=MAIN_MENU)]
        session.state = "idle"
        if payload == "shift:on":
            staff_notify.set_shift(user, True)
        elif payload == "shift:off":
            staff_notify.set_shift(user, False)
        return [self._shift_view(user)]

    def _shift_view(self, user, linked=False):
        lines = []
        if linked:
            lines.append(f"✅ {user.display_name}, {self.channel_title} привязан к вашей учётной записи сотрудника.")
        mode = user.notify_mode
        if mode == "always":
            lines.append("Уведомления о новых заказах и обращениях приходят сюда всегда (режим «Всегда»).")
        elif mode == "off":
            lines.append("Уведомления выключены (режим «Не присылать»). Включить можно в админке → «Уведомления».")
        else:
            lines.append("Уведомления о новых заказах и обращениях приходят сюда, только пока вы на смене.")
        if user.on_shift and user.shift_started_at:
            lines.append(f"🟢 Вы на смене с {timezone.localtime(user.shift_started_at):%H:%M}.")
        else:
            lines.append("⚪ Сейчас вы не на смене.")
        others = staff_notify.on_shift_names(exclude=user)
        lines.append("На смене также: " + ", ".join(others) if others else "Больше никого на смене нет.")
        lines.append("Открыть это меню: " + ("/smena" if self.channel == "telegram" else "напишите «смена»") + ".")
        shift_btn = B("⏹ Закончить смену", "shift:off") if user.on_shift else B("▶ Начать смену", "shift:on")
        return OutMessage("\n".join(lines), buttons=[[shift_btn], [B("☰ Меню магазина", "menu")]])

    # ------------------------------------------------------------ вход на сайт через бота
    def _who(self, session):
        return f"{self.channel}:{session.external_user_id}"

    def _login_hook(self, session, inc):
        link = None
        if inc.ref and inc.ref.startswith("login_"):
            link = inc.ref[6:]
        m = LOGIN_START_RE.match((inc.text or "").strip())
        if m:
            link = m.group(1)
        if link:
            return self._login_open(session, customer_login.find_by_link(link, self.channel))
        if session.state == "idle" and not inc.payload and inc.text:
            m = LOGIN_CODE_RE.match(inc.text)
            if m:
                return self._login_open(session, customer_login.find_by_code(m.group(1) + m.group(2), self.channel,
                                                                             session.external_user_id))
        return None

    def _login_open(self, session, login):
        session.state = "idle"
        if not login or not customer_login.claim(login, self._who(session)):
            return [OutMessage("Ссылка или код входа устарели. Нажмите «Войти через " + self.channel_title
                               + "» на сайте ещё раз.", buttons=MAIN_MENU)]
        shop = ShopSettings.load()
        device = customer_login.device_label(login.user_agent)
        where = f" ({device})" if device else ""
        if login.order_id:
            text = (f"🔔 Подключить уведомления о заказе №{login.order.number} на сайте «{shop.shop_name}»{where}?\n\n"
                    "Сюда будут приходить изменения статуса, а сайт запомнит вас для следующих заказов.")
            ok = "✅ Подключить"
        else:
            text = (f"🔐 Вход на сайт «{shop.shop_name}»{where}.\n\n"
                    "Подтвердите, что это вы. После входа сайт запомнит ваши данные, а уведомления о заказах "
                    "будут приходить сюда.\n\nЕсли вы не входили на сайт — нажмите «Отмена».")
            ok = "✅ Войти на сайт"
        return [OutMessage(text, buttons=[[B(ok, f"login_ok:{login.pk}")], [B("Отмена", f"login_no:{login.pk}")]])]

    def login_ok(self, session, arg):
        login = customer_login.confirm(int(arg) if arg.isdigit() else 0, self._who(session), session.customer)
        if not login:
            return [OutMessage("Запрос входа устарел. Нажмите кнопку входа на сайте ещё раз.", buttons=MAIN_MENU)]
        if login.order_id:
            o = login.order
            text = (f"✅ Уведомления о заказе №{o.number} подключены. Сейчас: {o.get_status_display().lower()}.\n"
                    "Вернитесь на сайт — вы уже вошли.")
            buttons = [[B("Статус заказа", url=notifications._order_url(o))]] + MAIN_MENU
        else:
            text = ("✅ Готово, вы вошли на сайт. Вернитесь в браузер — данные подставятся автоматически.\n"
                    "Уведомления о заказах будут приходить сюда.")
            buttons = MAIN_MENU
        return [OutMessage(text, buttons=buttons)]

    def login_no(self, session, arg):
        customer_login.cancel(int(arg) if arg.isdigit() else 0, self._who(session))
        return [OutMessage("Вход отменён.", buttons=MAIN_MENU)]

    # ------------------------------------------------------------ меню и каталог
    def menu(self, session, arg):
        shop = ShopSettings.load()
        name = session.data.get("name") or ""
        hello = f"Здравствуйте{', ' + name if name else ''}! Это бот магазина «{shop.shop_name}»."
        if not shop.orders_enabled:
            return [OutMessage(f"{hello}\n⏸ {orders_closed_message(shop)}\nБукеты можно посмотреть в каталоге.",
                               buttons=MAIN_MENU)]
        return [OutMessage(f"{hello}\nЗдесь можно выбрать и заказать готовый букет с доставкой или самовывозом.",
                           buttons=MAIN_MENU)]

    def _bouquets(self):
        products = list(Product.objects.filter(type=Product.Type.BOUQUET, is_active=True)
                        .select_related("inventory_item").prefetch_related("images", "inventory_item__recipe__components"))
        avail = availability_map()
        rows = []
        for p in products:
            rows.append((p, carts.product_available(p, avail)))
        return rows

    def catalog(self, session, arg):
        shop = ShopSettings.load()
        closed = not shop.orders_enabled
        rows = self._bouquets()
        categories = sorted({p.category for p, _ in rows if p.category})
        if not arg:
            buttons = [[B(f"{c} · {sum(1 for p, a in rows if p.category == c and a > 0)}", f"cat:{i}:0")]
                       for i, c in enumerate(categories)]
            buttons.append([B(f"Все букеты в наличии · {sum(1 for _, a in rows if a > 0)}", "cat:all:0")])
            buttons.append([B("🛒 Корзина", "cart"), B("☰ Меню", "menu")])
            text = "Выберите категорию букетов:"
            if closed:
                text = f"⏸ {orders_closed_message(shop)}\n\n{text}"
            return [OutMessage(text, buttons=buttons)]
        cat, _, page = arg.partition(":")
        page = int(page or 0)
        if cat == "all":
            title, selected = "Все букеты", [(p, a) for p, a in rows if a > 0]
        else:
            try:
                title = categories[int(cat)]
            except (ValueError, IndexError):
                return self.catalog(session, "")
            selected = [(p, a) for p, a in rows if p.category == title]
        selected.sort(key=lambda r: (r[1] <= 0, r[0].sort_order))
        chunk = selected[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        out = []
        for p, available in chunk:
            img = p.images.first()
            caption = f"{p.name}\n{p.short_description}\nЦена: {rub(p.price)}\n"
            caption += f"В наличии: {available} шт." if available > 0 else "Нет в наличии"
            buttons = [[B(f"➕ В корзину · {rub(p.price)}", f"add:{p.id}")]] if available > 0 and not closed else []
            out.append(OutMessage(caption, photo=img.image.name if img else None, buttons=buttons))
        nav = []
        if page > 0:
            nav.append(B("◀ Назад", f"cat:{cat}:{page - 1}"))
        if (page + 1) * PAGE_SIZE < len(selected):
            nav.append(B("Ещё ▶", f"cat:{cat}:{page + 1}"))
        shown_to = min((page + 1) * PAGE_SIZE, len(selected))
        text = f"{title}: показано {page * PAGE_SIZE + 1}–{shown_to} из {len(selected)}" if selected else f"{title}: пока пусто"
        buttons = [nav] if nav else []
        buttons += [[B("📂 Категории", "cat"), B("🛒 Корзина", "cart")]]
        out.append(OutMessage(text, buttons=buttons))
        return out

    def add(self, session, arg):
        line = carts.add_product(session.cart, int(arg), 1)
        s = carts.summary(session.cart)
        return [OutMessage(f"Добавлено: {line.product.name}.\nВ корзине {s['count']} шт. на {rub(s['items_total'])}.",
                           buttons=[[B("🛒 Оформить", "cart"), B("💐 Продолжить", "cat")]])]

    def flowers(self, session, arg):
        products = list(Product.objects.filter(type=Product.Type.FLOWER, is_active=True).select_related("inventory_item"))
        avail = availability_map([p.inventory_item_id for p in products])
        lines = ["Наличие цветов сегодня (для информации):"]
        for p in products:
            a = avail.get(p.inventory_item_id, 0)
            lines.append(f"• {p.name} — {rub(p.price)}/шт · {'в наличии ' + str(a) if a > 0 else 'нет'}")
        lines.append("\nПоштучный заказ цветов и сборка индивидуального букета доступны только на сайте.")
        return [OutMessage("\n".join(lines), buttons=[
            [B("Собрать букет на сайте", url=f"{settings.FRONTEND_URL}/constructor")],
            [B("💐 Готовые букеты", "cat"), B("☰ Меню", "menu")],
        ])]

    def info(self, session, arg):
        shop = ShopSettings.load()
        zones = "\n".join(
            f"• {z.name} — {rub(z.price)}" + (f" (бесплатно от {rub(z.free_from)})" if z.free_from else "")
            for z in DeliveryZone.objects.filter(is_active=True)
        )
        if not online_enabled():
            pay = "при получении — наличными или переводом"
        else:
            pay = "онлайн (сейчас — тестовый режим, деньги не списываются)" if is_test_mode() else "онлайн картой или СБП"
            if shop.allow_cash_on_delivery:
                pay += " или при получении (кроме индивидуальных букетов)"
        text = (f"Доставка нашими курьерами по районам:\n{zones}\n\nСамовывоз: {shop.address}, {shop.working_hours}.\n"
                f"Оплата: {pay}.\nТелефон: {shop.phone}")
        return [OutMessage(text, buttons=[[B("💐 Каталог", "cat"), B("☰ Меню", "menu")]])]

    # ------------------------------------------------------------ корзина
    def cart(self, session, arg=""):
        s = carts.summary(session.cart)
        if not s["items"]:
            return [OutMessage("Корзина пуста.", buttons=[[B("💐 Каталог букетов", "cat")], [B("☰ Меню", "menu")]])]
        lines = ["Ваша корзина:"]
        buttons = []
        for i, it in enumerate(s["items"], 1):
            warn = "" if it["ok"] else f" ⚠️ доступно {it.get('available', 0)}"
            lines.append(f"{i}. {it['name']} × {it['quantity']} — {rub(it['total'])}{warn}")
            if i <= 4:
                buttons.append([B(f"➖ {i}", f"dec:{it['id']}"), B(f"➕ {i}", f"inc:{it['id']}"), B(f"🗑 {i}", f"del:{it['id']}")])
        lines.append(f"\nИтого за товары: {rub(s['items_total'])} (доставка рассчитывается при оформлении)")
        buttons.append([B("✅ Оформить заказ", "checkout")])
        buttons.append([B("Очистить", "clear"), B("💐 Каталог", "cat")])
        return [OutMessage("\n".join(lines), buttons=buttons)]

    def _line(self, session, arg):
        return session.cart.items.filter(pk=int(arg)).first()

    def inc(self, session, arg):
        line = self._line(session, arg)
        if line:
            carts.set_quantity(session.cart, line.id, line.quantity + 1)
        return self.cart(session)

    def dec(self, session, arg):
        line = self._line(session, arg)
        if line:
            carts.set_quantity(session.cart, line.id, line.quantity - 1)
        return self.cart(session)

    def delete(self, session, arg):
        carts.remove_item(session.cart, int(arg))
        return self.cart(session)

    def clear(self, session, arg):
        carts.clear(session.cart)
        return self.cart(session)

    # ------------------------------------------------------------ оформление
    STEPS = ["fulfillment", "address", "zone", "date", "slot", "name", "phone", "recipient", "comment", "payment", "confirm"]

    def checkout_start(self, session, arg):
        carts.assert_orders_open()
        s = carts.summary(session.cart)
        if not s["items"]:
            return self.cart(session)
        if s["problems"]:
            return [OutMessage("Некоторых букетов уже нет в нужном количестве. Измените корзину:", buttons=[[B("🛒 Корзина", "cart")]])]
        session.state = "checkout"
        session.data["checkout"] = {"step": "fulfillment", "key": uuid.uuid4().hex}
        return self._ask(session)

    def _co(self, session):
        return session.data.setdefault("checkout", {"step": "fulfillment"})

    def _skip(self, co, step):
        """Шаг не нужен (самовывоз, район найден по адресу, только онлайн-оплата) или уже заполнен."""
        delivery = co.get("fulfillment") == "delivery"
        if step in ("address", "zone", "recipient") and not delivery:
            return True
        if step == "zone" and not co.get("needs_zone"):
            return True
        if step == "payment" and not online_enabled():
            co["payment"] = "on_delivery"  # онлайн-касса не подключена — оплата при получении
            return True
        if step == "payment" and not ShopSettings.load().allow_cash_on_delivery:
            co["payment"] = "online"
            return True
        filled = {
            "fulfillment": "fulfillment" in co, "address": bool(co.get("address")), "zone": bool(co.get("zone_id")),
            "date": bool(co.get("date")), "slot": bool(co.get("slot_id")), "name": bool(co.get("name")),
            "phone": bool(co.get("phone")), "recipient": "recipient_name" in co, "comment": "comment" in co,
            "payment": bool(co.get("payment")),
        }
        return filled.get(step, False)

    def _next(self, session):
        """Следующий незаполненный шаг. После «Изменить» сразу возвращает к подтверждению."""
        co = self._co(session)
        for step in self.STEPS:
            if step == "confirm" or not self._skip(co, step):
                co["step"] = step
                break
        return self._ask(session)

    def _ask(self, session):
        co = self._co(session)
        step = co["step"]
        cancel = [B("✖ Отменить оформление", "cart")]
        if step == "fulfillment":
            return [OutMessage("Как получить заказ?", buttons=[[B("🚗 Доставка", "ful:delivery"), B("🛍 Самовывоз", "ful:pickup")], cancel])]
        if step == "address":
            rows = [[B("📍 Отправить геопозицию", request_location=True)]] if self.channel == "telegram" else []
            hint = " или отправьте геопозицию" if self.channel == "telegram" else ""
            return [OutMessage(f"Напишите адрес доставки: улица, дом, квартира{hint}.\nНапример: Кондратово, Красавинская, 8, кв. 12",
                               buttons=rows + [cancel])]
        if step == "zone":
            zones = DeliveryZone.objects.filter(is_active=True)
            return [OutMessage("Не удалось автоматически проверить адрес. Выберите район доставки:",
                               buttons=[[B(f"{z.name} · {rub(z.price)}", f"zone:{z.id}")] for z in zones] + [cancel])]
        if step == "date":
            buttons, today = [], local_today()
            for d in range(0, 4):
                day = today + timedelta(days=d)
                if any(s["available"] for s in slots_for_date(day, co["fulfillment"])):
                    title = {0: "Сегодня", 1: "Завтра"}.get(d, WEEKDAYS[day.weekday()].capitalize())
                    buttons.append(B(f"{title}, {day:%d.%m}", f"date:{day.isoformat()}"))
            rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
            note = today_unavailable_note(co["fulfillment"])
            text = "Выберите дату или напишите её в формате ДД.ММ:"
            if not buttons:
                text = "В ближайшие дни свободного времени нет. Напишите нужную дату в формате ДД.ММ:"
            return [OutMessage(f"{note}\n\n{text}" if note else text, buttons=rows + [cancel])]
        if step == "slot":
            day = date_cls.fromisoformat(co["date"])
            slots = [s for s in slots_for_date(day, co["fulfillment"]) if s["available"]]
            if not slots:
                co["step"] = "date"
                co.pop("date", None)
                return [OutMessage("На эту дату свободных интервалов нет.")] + self._ask(session)
            rows = [[B(s["label"], f"slot:{s['id']}") for s in slots[i:i + 2]] for i in range(0, len(slots), 2)]
            return [OutMessage(f"Выберите время ({day:%d.%m}):", buttons=rows + [cancel])]
        if step == "name":
            name = session.data.get("name")
            rows = [[B(f"Да, я {name}", "name:keep")]] if name else []
            return [OutMessage("Как вас зовут? Напишите имя." if not name else f"Оформляем на имя «{name}»? Или напишите другое имя.",
                               buttons=rows + [cancel])]
        if step == "phone":
            rows = [[B("📱 Отправить мой номер", request_contact=True)]] if self.channel == "telegram" else []
            saved = session.data.get("phone")
            if saved:
                rows.insert(0, [B(f"Использовать {saved}", f"name:phone")])
            return [OutMessage("Напишите номер телефона для связи (например, +7 900 123-45-67).", buttons=rows + [cancel])]
        if step == "recipient":
            return [OutMessage("Кто получит букет? Напишите имя и телефон получателя через запятую или нажмите кнопку.",
                               buttons=[[B("Получатель — я", "rcpt:self")], cancel])]
        if step == "comment":
            return [OutMessage("Комментарий к заказу или текст для открытки? Напишите его или пропустите.",
                               buttons=[[B("Пропустить", "comment:skip")], cancel])]
        if step == "payment":
            return [OutMessage("Способ оплаты:", buttons=[
                [B(f"💳 {pay_label('Онлайн')}", "pay:online")], [B("💵 При получении", "pay:on_delivery")], cancel])]
        if step == "confirm":
            return [OutMessage(self._summary_text(session) + "\n\nДанные указаны правильно?",
                               buttons=[[B("Да", "confirm:yes"), B("Изменить", "confirm:edit")], cancel])]
        if step == "edit":
            return self._edit_menu(session)
        return self.cart(session)

    def _edit_menu(self, session):
        co = self._co(session)
        co["step"] = "edit"
        rows = []
        for key, title in EDIT_FIELDS:
            if key in ("address", "recipient") and co.get("fulfillment") != "delivery":
                continue
            if key == "payment" and (not online_enabled() or not ShopSettings.load().allow_cash_on_delivery):
                continue
            rows.append(B(title, f"edit:{key}"))
        buttons = [rows[i:i + 2] for i in range(0, len(rows), 2)]
        buttons.append([B("◀ Назад к заказу", "edit:back")])
        return [OutMessage("Что исправить?", buttons=buttons)]

    def _edit(self, session, field):
        co = self._co(session)
        if field not in EDIT_CLEARS:
            return self._next(session)
        for key in EDIT_CLEARS[field]:
            co.pop(key, None)
        return self._next(session)

    # --- адрес: геокодер находит дом и зону доставки; вне зон заказ с доставкой не оформить
    def _out_of_zone(self, address):
        return [OutMessage(f"По адресу «{address}» мы пока не доставляем: он вне наших районов доставки. "
                           "Напишите другой адрес или выберите самовывоз.",
                           buttons=[[B("🛍 Самовывоз", "ful:pickup")], [B("✖ Отменить оформление", "cart")]])]

    def _accept_address(self, session, res, extra=None):
        co = self._co(session)
        zone = geo.find_zone(res.lat, res.lon)
        if not zone:
            return self._out_of_zone(res.address)
        extra = extra or {}
        co.update(address=res.address, lat=res.lat, lon=res.lon, zone_id=zone.id, needs_zone=False,
                  address_token=geo.sign(res.address, res.lat, res.lon), apartment=extra.get("apartment", ""),
                  entrance=extra.get("entrance", ""), floor=extra.get("floor", ""))
        total = carts.summary(session.cart)["items_total"]
        cost = zone.cost_for(total)
        apt = f", кв. {co['apartment']}" if co["apartment"] else ""
        note = f"Адрес: {res.address}{apt}\n{zone.name}, доставка {rub(cost) if cost else 'бесплатно'}"
        if cost and zone.free_from:
            note += f" (бесплатно от {rub(zone.free_from)})"
        return [OutMessage(note)] + self._next(session)

    def _address_text(self, session, text):
        co = self._co(session)
        query, extra = geo.split_apartment(text)
        if len(query) < 4:
            return [OutMessage("Адрес слишком короткий. Укажите улицу и номер дома, например: Пермь, Ленина, 50, кв. 12")]
        try:
            rows = geo.geocode(query, 5)
        except geo.GeocoderUnavailable:
            co.update(address=text[:255], lat=None, lon=None, zone_id=None, needs_zone=True, address_token="",
                      apartment="", entrance="", floor="")
            return self._next(session)
        best = next((r for r in rows if r.house), None)
        if not best:
            return [OutMessage("Не нашли такой адрес. Напишите улицу и номер дома, например: Пермь, Ленина, 50, кв. 12",
                               buttons=[[B("✖ Отменить оформление", "cart")]])]
        return self._accept_address(session, best, extra)

    def _checkout_location(self, session, lat, lon):
        co = self._co(session)
        if co.get("step") != "address":
            return [OutMessage("Геопозиция нужна только на шаге адреса доставки.")] + self._ask(session)
        if not geo.find_zone(lat, lon):
            return self._out_of_zone("отправленной точке")
        try:
            res = geo.reverse(lat, lon)
        except geo.GeocoderUnavailable:
            res = None
        if not res or not res.house:
            return [OutMessage("Не удалось определить дом по геопозиции. Напишите адрес текстом: улица, дом, квартира.")]
        return self._accept_address(session, res)

    def _summary_text(self, session):
        co = self._co(session)
        s = carts.summary(session.cart)
        lines = ["Проверьте заказ:"] + [f"• {i['name']} × {i['quantity']} — {rub(i['total'])}" for i in s["items"]]
        delivery_cost = 0
        if co.get("fulfillment") == "delivery":
            zone = DeliveryZone.objects.filter(pk=co.get("zone_id")).first()
            delivery_cost = zone.cost_for(s["items_total"]) if zone else 0
            apt = f", кв. {co['apartment']}" if co.get("apartment") else ""
            lines.append(f"Доставка: {co.get('address')}{apt}")
            lines.append(f"Зона: {zone.name if zone else '—'}, {rub(delivery_cost) if delivery_cost else 'бесплатно'}")
            if co.get("recipient_name"):
                lines.append(f"Получатель: {co['recipient_name']} {co.get('recipient_phone', '')}")
        else:
            lines.append(f"Самовывоз: {ShopSettings.load().address}")
        day = date_cls.fromisoformat(co["date"])
        lines.append(f"Дата и время: {day:%d.%m.%Y}, {co.get('slot_label')}")
        lines.append(f"Контакт: {co.get('name')}, {co.get('phone')}")
        if co.get("comment"):
            lines.append(f"Комментарий: {co['comment']}")
        lines.append(f"Оплата: {'онлайн' if co.get('payment') == 'online' else 'при получении'}")
        lines.append(f"Итого: {rub(s['items_total'] + delivery_cost)}")
        return "\n".join(lines)

    def _checkout_button(self, session, cmd, arg):
        co = self._co(session)
        if cmd == "ful" and arg in ("delivery", "pickup"):
            if co.get("fulfillment") != arg:
                co.pop("slot_id", None)
                co.pop("slot_label", None)
            co["fulfillment"] = arg
            co["step"] = "fulfillment"
        elif cmd == "edit":
            return self._next(session) if arg == "back" else self._edit(session, arg)
        elif cmd == "zone":
            zone = DeliveryZone.objects.filter(pk=int(arg), is_active=True).first()
            if not zone:
                return self._ask(session)
            co["zone_id"] = zone.id
            co["step"] = "zone"
        elif cmd == "date":
            co["date"] = date_cls.fromisoformat(arg).isoformat()
            co.pop("slot_id", None)
            co.pop("slot_label", None)
            co["step"] = "date"
        elif cmd == "slot":
            day = date_cls.fromisoformat(co["date"])
            slot = next((s for s in slots_for_date(day, co["fulfillment"]) if s["id"] == int(arg) and s["available"]), None)
            if not slot:
                return [OutMessage("Этот интервал уже недоступен.")] + self._ask(session)
            co["slot_id"], co["slot_label"] = slot["id"], slot["label"]
            co["step"] = "slot"
        elif cmd == "name" and arg == "keep":
            co["name"] = session.data.get("name")
            co["step"] = "name"
        elif cmd == "name" and arg == "phone":
            co["phone"] = session.data.get("phone")
            co["step"] = "phone"
        elif cmd == "rcpt":
            co["recipient_name"], co["recipient_phone"] = "", ""
            co["step"] = "recipient"
        elif cmd == "comment":
            co["comment"] = ""
            co["step"] = "comment"
        elif cmd == "pay" and arg in ("online", "on_delivery"):
            co["payment"] = arg
            co["step"] = "payment"
        elif cmd == "confirm" and arg == "edit":
            return self._edit_menu(session)
        elif cmd == "confirm":
            if co.get("step") != "confirm":
                return self._next(session)
            return self._place(session)
        else:
            return self._ask(session)
        return self._next(session)

    def _checkout_text(self, session, text):
        co = self._co(session)
        step = co["step"]
        if step == "address":
            return self._address_text(session, text)
        if step == "confirm":
            answer = _norm(text)
            if answer in ("да", "верно", "подтверждаю", "все верно", "всё верно"):
                return self._place(session)
            if answer in ("изменить", "нет", "исправить"):
                return self._edit_menu(session)
            return self._ask(session)
        if step == "date":
            m = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", text)
            if not m:
                return [OutMessage("Не удалось распознать дату. Пример: 14.02")] + self._ask(session)
            year = int(m.group(3)) if m.group(3) else local_today().year
            year = year + 2000 if year < 100 else year
            try:
                day = date_cls(year, int(m.group(2)), int(m.group(1)))
            except ValueError:
                return [OutMessage("Такой даты нет.")] + self._ask(session)
            if day < local_today():
                day = date_cls(year + 1, day.month, day.day)
            co["date"] = day.isoformat()
            co.pop("slot_id", None)
            co.pop("slot_label", None)
        elif step == "name":
            co["name"] = text[:160]
            session.data["name"] = co["name"]
        elif step == "phone":
            phone = normalize_phone(text)
            if not phone:
                return [OutMessage("Не похоже на российский номер. Пример: +7 900 123-45-67")]
            co["phone"] = session.data["phone"] = phone
        elif step == "recipient":
            parts = [p.strip() for p in text.split(",")]
            phone = normalize_phone(parts[-1]) if len(parts) > 1 else None
            co["recipient_name"] = parts[0][:160]
            co["recipient_phone"] = phone or ""
        elif step == "comment":
            co["comment"] = text[:1000]
        else:
            return [OutMessage("Пожалуйста, воспользуйтесь кнопками ниже.")] + self._ask(session)
        return self._next(session)

    def _place(self, session):
        co = self._co(session)
        data = {
            "customer": {"name": co.get("name"), "phone": co.get("phone")},
            "recipient": {"name": co.get("recipient_name", ""), "phone": co.get("recipient_phone", "")},
            "fulfillment": co.get("fulfillment"),
            "delivery": {"zone_id": co.get("zone_id"), "address": co.get("address", ""), "lat": co.get("lat"),
                         "lon": co.get("lon"), "address_token": co.get("address_token", ""),
                         "apartment": co.get("apartment", ""), "entrance": co.get("entrance", ""),
                         "floor": co.get("floor", "")},
            "date": co.get("date"), "slot_id": co.get("slot_id"), "payment_method": co.get("payment"),
            "comment": co.get("comment", ""), "idempotency_key": co.get("key") or uuid.uuid4().hex,
        }
        order = place_order(session.cart, data, actor_label=f"{self.channel_title}-бот")
        session.state = "idle"
        session.data.pop("checkout", None)
        text = f"✅ Заказ №{order.number} оформлен на сумму {rub(order.total)}.\nСтатус: {order.get_status_display()}."
        buttons = []
        if order.status == Order.Status.AWAITING_PAYMENT:
            url = ensure_payment_link(order)
            text += f"\nТовар зарезервирован на {ShopSettings.load().online_reservation_minutes} мин. Оплатите по ссылке:"
            buttons.append([B(f"💳 Оплатить {rub(order.total)}", url=url)])
        elif order.status == Order.Status.AWAITING_CONFIRMATION:
            text += "\nФлорист проверит заказ и пришлёт ссылку на оплату."
        else:
            text += "\nМы свяжемся с вами для подтверждения. Оплата при получении."
        buttons.append([B("📦 Мои заказы", "orders"), B("☰ Меню", "menu")])
        return [OutMessage(text, buttons=buttons)]

    # ------------------------------------------------------------ заказы
    def _orders_qs(self, session):
        return Order.objects.filter(customer=session.customer).exclude(source="store").order_by("-created_at")

    def orders(self, session, arg):
        orders = list(self._orders_qs(session)[:5])
        if not orders:
            return [OutMessage("У вас пока нет заказов.", buttons=[[B("💐 Каталог", "cat")]])]
        lines = ["Последние заказы:"]
        for o in orders:
            lines.append(f"№{o.number} от {o.created_at:%d.%m} — {o.get_status_display()} · {rub(o.total)} · оплата: {o.get_payment_status_display().lower()}")
        buttons = [[B(f"Заказ №{o.number}", f"order:{o.number}")] for o in orders] + [[B("☰ Меню", "menu")]]
        return [OutMessage("\n".join(lines), buttons=buttons)]

    def order_detail(self, session, arg):
        o = self._orders_qs(session).filter(number=arg).first()
        if not o:
            return self.orders(session, "")
        lines = [f"Заказ №{o.number} — {o.get_status_display()}"]
        lines += [f"• {i.name} × {i.quantity} — {rub(i.line_total)}" for i in o.items.all()]
        if o.delivery_cost:
            lines.append(f"Доставка: {rub(o.delivery_cost)}")
        lines.append(f"Итого: {rub(o.total)} · оплата: {o.get_payment_status_display().lower()}")
        lines.append(f"{o.get_fulfillment_display()}: {o.fulfillment_date:%d.%m}, {o.time_from:%H:%M}–{o.time_to:%H:%M}" if o.time_from else "")
        history = [f"{e.created_at:%d.%m %H:%M} — {Order.Status(e.to_status).label}" for e in o.events.exclude(to_status="")]
        if history:
            lines.append("История:\n" + "\n".join(history[-6:]))
        buttons = []
        if o.status == Order.Status.AWAITING_PAYMENT:
            buttons.append([B("💳 Оплатить", f"payorder:{o.number}")])
        buttons.append([B("📦 Все заказы", "orders"), B("☰ Меню", "menu")])
        return [OutMessage("\n".join(l for l in lines if l), buttons=buttons)]

    def pay_order(self, session, arg):
        o = self._orders_qs(session).filter(number=arg).first()
        url = ensure_payment_link(o) if o else None
        if not url:
            return [OutMessage("Заказ не ожидает оплаты.", buttons=[[B("📦 Мои заказы", "orders")]])]
        note = " (тестовый режим, деньги не списываются)" if is_test_mode() else ""
        return [OutMessage(f"Ссылка на оплату заказа №{o.number}{note}:",
                           buttons=[[B(f"💳 Оплатить {rub(o.total)}", url=url)]])]

    # ------------------------------------------------------------ связь с флористом
    def support(self, session, arg):
        session.state = "support"
        return [OutMessage("Напишите ваш вопрос одним сообщением — я передам его флористу. Ответ придёт в этот чат.",
                           buttons=[[B("✖ Отмена", "menu")]])]

    def _support_message(self, session, text, inc):
        session.state = "idle"
        who = session.data.get("name") or inc.display_name or "Покупатель"
        handle = f" (@{inc.username})" if inc.username else ""
        notifications.create(
            "staff", f"💬 Обращение из {self.channel_title} от {who}{handle}: {text[:1500]}", kind="support_request",
            customer=session.customer, recipient=notifications.staff_recipient(),
            payload={"reply_channel": self.channel, "reply_to": str(inc.user_id), "message": text[:1500]},
        )
        return [OutMessage("Спасибо! Сообщение передано флористу. Мы ответим здесь в рабочее время.", buttons=MAIN_MENU)]
