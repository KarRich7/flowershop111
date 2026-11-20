"""Проверка безопасности установки: что ещё нужно настроить владельцу перед работой с настоящими покупателями.

Используется в админке (Настройки → Безопасность, плашка на главной) и командой
`python manage.py security_check`. Секреты в ответ не попадают — только вывод «задан / не задан».
"""
from urllib.parse import urlparse

from django.conf import settings

DEMO_PASSWORDS = ("owner12345", "florist12345", "courier12345")


def _item(code, level, title, detail="", fix=""):
    return {"code": code, "level": level, "title": title, "detail": detail, "fix": fix}


def has_demo_password(u):
    """Проверка хеша дорогая (PBKDF2), поэтому результат кэшируется до смены пароля."""
    import hashlib

    from django.core.cache import cache

    key = "demo_pw:%s:%s" % (u.pk, hashlib.sha256(u.password.encode()).hexdigest()[:16])
    hit = cache.get(key)
    if hit is None:
        hit = any(u.check_password(p) for p in DEMO_PASSWORDS)
        cache.set(key, hit, 24 * 3600)
    return hit


def _staff_with_demo_password():
    from apps.core.models import User

    return [u for u in User.objects.filter(is_active=True) if has_demo_password(u)]


def run_checks():
    from apps.core.models import User
    from apps.customers.models import Customer
    from apps.orders.models import Order

    prod = settings.PRODUCTION
    items = []

    if settings.DEBUG:
        items.append(_item("debug", "critical", "Включён режим отладки",
                           "DJANGO_DEBUG=true показывает посетителям технические подробности ошибок.",
                           "В .env: DJANGO_DEBUG=false"))
    if settings.SECRET_KEY_IS_WEAK:
        items.append(_item("secret_key", "critical", "Секретный ключ не задан или слишком короткий",
                           "DJANGO_SECRET_KEY подписывает ссылки и адреса. Со стандартным ключом их можно подделать.",
                           "docker compose run --rm --no-deps backend gen-secrets → вставить в .env"))
    weak = _staff_with_demo_password()
    if weak:
        names = ", ".join(u.username for u in weak)
        items.append(_item("demo_passwords", "critical", "Стандартный пароль у сотрудников: " + names,
                           "Пароли демо-версии (owner12345 и т. п.) известны всем, кто видел проект.",
                           "Админка → внизу меню «Сменить пароль» (пароли сотрудников — Админка → Сотрудники)"))
    if settings.CUSTOMER_LOGIN_TEST_MODE:
        items.append(_item("test_login", "critical", "Включён тестовый вход покупателей",
                           "Кнопка «Подтвердить (тест)» позволяет войти без мессенджера.",
                           "В .env: CUSTOMER_LOGIN_TEST_MODE=false"))
    if settings.PAYMENT_PROVIDER == "simulator":
        if settings.ONLINE_PAYMENTS_ENABLED:
            items.append(_item("payment_simulator", "critical" if prod else "warning",
                               "Онлайн-оплата работает в тестовом режиме",
                               "Покупатель «оплачивает» заказ кнопкой симулятора — деньги не поступают.",
                               "Подключите RollyPay (PAYMENT_PROVIDER=rollypay, см. docs/DEPLOY.md) или выключите онлайн-оплату: ONLINE_PAYMENTS=off"))
        else:
            items.append(_item("payment_off", "info", "Онлайн-оплата выключена",
                               "Заказы принимаются с оплатой при получении, флорист подтверждает их звонком.",
                               "Для оплаты по СБП и картой подключите RollyPay: PAYMENT_PROVIDER=rollypay (docs/DEPLOY.md)"))
    elif settings.PAYMENT_PROVIDER == "rollypay":
        if not (settings.ROLLYPAY_API_KEY and settings.ROLLYPAY_SIGNING_SECRET):
            items.append(_item("rollypay", "critical", "RollyPay выбран, но ключи не заданы",
                               "Без ROLLYPAY_API_KEY оплата не создаётся, без ROLLYPAY_SIGNING_SECRET не принимаются "
                               "уведомления об оплате.",
                               "Ключ кассы и секрет подписи выдаёт RollyPay при создании кассы → впишите их в .env"))
        elif settings.ROLLYPAY_TEST_MODE:
            items.append(_item("rollypay_test", "critical" if prod else "warning",
                               "RollyPay в тестовом режиме",
                               "Платежи тестовые: заказ «оплачивается» кнопкой на форме RollyPay, деньги не поступают.",
                               "После проверки оплаты в .env: ROLLYPAY_TEST_MODE=false"))
    elif settings.PAYMENT_PROVIDER == "yookassa" and not (settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY):
        items.append(_item("yookassa", "critical", "ЮKassa выбрана, но ключи не заданы",
                           "Без YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY оплата не создаётся.",
                           "Личный кабинет ЮKassa → Интеграция → Ключи API"))
    if not settings.SECURE_COOKIES:
        items.append(_item("https", "critical" if prod else "warning", "Сайт работает без HTTPS",
                           "Без шифрования пароли сотрудников и данные покупателей можно перехватить в сети.",
                           "Запуск с доменом: docker-compose.prod.yml (Caddy сам получит сертификат)"))
    front = urlparse(settings.FRONTEND_URL)
    if prod and (front.hostname in ("localhost", "127.0.0.1") or front.scheme != "https"):
        items.append(_item("frontend_url", "critical", "FRONTEND_URL указывает не на ваш домен",
                           f"Сейчас: {settings.FRONTEND_URL}. Ссылки в ботах и на оплату будут вести не туда.",
                           "В .env: SITE_DOMAIN=ваш-домен.ru (FRONTEND_URL выставится сам)"))
    if (settings.DATABASES["default"].get("PASSWORD") or "") in ("flowers", "postgres", ""):
        items.append(_item("db_password", "warning", "Стандартный пароль базы данных",
                           "База доступна только внутри Docker, но стандартный пароль лучше сменить.",
                           "См. docs/SECURITY.md → «Пароль базы данных»"))
    if settings.BOT_SIMULATOR_ENABLED:
        items.append(_item("bot_simulator", "warning", "Включён отладочный симулятор ботов",
                           "Эндпоинт /api/v1/simulator/* нужен только разработчику.", "В .env: BOT_SIMULATOR_ENABLED=false"))
    if settings.API_DOCS_ENABLED or settings.DJANGO_ADMIN_ENABLED:
        parts = [n for n, on in (("Swagger /api/docs/", settings.API_DOCS_ENABLED),
                                 ("Django-admin /django-admin/", settings.DJANGO_ADMIN_ENABLED)) if on]
        items.append(_item("dev_tools", "warning" if prod else "info", "Открыты инструменты разработчика: " + ", ".join(parts),
                           "Лишние страницы входа — лишние цели для подбора паролей.",
                           "В .env: API_DOCS_ENABLED=false и DJANGO_ADMIN_ENABLED=false (в PRODUCTION — по умолчанию)"))
    if settings.BOT_SERVICE_TOKEN and len(settings.BOT_SERVICE_TOKEN) < 24:
        items.append(_item("bot_token", "warning", "Короткий BOT_SERVICE_TOKEN",
                           "Сервисный токен открывает API от имени бота.", "Сгенерируйте новый: gen-secrets"))
    if Order.objects.filter(is_demo=True).exists() or Customer.objects.filter(is_demo=True).exists():
        items.append(_item("demo_data", "info", "В базе есть демо-заказы и демо-покупатели",
                           "Они мешают статистике и путают сотрудников.",
                           "docker compose exec backend python manage.py clear_demo --yes"))
    if User.objects.filter(is_demo=True).exclude(role=User.Role.OWNER).exists():
        items.append(_item("demo_staff", "warning", "Остались демо-сотрудники",
                           "Учётные записи демо-версии с известными паролями.", "Админка → Сотрудники"))
    if not settings.YANDEX_MAPS_API_KEY:
        items.append(_item("maps_key", "info", "Не задан ключ Яндекс Карт",
                           "Карта работает в ограниченном режиме, адреса ищет OpenStreetMap.",
                           "Настройки → «Карта и поиск адресов»"))
    order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: order[i["level"]])
    return {
        "production": prod,
        "critical": sum(1 for i in items if i["level"] == "critical"),
        "warnings": sum(1 for i in items if i["level"] == "warning"),
        "items": items,
    }
