"""Тексты сайта, которые владелец меняет в админке.

* приём заказов — сообщение покупателям, пока он закрыт;
* «Частые вопросы» (FAQ) — блоки с вопросами и ответами. Пока владелец их не менял (`faq is None`), показываются
  стандартные вопросы: они собираются из настроек (цены доставки, сроки, способы оплаты) и меняются вместе с ними;
* заголовки (title) и описания (description) страниц для поисковиков и коды подтверждения Яндекса/Google.

Разметка ответов FAQ — простая и безопасная (HTML не принимается): пустая строка — новый абзац, «- » в начале
строки — пункт списка, **жирный**, [текст](/delivery) или [текст](https://…) — ссылка. Её рисует сайт
(frontend/components/Faq.tsx)."""
import re

from django.conf import settings as dj_settings

from . import validation as v

# ------------------------------------------------------------------ приём заказов

ORDERS_CLOSED_DEFAULT = "Сейчас мы не принимаем заказы. Загляните чуть позже — или позвоните нам."


def orders_closed_message(s):
    return (s.orders_closed_message or "").strip() or ORDERS_CLOSED_DEFAULT


# ------------------------------------------------------------------ форматирование

def money(kopecks):
    rub = kopecks / 100
    whole = f"{int(rub):,}".replace(",", "\u00a0")
    return f"{whole} ₽" if rub == int(rub) else f"{rub:,.2f}".replace(",", "\u00a0").replace(".", ",") + " ₽"


def plural(n, one, few, many):
    m10, m100 = n % 10, n % 100
    if m10 == 1 and m100 != 11:
        return one
    if 2 <= m10 <= 4 and not 12 <= m100 <= 14:
        return few
    return many


def lead_time(min_lead_minutes):
    """Сколько нужно на сборку и дорогу: «2 ч 30 мин» (как lib/format.ts → leadTime)."""
    lead = (min_lead_minutes if min_lead_minutes is not None else 120) + 30
    h, m = divmod(lead, 60)
    return (f"{h} ч " if h else "") + f"{m} мин" if m else f"{h} ч"


def delivery_area(city):
    c = (city or "").strip()
    if not c or re.search(r"кондратов|медов", c, re.I):
        return "по Кондратово и Медовому"
    return f"по населённому пункту {c} и окрестностям"


# ------------------------------------------------------------------ «Частые вопросы»

FAQ_MAX_BLOCKS = 20
FAQ_MAX_ITEMS = 60
FAQ_MAX_TOTAL = 200


def _zone_prices():
    from apps.delivery.models import DeliveryZone

    zones = list(DeliveryZone.objects.filter(is_active=True).values_list("price", "free_from"))
    min_price = min((p for p, _ in zones), default=None)
    free = [f for _, f in zones if f]
    return min_price, (min(free) if free else None)


def default_faq(s):
    """Стандартные вопросы — тот же текст, что был зашит на главной, но с текущими значениями настроек."""
    from apps.customers.login import channels_available
    from apps.payments.providers.registry import cod_allowed, is_test_mode, online_enabled

    min_zone, free_from = _zone_prices()
    login = channels_available()
    messengers = login.get("telegram") or login.get("vk")
    constructor = s.constructor_section_enabled
    pre = s.preorder_threshold_days
    phone = (s.phone or "").strip()
    tel = re.sub(r"[^\d+]", "", phone)

    cost = "Зависит от зоны на карте"
    if min_zone is not None:
        cost += f": по городу от {money(min_zone)}"
    if free_from:
        cost += f", а при заказе от {money(free_from)} — бесплатно"
    cost += (". Точная сумма появится, как только вы отметите адрес при оформлении. "
             "Все зоны и цены — на странице [«Доставка и оплата»](/delivery).")

    today = (f"Да, если до конца выбранного интервала остаётся не меньше {lead_time(s.min_lead_minutes)} — столько "
             "нужно на сборку и дорогу. Курьер приедет в любой момент интервала.")
    if pre:
        today += (f" Заказ больше чем на {pre} {plural(pre, 'день', 'дня', 'дней')} вперёд — предзаказ: флорист "
                  "подтвердит его и закупит цветы к дате.")

    pickup = f"Да, по адресу {s.address}" + (f" ({s.working_hours})" if s.working_hours else "")
    pickup += (f". Букет будет готов примерно через {s.pickup_ready_minutes} минут после подтверждения заказа — "
               "мы сообщим, когда можно приходить.")

    pay = (f"Онлайн картой: страница оплаты откроется сразу после оформления, букет ждёт оплату "
           f"{s.online_reservation_minutes} минут.")
    if cod_allowed(s):
        what = "Готовые букеты" + (" и цветы" if s.flowers_section_enabled else "")
        pay += f" {what} можно оплатить при получении — такой заказ подтверждает администратор."
    if constructor:
        pay += " Индивидуальный букет оплачивается после того, как флорист подтвердит состав."
    if online_enabled() and is_test_mode():
        pay += " Сейчас сайт в демо-режиме: оплата тестовая, деньги не списываются."

    photo = ("Да. Флорист фотографирует собранный букет, фото появляется на странице заказа"
             + (" и приходит в Telegram или ВКонтакте" if messengers else "")
             + ". Если что-то не так — поправим до выезда курьера.")

    track = ("По ссылке, которая появится после оформления, или в разделе [«Мой заказ»](/track) по номеру заказа "
             "и телефону." + (" Если войти через Telegram или ВКонтакте, уведомления о каждом этапе придут туда."
                              if messengers else ""))

    cancel = "До начала сборки — по телефону " + (f"[{phone}](tel:{tel})" if tel else "магазина")
    cancel += ". Если заказ оплачен онлайн, деньги вернутся на карту."
    if constructor:
        cancel += " Индивидуальный букет после сборки не возвращается."

    return [
        {"title": "Доставка и самовывоз", "items": [
            {"q": "Сколько стоит доставка?", "a": cost},
            {"q": "Можно заказать на сегодня?", "a": today},
            {"q": "Можно забрать букет самому?", "a": pickup},
            {"q": "Не знаю точный адрес получателя — что делать?",
             "a": "Укажите телефон получателя и примерный район. Флорист сам позвонит и узнает, куда и когда удобно "
                  "привезти, — не говоря, что это цветы."},
            {"q": "Можно сделать сюрприз или отправить анонимно?",
             "a": "Да. Для сюрприза курьер позвонит получателю только у двери. Отправителя курьер не назовёт, "
                  "а открытку можно оставить без подписи."},
        ]},
        {"title": "Заказ и оплата", "items": [
            {"q": "Букеты из каталога точно есть в наличии?",
             "a": "Да. Остатки общие для сайта, ботов и магазина, поэтому на сайте только то, что сегодня есть "
                  "в мастерской. На время оплаты букет резервируется за вами."},
            {"q": "Как оплатить заказ?", "a": pay},
            {"q": "Увижу ли я букет до доставки?", "a": photo},
            {"q": "Как узнать, где мой заказ?", "a": track},
            {"q": "Можно отменить заказ?", "a": cancel},
        ]},
    ]


