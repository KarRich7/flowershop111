# Запуск сайта в интернете (свой домен + HTTPS)

Для проверки на своём компьютере достаточно `docker compose up -d --build` (см. README).
Эта инструкция — для настоящего запуска, когда сайт открывают покупатели.

## 1. Что понадобится

* **Сервер (VPS)** в России: Timeweb Cloud, Selectel, REG.RU, Beget и т. п. — Ubuntu 22.04/24.04,
  минимум 2 ядра, 4 ГБ памяти, 40 ГБ диска (≈ 600–1200 ₽/мес).
* **Домен** (например, `cvety-urala.ru`) — у регистратора (REG.RU, RU-CENTER, Timeweb).
* Почта для уведомлений Let's Encrypt (бесплатный HTTPS-сертификат).

## 2. Домен → сервер

В панели регистратора домена создайте DNS-записи (IP — из панели VPS):

| Тип | Имя | Значение |
|---|---|---|
| A | `@` | IP сервера |
| A | `www` | IP сервера |

Записи начинают работать через 15 мин – 24 ч. Проверка: `ping cvety-urala.ru` показывает IP сервера.

## 3. Подготовка сервера

```bash
ssh root@IP_сервера
curl -fsSL https://get.docker.com | sh          # Docker + Docker Compose
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable   # открыть только SSH и сайт
```

Скопируйте проект на сервер (с компьютера): `scp -r flower-shop root@IP_сервера:/opt/` —
или через Git. Дальше все команды — в папке `/opt/flower-shop`.

## 4. Настройки `.env`

```bash
cp .env.example .env
docker compose run --rm --no-deps backend gen-secrets      # напечатает новые секреты
nano .env                                        # вставить секреты и заполнить строки ниже
```

Обязательно:

```ini
PRODUCTION=true
DJANGO_DEBUG=false
SITE_DOMAIN=cvety-urala.ru
ACME_EMAIL=you@mail.ru
DJANGO_SECRET_KEY=…            # из gen-secrets
PAYMENT_SIMULATOR_SECRET=…     # из gen-secrets
BOT_SERVICE_TOKEN=…            # из gen-secrets
POSTGRES_PASSWORD=…            # из gen-secrets (до первого запуска; потом — см. SECURITY.md, п. 4)
OWNER_PASSWORD=…               # пароль владельца, если база новая и SEED_DEMO=false
SEED_DEMO=false                # не заполнять демо-товарами (или true, чтобы начать с примеров)
GEOCODER_USER_AGENT=CvetyUrala-shop/1.0 (+https://cvety-urala.ru)
```

Адреса `FRONTEND_URL`, `ALLOWED_HOSTS`, `CSRF`/`CORS` для домена подставляются автоматически
из `SITE_DOMAIN` (в `docker-compose.prod.yml`).

## 5. Запуск

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy backend   # Ctrl+C — выйти
```

Через 1–2 минуты сайт откроется по `https://cvety-urala.ru` (сертификат выпускается сам).
Чтобы не писать длинную команду, можно один раз выполнить
`echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml' >> .env` — дальше хватит
`docker compose up -d --build`, `docker compose logs -f` и т. д.

После запуска:

1. `https://ваш-домен/admin` → войдите владельцем → смените пароль, если сайт попросит.
2. **Настройки → «Безопасность»** — не должно быть красных пунктов.
3. Если запускали с демо-данными: `docker compose exec backend python manage.py clear_demo --yes`
   (`--catalog` — удалить и демо-товары), затем заведите свои товары и фото.
4. **Настройки → Магазин / Доставка** — название, телефон, адрес, график, зоны, разделы сайта.
5. **Сотрудники → «+ Сотрудник»** — флористы и курьеры со своими паролями.

## 6. Оплата (RollyPay)

Онлайн-оплата идёт через **RollyPay** (СБП, карта): покупатель переходит на платёжную форму RollyPay,
после оплаты возвращается на страницу заказа, а заказ подтверждается сам по уведомлению кассы.

1. Получите у RollyPay (через партнёра/поддержку) кассу: **api_key** (`rpk_live_…`) и **signing_secret**.
2. В настройках кассы укажите **callback_url**: `https://ваш-домен/api/v1/payments/webhook/rollypay`
   (нужен настоящий домен с HTTPS — на `localhost` уведомления не дойдут).
3. `.env`:
   ```
   PAYMENT_PROVIDER=rollypay
   ROLLYPAY_API_KEY=rpk_live_…
   ROLLYPAY_SIGNING_SECRET=…
   ROLLYPAY_TEST_MODE=true
   ```
   `ROLLYPAY_PAYMENT_METHOD=sbp` (или `card`) — сразу открывать этот способ; пусто — выбор на форме.
