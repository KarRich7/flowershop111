"""Настройки Django. Все секреты и параметры окружения читаются из переменных окружения."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [x.strip() for x in str(env(name, default)).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
# PRODUCTION=true — боевой режим (docker-compose.prod.yml): небезопасные настройки не дают запуститься,
# тестовые функции (симулятор оплаты, тестовый вход, Swagger, Django-admin) выключены.
PRODUCTION = env_bool("PRODUCTION", False)
# Значения-заглушки из .env.example: считаются «не заданными»
PLACEHOLDER_SECRETS = {"", "change-me", "change-me-to-a-long-random-string", "change-me-simulator-secret",
                       "change-me-bot-service-token", "dev-insecure-key-change-me", "dev-simulator-secret"}


def secret_env(name, default=""):
    value = (env(name, default) or "").strip()
    return "" if value in PLACEHOLDER_SECRETS else value


SECRET_KEY = secret_env("DJANGO_SECRET_KEY")
SECRET_KEY_IS_WEAK = len(SECRET_KEY) < 32
if not SECRET_KEY:
    if PRODUCTION:
        raise RuntimeError("Задайте DJANGO_SECRET_KEY в .env. Сгенерировать: docker compose run --rm --no-deps backend gen-secrets")
    # Тестовый стенд без ключа: ключ-заглушка (сессии и подписи адресов не переживут смену ключа)
    SECRET_KEY = env("DJANGO_SECRET_KEY") or "dev-insecure-key-change-me"
if PRODUCTION:
    if DEBUG:
        raise RuntimeError("PRODUCTION=true несовместим с DJANGO_DEBUG=true")
    if SECRET_KEY_IS_WEAK:
        raise RuntimeError("DJANGO_SECRET_KEY слишком короткий (нужно от 32 символов). Сгенерировать: docker compose run --rm --no-deps backend gen-secrets")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "corsheaders",
    "apps.core",
    "apps.inventory",
    "apps.catalog",
    "apps.recipes",
    "apps.customers",
    "apps.delivery",
    "apps.carts",
    "apps.orders",
    "apps.reservations",
    "apps.payments",
    "apps.notifications",
    "apps.bots",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "flowers"),
        "USER": env("POSTGRES_USER", "flowers"),
        "PASSWORD": env("POSTGRES_PASSWORD", "flowers"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
        "TEST": {"NAME": "test_flowers"},
    }
}

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("SHOP_TIME_ZONE", "Asia/Yekaterinburg")  # пермское время, UTC+5 (отдельного пояса для Перми в базе tz нет)
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
DEMO_MEDIA_ROOT = BASE_DIR / "demo_media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.api.auth.BearerTokenAuthentication",
        "apps.api.auth.CookieTokenAuthentication",
        "apps.api.auth.BotServiceAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.api.errors.exception_handler",
    # Общий лимит на все запросы API (по IP покупателя, у сотрудника — по учётной записи) + отдельные лимиты
    # на вход, оформление заказа и поиск адресов. Запросы из внутренней сети (сервер сайта) не ограничиваются.
    "DEFAULT_THROTTLE_CLASSES": ["apps.api.auth.BurstThrottle", "apps.api.auth.SustainedThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "burst": env("THROTTLE_BURST", "180/min"), "sustained": env("THROTTLE_SUSTAINED", "3000/hour"),
        "staff_burst": "600/min", "staff_sustained": "20000/hour",
        "login": "10/min", "checkout": "6/min", "checkout_hour": "20/hour", "lookup": "10/min",
        "simulator": "120/min", "geo": "30/min", "geo_day": "600/day",
        "customer_login": "12/min", "customer_poll": "120/min", "password": "5/min",
    },
    # Сколько прокси стоит перед Django: Caddy (прод) или сервер Next.js (тестовый стенд) — 1.
    # IP покупателя берётся из X-Forwarded-For, который выставляет ближайший к нему прокси.
    "NUM_PROXIES": int(env("TRUSTED_PROXY_COUNT", "1")),
}
# Локально (без PRODUCTION) все запросы приходят из сети Docker с одного адреса — их не ограничиваем по IP.
THROTTLE_INTERNAL_EXEMPT = env_bool("THROTTLE_INTERNAL_EXEMPT", not PRODUCTION)
SPECTACULAR_SETTINGS = {
    "TITLE": "Цветочный магазин — API",
    "DESCRIPTION": "Единый API сайта, Telegram-бота, ВК-бота и админ-панели (тестовая версия).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_HEADERS = ("accept", "authorization", "content-type", "origin", "user-agent", "x-csrftoken",
                      "x-requested-with", "idempotency-key", "x-customer-token")

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_IGNORE_RESULT = True
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = TIME_ZONE

CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if env_bool("USE_REDIS_CACHE", True)
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    )
}

# --- Публичные адреса (ссылки в ботах, уведомлениях и платёжном симуляторе)
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:3000").rstrip("/")
BACKEND_PUBLIC_URL = env("BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")

# --- Боты
def _clean(value):
    """Токены вставляют в .env вручную: убираем пробелы, кавычки и невидимый \r из Windows."""
    return str(value or "").strip().strip("\"'").strip()


TELEGRAM_BOT_TOKEN = _clean(env("TELEGRAM_BOT_TOKEN", ""))
# Имя бота без @ — для ссылок входа t.me/<имя>?start=…; если пусто, берётся из ссылки на бота в настройках или getMe
TELEGRAM_BOT_USERNAME = _clean(env("TELEGRAM_BOT_USERNAME", "")).lstrip("@")
TELEGRAM_STAFF_CHAT_ID = _clean(env("TELEGRAM_STAFF_CHAT_ID", ""))
# Прокси для Telegram, если с сервера нет прямой связи с api.telegram.org (блокировка у провайдера):
# http://логин:пароль@IP:порт или socks5://логин:пароль@IP:порт. Пусто — напрямую.
TELEGRAM_PROXY = _clean(env("TELEGRAM_PROXY", ""))
# Свой адрес Bot API (зеркало/локальный сервер Bot API); обычно не нужен
TELEGRAM_API_BASE = (_clean(env("TELEGRAM_API_BASE", "")) or "https://api.telegram.org").rstrip("/")
VK_GROUP_TOKEN = _clean(env("VK_GROUP_TOKEN", ""))
# номер сообщества без минуса и без «club»/«public» (частая ошибка при копировании)
VK_GROUP_ID = _clean(env("VK_GROUP_ID", "")).lstrip("-").removeprefix("club").removeprefix("public")
VK_API_VERSION = env("VK_API_VERSION", "5.199")
# Куда в ВК присылать уведомления сотрудникам (новые заказы, обращения): беседа владельца и флористов
# (номер 2000000001…, бот сообщает его сам, когда сообщество добавят в беседу) или Id одного человека. Пусто — не присылать.
VK_STAFF_PEER_ID = _clean(env("VK_STAFF_PEER_ID", ""))
BOT_SERVICE_TOKEN = secret_env("BOT_SERVICE_TOKEN")
# Через сколько часов забытая смена сотрудника закрывается сама (уведомления о заказах перестают приходить)
STAFF_SHIFT_MAX_HOURS = int(env("STAFF_SHIFT_MAX_HOURS", "14"))
STAFF_TOKEN_TTL_HOURS = int(env("STAFF_TOKEN_TTL_HOURS", "72"))
# Тестовый вход покупателя без настоящего бота: на сайте появляется кнопка «Подтвердить вход (тест)». Только для разработки!
CUSTOMER_LOGIN_TEST_MODE = env_bool("CUSTOMER_LOGIN_TEST_MODE", False) and not PRODUCTION
BOT_SIMULATOR_ENABLED = env_bool("BOT_SIMULATOR_ENABLED", False) and not PRODUCTION  # отладочный эндпоинт движка ботов

# --- Платежи
# simulator — тестовая оплата (деньги не списываются); rollypay — RollyPay (нужны ROLLYPAY_API_KEY и
# ROLLYPAY_SIGNING_SECRET); yookassa — ЮKassa (запасной вариант: YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY)
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", "simulator").strip().lower()
# Подпись уведомлений симулятора. Без своего значения выводится из DJANGO_SECRET_KEY (у каждой установки своя)
PAYMENT_SIMULATOR_SECRET = secret_env("PAYMENT_SIMULATOR_SECRET")
if not PAYMENT_SIMULATOR_SECRET:
    import hashlib as _hashlib

    PAYMENT_SIMULATOR_SECRET = _hashlib.sha256(f"payment-simulator:{SECRET_KEY}".encode()).hexdigest()
# Онлайн-оплата на сайте и в ботах: auto — включена с настоящим провайдером; с симулятором — только не в PRODUCTION
# (чтобы покупатель не «оплатил» заказ тестовой кнопкой). on | off — принудительно.
ONLINE_PAYMENTS = env("ONLINE_PAYMENTS", "auto").strip().lower()
ONLINE_PAYMENTS_ENABLED = (ONLINE_PAYMENTS == "on" or (ONLINE_PAYMENTS == "auto"
                                                       and (PAYMENT_PROVIDER != "simulator" or not PRODUCTION)))
# RollyPay (docs.rollypay.io): ключ кассы и секрет подписи уведомлений выдаются при создании кассы
ROLLYPAY_API_KEY = secret_env("ROLLYPAY_API_KEY")
ROLLYPAY_SIGNING_SECRET = secret_env("ROLLYPAY_SIGNING_SECRET")
ROLLYPAY_API_URL = env("ROLLYPAY_API_URL", "https://rollypay.io").rstrip("/")
# true — тестовые платежи (деньги не списываются, на форме оплаты кнопки симуляции). Сначала проверьте так!
ROLLYPAY_TEST_MODE = env_bool("ROLLYPAY_TEST_MODE", False)
# Способ оплаты: пусто — покупатель выбирает на форме RollyPay; sbp | card — сразу этот способ
ROLLYPAY_PAYMENT_METHOD = env("ROLLYPAY_PAYMENT_METHOD", "").strip().lower()
# Сколько секунд уведомление с подписью считается свежим (RollyPay повторяет доставку около часа)
ROLLYPAY_WEBHOOK_TOLERANCE = int(env("ROLLYPAY_WEBHOOK_TOLERANCE", "7200"))
YOOKASSA_SHOP_ID = env("YOOKASSA_SHOP_ID", "").strip()
YOOKASSA_SECRET_KEY = secret_env("YOOKASSA_SECRET_KEY")
YOOKASSA_API_URL = env("YOOKASSA_API_URL", "https://api.yookassa.ru/v3").rstrip("/")
# Чеки 54-ФЗ через «Чеки от ЮKassa» или подключённую онлайн-кассу: true — передавать состав заказа в платеже
YOOKASSA_SEND_RECEIPT = env_bool("YOOKASSA_SEND_RECEIPT", False)
YOOKASSA_VAT_CODE = int(env("YOOKASSA_VAT_CODE", "1"))  # 1 — без НДС
YOOKASSA_TAX_SYSTEM_CODE = env("YOOKASSA_TAX_SYSTEM_CODE", "").strip()  # 1–6, если касса требует систему налогообложения
# Защита от накрутки: сколько неоплаченных/неподтверждённых заказов может висеть на одном телефоне
MAX_PENDING_ORDERS_PER_PHONE = int(env("MAX_PENDING_ORDERS_PER_PHONE", "3"))

# --- Карты и проверка адресов
# YANDEX_MAPS_API_KEY — ключ «JavaScript API и HTTP Геокодер» (developer.tech.yandex.ru): карта на сайте
# и геокодер на сервере. YANDEX_GEOCODER_API_KEY — отдельный серверный ключ геокодера (необязательно).
# Модель IS-Net для автоматической вырезки фона на фото цветов (скачивается при сборке Docker-образа).
# Если файла нет, работает простой алгоритм для однотонного фона.
CUTOUT_MODEL_PATH = env("CUTOUT_MODEL_PATH", str(BASE_DIR / "models" / "isnet-general-use.onnx"))
YANDEX_MAPS_API_KEY = env("YANDEX_MAPS_API_KEY", "")
YANDEX_GEOCODER_API_KEY = env("YANDEX_GEOCODER_API_KEY", "") or YANDEX_MAPS_API_KEY
# auto — Яндекс при наличии ключа, иначе Nominatim (OpenStreetMap); yandex | nominatim | off
GEOCODER_PROVIDER = env("GEOCODER_PROVIDER", "auto")
NOMINATIM_URL = env("NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/")
GEOCODER_USER_AGENT = env("GEOCODER_USER_AGENT", "CvetyUrala-shop/1.0 (+https://example.com)")
GEOCODER_TIMEOUT = float(env("GEOCODER_TIMEOUT", "6"))
# Бесплатный тариф Яндекса — 1000 запросов в сутки. После лимита адреса до полуночи ищет OpenStreetMap,
# чтобы злоумышленник не «выжег» квоту и не заблокировал ключ. 0 — без ограничения.
YANDEX_GEOCODER_DAILY_LIMIT = int(env("YANDEX_GEOCODER_DAILY_LIMIT", "900"))
# Насколько точка на карте может отличаться от найденного геокодером адреса
ADDRESS_MAX_DISTANCE_M = int(env("ADDRESS_MAX_DISTANCE_M", "400"))

# --- Безопасность
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SECURE_COOKIES = env_bool("SECURE_COOKIES", PRODUCTION)
if not DEBUG:
    SESSION_COOKIE_SECURE = SECURE_COOKIES
    CSRF_COOKIE_SECURE = SECURE_COOKIES
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    if SECURE_COOKIES:
        # Сайт работает только по HTTPS: браузер запомнит это на год (HSTS)
        SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
# Django-admin (/django-admin/) и Swagger (/api/docs/) — инструменты разработчика; в PRODUCTION выключены
DJANGO_ADMIN_ENABLED = env_bool("DJANGO_ADMIN_ENABLED", not PRODUCTION)
API_DOCS_ENABLED = env_bool("API_DOCS_ENABLED", not PRODUCTION)
# Плашка «Демо-версия» и подписи о демо-фото на сайте
SHOW_DEMO_NOTICE = env_bool("SHOW_DEMO_NOTICE", not PRODUCTION)
# Вход сотрудников: после LOGIN_MAX_FAILS неверных паролей логин блокируется на LOGIN_LOCK_MINUTES
LOGIN_MAX_FAILS = int(env("LOGIN_MAX_FAILS", "5"))
LOGIN_LOCK_MINUTES = int(env("LOGIN_LOCK_MINUTES", "15"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    # секретные токены из ссылок на заказ/оплату/корзину в журнале заменяются на *** (config/log_masking.py)
    "filters": {"mask_secrets": {"()": "config.log_masking.MaskSecretsFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain", "filters": ["mask_secrets"]}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