def faq_blocks(s):
    """Что показывать на сайте: блоки владельца или стандартные."""
    return s.faq if s.faq is not None else default_faq(s)


def clean_faq(blocks):
    """Проверяет блоки из админки. Пустые строки (без вопроса и ответа) и пустые блоки без названия убираются.
    Поле ошибки — faq.<блок>.title или faq.<блок>.<вопрос>.q|a (номера с нуля, как в форме)."""
    if not isinstance(blocks, list):
        v.fail("faq", "Некорректные данные")
    if len(blocks) > FAQ_MAX_BLOCKS:
        v.fail("faq", f"Не больше {FAQ_MAX_BLOCKS} блоков")
    out, total = [], 0
    for bi, b in enumerate(blocks):
        if not isinstance(b, dict):
            v.fail(f"faq.{bi}.title", "Некорректный блок")
        title = v.text(b.get("title"), f"faq.{bi}.title", "Название блока", max_len=120)
        raw = b.get("items") or []
        if not isinstance(raw, list):
            v.fail(f"faq.{bi}.title", "Некорректный список вопросов")
        items = []
        for ii, it in enumerate(raw):
            if not isinstance(it, dict):
                v.fail(f"faq.{bi}.{ii}.q", "Некорректный вопрос")
            q = v.text(it.get("q"), f"faq.{bi}.{ii}.q", "Вопрос", max_len=200)
            a = v.text(it.get("a"), f"faq.{bi}.{ii}.a", "Ответ", max_len=5000, multiline=True)
            if not q and not a:
                continue
            if not q:
                v.fail(f"faq.{bi}.{ii}.q", "Впишите вопрос")
            if not a:
                v.fail(f"faq.{bi}.{ii}.a", "Впишите ответ")
            items.append({"q": q, "a": a})
        if len(items) > FAQ_MAX_ITEMS:
            v.fail(f"faq.{bi}.title", f"В одном блоке — не больше {FAQ_MAX_ITEMS} вопросов")
        total += len(items)
        if not title and not items:
            continue
        out.append({"title": title, "items": items})
    if total > FAQ_MAX_TOTAL:
        v.fail("faq", f"Всего не больше {FAQ_MAX_TOTAL} вопросов")
    return out


# ------------------------------------------------------------------ поисковики (SEO)

# ключ, адрес, подпись в админке
SEO_PAGES = [
    ("home", "/", "Главная"),
    ("bouquets", "/bouquets", "Готовые букеты"),
    ("flowers", "/flowers", "Цветы поштучно"),
    ("constructor", "/constructor", "Собрать букет"),
    ("delivery", "/delivery", "Доставка и оплата"),
    ("about", "/about", "О нас"),
    ("contacts", "/contacts", "Контакты"),
    ("product", "/product/…", "Страницы товаров (шаблон)"),
]
SEO_KEYS = [k for k, _, _ in SEO_PAGES]
SEO_TITLE_MAX = 120
SEO_DESCRIPTION_MAX = 300
VERIFY_RE = re.compile(r"^[A-Za-z0-9_\-]{6,100}$")