4. `docker compose up -d --force-recreate backend celery-worker telegram-bot vk-bot`.
5. **Проверка без денег** (`ROLLYPAY_TEST_MODE=true`): оформите заказ → на форме RollyPay баннер
   «Тестовый режим» → «Симулировать успешную оплату» → заказ в админке стал «Подтверждён», в истории
   «Оплата получена (тестовый режим)». Повторите с неуспешной оплатой.
6. Боевой режим: `ROLLYPAY_TEST_MODE=false` и снова команда из п. 4.

Как это защищено: уведомление без верной подписи `X-Signature` (HMAC-SHA256 от `X-Timestamp.тело`
с `signing_secret`) отклоняется; статус и сумма платежа дополнительно запрашиваются у API RollyPay
с ключом кассы, сумма сверяется с заказом; тестовый платёж не подтвердит заказ в боевом режиме;
повторные уведомления не меняют заказ дважды. Если покупатель вернулся с формы раньше уведомления
(или callback_url не настроен), сайт сам сверяет статус платежа при открытии страницы заказа и перед
снятием резерва.

Важно знать про RollyPay:
* **Возвраты** — в API RollyPay их нет. При отмене оплаченного заказа платёж станет «Возврат»,
  в истории заказа появится подсказка: оформите возврат в личном кабинете RollyPay/через поддержку.
  Когда RollyPay вернёт деньги, придёт уведомление и платёж станет «Возвращён» автоматически.
  Тестовые платежи «возвращаются» сразу — денег по ним не было.
* **Деньги зачисляются на баланс в USDT** (RollyPay сам конвертирует рубли), выплата — на кошелёк.
  Чеков 54-ФЗ RollyPay не формирует. Как учитывать такие поступления и пробивать чеки покупателям
  (отдельная онлайн-касса), уточните у бухгалтера **до** запуска.

Пока касса не подключена, в боевом режиме онлайн-оплата скрыта, покупатель платит при
получении (`ONLINE_PAYMENTS=off` — выключить онлайн-оплату принудительно).

### ЮKassa (запасной вариант, сейчас не используется)

Код подключения сохранён. Чтобы переключиться: договор на yookassa.ru → `.env`:
`PAYMENT_PROVIDER=yookassa`, `YOOKASSA_SHOP_ID=…`, `YOOKASSA_SECRET_KEY=…` (чеки 54-ФЗ через ЮKassa —
`YOOKASSA_SEND_RECEIPT=true`) → кабинет ЮKassa → Интеграция → HTTP-уведомления:
`https://ваш-домен/api/v1/payments/webhook/yookassa` (события `payment.succeeded`, `payment.canceled`,
`refund.succeeded`) → команда из п. 4.

## 7. Яндекс Карты, боты

* Ключ Яндекса (developer.tech.yandex.ru): в ограничениях ключа (HTTP Referer) добавьте
  `https://ваш-домен` и `https://www.ваш-домен`.
* Telegram/ВК — токены в `.env`, как в README; на боевом домене кнопки-ссылки в ботах работают.

## 8. Парсер ВК → Telegram-канал

Папка `vk-parser` — отдельная программа: раз в минуту проверяет стену https://vk.ru/cvetyurala
(на сервере — через официальный API ВК, на домашнем компьютере можно и через браузер Chromium),
сохраняет новые посты (текст, фото, видео) и публикует их в ваш Telegram-канал с подписью из
`vk-parser/post_footer.txt`. С сайтом и базой не связана.

1. Бот-публикатор: @BotFather → `/newbot` → токен. Добавьте бота **администратором канала**
   с правом «Публикация сообщений». Можно взять бота магазина, но лучше отдельного.
2. ID канала (вида `-1001234567890`): перешлите любой пост канала боту @userinfobot
   (или @getmyid_bot) — он покажет ID канала.
3. **Ключ ВК (обязательно на сервере).** С адресов дата-центров ВК не пускает программный браузер
   (страница «Проверяем, что вы не робот»), поэтому на сервере парсер читает стену через
   **официальный API ВК**. Нужен сервисный ключ своего приложения ВК (бесплатно, 5 минут):
   https://id.vk.com/about/business/go → «Перейти в кабинет» → «Создать приложение» → платформа
   **Web**, название любое (например, «Парсер Цветы Урала»), базовый домен `cvetyurala.ru`,
   доверенный Redirect URL `https://cvetyurala.ru` → в настройках приложения скопируйте
   **«Сервисный ключ доступа»** (не «Защищённый ключ»). Сообщество должно быть открытым.
4. В `.env` на сервере:

   ```ini
   COMPOSE_PROFILES=parser
   VK_PARSER_TELEGRAM_BOT_TOKEN=123456:ABC…
   VK_PARSER_TELEGRAM_CHAT_ID=-1001234567890
   VK_PARSER_VK_TOKEN=…сервисный ключ…
   ```

