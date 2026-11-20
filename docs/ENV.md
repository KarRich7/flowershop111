# Переменные окружения

Шаблон — `.env.example` (скопируйте в `.env`). В Docker Compose `POSTGRES_HOST`, `REDIS_URL`
и `MEDIA_ROOT` переопределяются автоматически. **Секреты не хранятся в коде.**

| Переменная | Обязательна | По умолчанию | Назначение |
|---|:-:|---|---|
| `PRODUCTION` | | `false` | Боевой режим: Secure-cookies, HSTS, лимиты и для внутренней сети, выключены симулятор оплаты, Swagger, Django admin и демо-надписи; запрещён `DJANGO_DEBUG=true` и короткий секретный ключ |
| `SITE_DOMAIN` / `ACME_EMAIL` | для `docker-compose.prod.yml` | — | Домен сайта и почта Let's Encrypt (Caddy, HTTPS); из домена подставляются `FRONTEND_URL`, хосты, CSRF/CORS |
| `SITE_BIND` | | `127.0.0.1` | На каком адресе компьютера открыт сайт `:3000`; `0.0.0.0` — доступ с телефона в той же Wi-Fi сети |
| `SITE_INDEXING` | | `false` (prod-compose: `true`) | Разрешить поисковикам индексировать сайт (`/robots.txt`) |
| `OWNER_USERNAME` / `OWNER_PASSWORD` | | `owner` / пусто | Владелец, создаётся при старте, если его нет в базе (`ensure_owner`); пароль от 10 символов. Демо-заполнение без пароля — `owner12345` (сайт попросит сменить) |
| `DJANGO_SECRET_KEY` | **да** (при `PRODUCTION=true`) | — | Секретный ключ Django, от 32 символов (`docker compose run --rm --no-deps backend gen-secrets`) |
| `DJANGO_DEBUG` | | `false` | Режим отладки (только для разработки) |
| `DJANGO_ALLOWED_HOSTS` | | `localhost,127.0.0.1,backend` | Разрешённые хосты |
| `CSRF_TRUSTED_ORIGINS` | | `http://localhost:3000` | Доверенные origin (Django admin) |
| `CORS_ALLOWED_ORIGINS` | | `http://localhost:3000` | CORS для прямых запросов к API |
| `SECURE_COOKIES` | | = `PRODUCTION` | Secure-cookie (только HTTPS) |
| `STAFF_TOKEN_TTL_HOURS` | | `72` | Срок действия токена входа сотрудника |
| `LOGIN_MAX_FAILS` / `LOGIN_LOCK_MINUTES` | | `5` / `15` | Блокировка входа под логином после N неверных паролей на M минут |
| `DJANGO_ADMIN_ENABLED` / `API_DOCS_ENABLED` | | = не `PRODUCTION` | Технический Django admin `/django-admin/` и Swagger `/api/docs/` |
| `SHOW_DEMO_NOTICE` | | = не `PRODUCTION` | Надписи «тестовый магазин» на сайте |
| `THROTTLE_BURST` / `THROTTLE_SUSTAINED` | | `180/min` / `3000/hour` | Общий лимит запросов к API с одного IP (у сотрудников — 600/min, 20000/hour) |
| `THROTTLE_INTERNAL_EXEMPT` | | = не `PRODUCTION` | Не ограничивать запросы из локальной сети/Docker (тесты на своём компьютере) |
| `TRUSTED_PROXY_COUNT` | | `1` | Сколько прокси перед backend; IP покупателя берётся из `X-Forwarded-For` |
| `MAX_PENDING_ORDERS_PER_PHONE` | | `3` | Лимит неоплаченных/неподтверждённых заказов на телефон (`0` — без лимита) |
| `LOG_LEVEL` | | `INFO` | Уровень логирования |
| `SHOP_TIME_ZONE` | | `Asia/Yekaterinburg` | Часовой пояс магазина. Пермь и Кондратово живут по этому поясу (UTC+5): в базе часовых поясов он называется по Екатеринбургу |
| `POSTGRES_HOST` / `POSTGRES_PORT` | | `localhost` / `5432` | PostgreSQL |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | **да** | `flowers` | База и учётная запись |
| `POSTGRES_CONN_MAX_AGE` | | `60` | Постоянные соединения, с |
| `REDIS_URL` | **да** | `redis://localhost:6379/0` | Redis (кэш, брокер Celery) |
| `CELERY_BROKER_URL` | | = `REDIS_URL` | Брокер Celery |
| `USE_REDIS_CACHE` | | `true` | Кэш в Redis (иначе — в памяти процесса) |
| `CELERY_TASK_ALWAYS_EAGER` | | `false` | Выполнять задачи синхронно (тесты/отладка) |
| `FRONTEND_URL` | **да** | `http://localhost:3000` | Публичный адрес сайта (ссылки на оплату и статус заказа в ботах) |
| `BACKEND_PUBLIC_URL` | | `http://localhost:8000` | Публичный адрес API |
| `MEDIA_ROOT` | | `backend/media` | Каталог загруженных фото |
| `PAYMENT_PROVIDER` | | `simulator` | `simulator` (тест, деньги не списываются), `rollypay` (RollyPay — основной) или `yookassa` (запасной) |
| `ONLINE_PAYMENTS` | | `auto` | `auto` — онлайн-оплата с кассой (RollyPay/ЮKassa) всегда, с симулятором — только при `PRODUCTION=false`; `on` / `off` — принудительно. Без онлайн-оплаты заказы принимаются с оплатой при получении |
| `ROLLYPAY_API_KEY` / `ROLLYPAY_SIGNING_SECRET` | для RollyPay | пусто | Ключ кассы (`rpk_live_…`) и секрет подписи уведомлений; в кассе callback_url — `https://<домен>/api/v1/payments/webhook/rollypay` |
| `ROLLYPAY_TEST_MODE` | | `false` | `true` — тестовые платежи без денег (кнопки симуляции на форме RollyPay) |
| `ROLLYPAY_PAYMENT_METHOD` | | пусто | `sbp` / `card` — сразу этот способ; пусто — выбор на форме RollyPay |
| `ROLLYPAY_API_URL` / `ROLLYPAY_WEBHOOK_TOLERANCE` | | `https://rollypay.io` / `7200` | Адрес API; сколько секунд подписанное уведомление считается свежим |
| `YOOKASSA_SHOP_ID` / `YOOKASSA_SECRET_KEY` | для ЮKassa | пусто | Ключи магазина ЮKassa; уведомления — `https://<домен>/api/v1/payments/webhook/yookassa` |
| `YOOKASSA_SEND_RECEIPT` / `YOOKASSA_VAT_CODE` / `YOOKASSA_TAX_SYSTEM_CODE` | | `false` / `1` / пусто | Чек 54-ФЗ через ЮKassa: передавать состав заказа, код НДС, система налогообложения |
| `PAYMENT_SIMULATOR_SECRET` | **да** (при `DEBUG=false`) | — | HMAC-секрет webhook симулятора |
| `TELEGRAM_BOT_TOKEN` | для Telegram | пусто | Токен @BotFather; пусто → бот не запускается, вход через Telegram на сайте скрыт |
| `TELEGRAM_BOT_USERNAME` | | пусто | Имя бота без `@` для ссылок входа `t.me/<бот>?start=login_…`; пусто → берётся из ссылки «Telegram» в настройках или через `getMe` |
| `TELEGRAM_STAFF_CHAT_ID` | | пусто | Необязательная общая группа Telegram для всех уведомлений сотрудникам (`-100…`; бот пишет номер сам, когда его добавляют в группу, или по `/chatid`). Основной способ — личные уведомления по сменам (привязка в админке) |
| `VK_STAFF_PEER_ID` | | пусто | То же для беседы ВК (`2000000001…`; бот пишет номер, когда сообщество добавляют в беседу) или Id одного человека |
| `STAFF_SHIFT_MAX_HOURS` | | `14` | Через сколько часов забытая смена закрывается сама (Celery beat, проверка раз в 10 мин) |
| `TELEGRAM_PROXY` | | пусто | Прокси для всех обращений к Telegram (бот, уведомления, вход): `http://логин:пароль@IP:порт` или `socks5://логин:пароль@IP:порт`. Нужен, если с сервера нет связи с `api.telegram.org` (у российских хостингов бывает блокировка). Спецсимволы в пароле — в URL-кодировке (`@` → `%40`) |
| `TELEGRAM_API_BASE` | | `https://api.telegram.org` | Свой адрес Bot API (зеркало или локальный Bot API-сервер); обычно не нужен |
| `VK_GROUP_TOKEN` | для ВК | пусто | Ключ доступа сообщества (сообщения, фото) |
| `VK_GROUP_ID` | для ВК | пусто | ID сообщества (число без минуса); нужен и для ссылок входа `vk.me/club<ID>?ref=login_…` |
| `VK_API_VERSION` | | `5.199` | Версия VK API |
| `COMPOSE_PROFILES` | | пусто | `parser` — запускать вместе с сайтом парсер ВК → Telegram (`vk-parser`). Только в одном месте: сервер или компьютер |
| `VK_PARSER_TELEGRAM_BOT_TOKEN` / `VK_PARSER_TELEGRAM_CHAT_ID` | для парсера | пусто | Бот-публикатор (администратор канала с правом публикации) и числовой ID канала `-100…` |
| `VK_PARSER_VK_TOKEN` | для парсера на сервере | пусто | Сервисный ключ приложения ВК (id.vk.com): стена читается через официальный API `wall.get`. Пусто → браузер Chromium (с серверных IP ВК его не пускает) |
| `VK_PARSER_URL` / `VK_PARSER_LIMIT` / `VK_PARSER_INTERVAL` | | `https://vk.ru/cvetyurala` / `10` / `60` | Какая стена ВК, сколько последних постов просматривать, пауза между проверками (с) |
| `VK_PARSER_MAX_CATCHUP` | | `1000` | Сколько постов парсер готов просмотреть, чтобы догнать пропущенное (после долгой остановки) |
| `VK_PARSER_DATA_DIR` | | `./vk-parser-data` | Папка архива постов и журнала отправок (на Windows можно `D:/…`) |
| `BOT_SERVICE_TOKEN` | для внешних бот-процессов | пусто | Сервисный токен `Authorization: Bot …` |
| `BOT_SIMULATOR_ENABLED` | | `false` | Отладочный эндпоинт движка ботов `/api/v1/simulator/*` (на сайте не показывается; в продакшене — `false`) |
| `CUSTOMER_LOGIN_TEST_MODE` | | `false` | Тестовый вход покупателя без мессенджера (кнопка «Подтвердить вход (тестовый режим)») — только разработка и e2e |
| `CUTOUT_MODEL_PATH` | | `backend/models/isnet-general-use.onnx` (Docker: `/opt/models/…`) | Нейросеть IS-Net для вырезания цветов из фото; без файла — простой алгоритм для однотонного фона. В Docker скачивается при сборке (~180 МБ, `--build-arg CUTOUT_MODEL_URL=` — не скачивать) |
| `YANDEX_MAPS_API_KEY` | рекомендуется | пусто | Ключ «JavaScript API и HTTP Геокодер» ([developer.tech.yandex.ru](https://developer.tech.yandex.ru)): карта зон на сайте/в админке и поиск адресов. Без ключа карта — в демо-режиме, геокодер — Nominatim |
| `YANDEX_GEOCODER_API_KEY` | | = `YANDEX_MAPS_API_KEY` | Отдельный серверный ключ HTTP Геокодера |
| `GEOCODER_PROVIDER` | | `auto` | `auto` (Яндекс при наличии ключа, иначе Nominatim; если Яндекс отклонил ключ или не отвечает — на 10 мин автоматически Nominatim), `yandex`, `nominatim`, `off` (без проверки дома — только зона по точке) |
| `NOMINATIM_URL` | | `https://nominatim.openstreetmap.org` | Адрес Nominatim (можно свой сервер) |
| `GEOCODER_USER_AGENT` | для Nominatim | `CvetyUrala-shop/1.0 (+https://example.com)` | User-Agent с контактом — требование OSM |
| `GEOCODER_TIMEOUT` | | `6` | Таймаут запроса к геокодеру, с |
| `ADDRESS_MAX_DISTANCE_M` | | `400` | Допустимое расхождение точки на карте и найденного адреса, м |
| `YANDEX_GEOCODER_DAILY_LIMIT` | | `900` | Запросов к Яндекс Геокодеру в сутки; дальше — Nominatim (защита бесплатного лимита ключа) |
| `SEED_DEMO` | | `true` | Docker: заполнить демо-данные при пустой БД |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | | `3` / `4` | Docker: процессы и потоки gunicorn |
| `CELERY_CONCURRENCY` | | `2` | Docker: потоки Celery worker |
| `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP` | | `24` / `7` | Docker: период и число резервных копий |
| `BACKUP_MEDIA` / `BACKUP_MEDIA_KEEP` | | `true` / `3` | Docker: архивировать фото (`backups/media_*.tar.gz`) вместе с базой и сколько архивов хранить |
| `API_INTERNAL_URL` (frontend) | | `http://localhost:8000` | Адрес бэкенда для Next.js (в Docker — `http://backend:8000`, задаётся и при сборке) |