def seo_defaults(s):
    shop, city = s.shop_name, s.city
    area = delivery_area(city)
    return {
        "home": {"title": f"{shop} — доставка цветов и букетов в {city}",
                 "description": f"Цветочная мастерская в {city}: букеты в наличии, цветы поштучно, доставка "
                                f"{area} и самовывоз. Заказ на сайте, в Telegram и ВКонтакте."},
        "bouquets": {"title": f"Готовые букеты с доставкой в {city} — {shop}",
                     "description": f"Букеты в наличии с фото и ценами. Доставка {area}, самовывоз. "
                                    "Фото букета перед отправкой."},
        "flowers": {"title": f"Цветы поштучно в {city} — {shop}",
                    "description": "Розы, хризантемы, тюльпаны и другие цветы поштучно, зелень. Соберём букет "
                                   f"из выбранных цветов, доставка {area}."},
        "constructor": {"title": f"Собрать свой букет онлайн — {shop}",
                        "description": "Конструктор букета: выберите цветы, упаковку и ленту — флорист соберёт "
                                       "букет по вашему эскизу."},
        "delivery": {"title": f"Доставка цветов в {city}: зоны, цены, оплата — {shop}",
                     "description": f"Стоимость доставки цветов {area} по зонам на карте, интервалы, онлайн-оплата, "
                                    "самовывоз."},
        "about": {"title": f"О нас — {shop}",
                  "description": (s.about_lead or f"Цветочная мастерская {shop} в {city}.")[:SEO_DESCRIPTION_MAX]},
        "contacts": {"title": f"Контакты — {shop}, {city}",
                     "description": " ".join(x for x in (
                         f"Адрес: {s.address}." if s.address else "", f"Телефон: {s.phone}." if s.phone else "",
                         s.working_hours or "") if x)[:SEO_DESCRIPTION_MAX] or f"Контакты магазина {shop}."},
        "product": {"title": f"{{name}} — купить в {city} | {shop}",
                    "description": f"{{name}} за {{price}}. {{description}} Доставка {area}, самовывоз."},
    }


def seo_pages(s):
    """Итоговые заголовки: то, что вписал владелец, а пустые поля — стандартный текст."""
    defaults = seo_defaults(s)
    own = s.seo_pages or {}
    out = {}
    for k in SEO_KEYS:
        mine = own.get(k) or {}
        out[k] = {f: (mine.get(f) or "").strip() or defaults[k][f] for f in ("title", "description")}
    return out


def clean_seo_pages(d):
    if not isinstance(d, dict):
        v.fail("seo_pages", "Некорректные данные")
    out = {}
    for k in SEO_KEYS:
        page = d.get(k) or {}
        if not isinstance(page, dict):
            v.fail(f"seo.{k}.title", "Некорректные данные")
        title = v.text(page.get("title"), f"seo.{k}.title", "Заголовок", max_len=SEO_TITLE_MAX)
        desc = v.text(page.get("description"), f"seo.{k}.description", "Описание", max_len=SEO_DESCRIPTION_MAX)
        if title or desc:
            out[k] = {"title": title, "description": desc}
    return out


def clean_verification(value, field, label):
    """Принимает сам код или целиком тег <meta name="…" content="код"> — из тега берём content."""
    value = (value or "").strip() if isinstance(value, str) else ""
    m = re.search(r'content\s*=\s*["\']([^"\']+)["\']', value)
    if m:
        value = m.group(1).strip()
    if value and not VERIFY_RE.match(value):
        v.fail(field, f"{label}: вставьте код из кабинета (латинские буквы и цифры) или весь тег <meta …>")
    return value


def site_url():
    return dj_settings.FRONTEND_URL.rstrip("/")


def organization(s, media_url):
    """Разметка schema.org «Цветочный магазин» (JSON-LD) — поисковики показывают по ней адрес, телефон, часы."""
    url = site_url()
    data = {
        "@context": "https://schema.org", "@type": "Florist", "name": s.shop_name, "url": url + "/",
        "address": {"@type": "PostalAddress", "streetAddress": s.address, "addressLocality": s.city,
                    "addressCountry": "RU"},
        "geo": {"@type": "GeoCoordinates", "latitude": s.shop_lat, "longitude": s.shop_lon},
        "openingHoursSpecification": [{
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "opens": s.open_time.strftime("%H:%M") if hasattr(s.open_time, "strftime") else str(s.open_time)[:5],
            "closes": s.close_time.strftime("%H:%M") if hasattr(s.close_time, "strftime") else str(s.close_time)[:5],
        }],
        "priceRange": "₽₽",
    }
    if s.phone:
        data["telephone"] = s.phone
    if s.email:
        data["email"] = s.email
    image = media_url(s.hero_image) or media_url(s.logo)
    if image:
        data["image"] = image if image.startswith("http") else url + image
    same = [x for x in (s.vk_url, s.telegram_url) if x]
    if same:
        data["sameAs"] = same
    return data