5. `docker compose up -d --build` и проверка: `docker compose logs -f vk-parser`
   (в начале «Источник: официальный API ВК», затем каждую минуту «Проверка N: новых/начальных …»,
   Ctrl+C — выйти).

Важно:

* **Первый запуск** только запоминает последние 10 постов (в канал их не шлёт) — дальше
  публикуются лишь новые. Старые посты повторно не уйдут и после перезапуска.
* **Включайте парсер в одном месте.** Если он работает и на домашнем компьютере, а потом и
  на сервере, новые посты придут в канал дважды. На компьютере уберите `COMPOSE_PROFILES=parser`
  и выполните `docker compose stop vk-parser`.
* Подпись под постами: `nano vk-parser/post_footer.txt` → `docker compose restart vk-parser`.
* Разовый сбор и повторная отправка поста (меню): `docker compose run --rm vk-parser menu`
  (на Windows — `parser-menu.cmd`).
* Архив постов и журнал отправок — в папке `vk-parser-data` (на компьютере путь задаёт
  `VK_PARSER_DATA_DIR`). Не удаляйте `vk-parser-data/delivery.sqlite3` и `archive/watch.sqlite3`,
  иначе парсер «забудет», что уже публиковал. Архив растёт за счёт фото и видео — раз в
  несколько месяцев можно удалить старые папки `vk-parser-data/runs/*`.
* Без `VK_PARSER_VK_TOKEN` парсер открывает стену в браузере, как на домашнем компьютере. На сервере
  это обычно заканчивается «Проверка не завершена: … TimeoutException» (снимок —
  `vk-parser-data/archive/last-error.png`) — значит, нужен ключ из п. 3.
* Ошибки API понятны из журнала: «ВК отклонил ключ доступа» — ключ скопирован не тот или отозван;
  «ВК не даёт читать эту стену» — стена закрыта. Парсер повторяет попытки сам.
* Видео: файлы скачиваются через yt-dlp, если ВК их отдаёт. Если нет — пост уходит с текстом и
  фото, а видео остаётся ссылкой в архиве (`download_status=link_only`).
* Парсер занимает до 2 ГБ памяти (ограничение в `docker-compose.yml`).

## 9. Защита от DDoS (рекомендуется)

Сайт сам ограничивает частоту запросов и обрывает медленные соединения, но массированную атаку
трафиком выдерживает только внешняя защита. Бесплатно: **Cloudflare** (перенести DNS домена
в Cloudflare, включить оранжевое облако «Proxied», SSL/TLS → Full (strict)) или **DDoS-Guard**.
После этого в `deploy/Caddyfile` раскомментируйте строки `trusted_proxies` и `client_ip_headers`
(список IP Cloudflare: https://www.cloudflare.com/ips/) и перезапустите `caddy`.

## 10. Обслуживание

```bash
docker compose up -d --build                         # обновление после замены файлов проекта
docker compose exec backend python manage.py security_check   # проверка настроек
docker compose exec backend python manage.py changepassword owner   # сброс пароля владельца
docker compose exec db-backup /bin/sh /backup.sh     # резервная копия → ./backups
```

Контейнер `db-backup` раз в сутки кладёт в `./backups` копию базы (`flowers_*.dump`, 7 последних) и
архив фото (`media_*.tar.gz`, 3 последних). Копируйте `./backups` с сервера к себе (или в облако)
хотя бы раз в неделю. Восстановление фото: `docker compose exec -T backend tar xzf - -C /app < backups/media_<дата>.tar.gz`.

После изменения `deploy/Caddyfile` (приходит с обновлением) перезапустите Caddy: `docker compose restart caddy`.

### Сайт не открывается в каком-то браузере или через VPN

Сайт работает по обычному HTTPS (HTTP/1.1 и HTTP/2 по TCP, порт 443). Новый протокол HTTP/3 (QUIC, по UDP)
специально выключен (`protocols h1 h2` в `deploy/Caddyfile`, порт `443/udp` не открыт): через часть VPN,
антивирусов и мобильных сетей он «зависает», и сайт не открывается в Яндекс Браузере или Chrome.
Заголовок `Alt-Svc: clear` заставляет браузеры забыть HTTP/3, если они его запомнили раньше.

Если у покупателя сайт всё равно не открывается — по порядку:
1. Открыть адрес полностью: `https://cvetyurala.ru` (в Яндекс Браузере короткий текст иногда уходит в поиск).
2. Проверить в режиме «Инкогнито» (`Ctrl+Shift+N`). Открылось — очистить кэш и cookie (`Ctrl+Shift+Del`) и выключить расширения.
3. Проверка снаружи: <https://check-host.net/check-http?host=https://cvetyurala.ru> — сайт должен отвечать «OK 200» из России и Европы.
4. Проверка на сервере: `docker compose ps` (все контейнеры `Up`), `docker compose logs --tail=50 caddy`.

