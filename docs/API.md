# API «Цветы Урала» (v1)

* Базовый адрес: `http://localhost:8000/api/v1/` (через сайт — `http://localhost:3000/api/v1/`, Next.js проксирует).
* Интерактивная документация: **`/api/docs/`** (Swagger UI), схема OpenAPI 3: `/api/schema/` и `docs/openapi.yaml`.
* Формат — JSON. **Все суммы — целые копейки** (`19000` = 190 ₽). Даты — `YYYY-MM-DD`, часовой пояс магазина `Asia/Yekaterinburg` (пермское время, UTC+5).
* Ошибки — единый формат и осмысленный HTTP-код:

```json
{"error": {"code": "channel_restricted", "message": "Конструктор букетов недоступен в ВКонтакте. Соберите букет на сайте.", "details": {}}}
```

Типичные коды: `validation_error`, `insufficient_stock` (409), `invalid_transition` (409),
`channel_restricted` (403), `not_found` (404), `not_authenticated` (401), `permission_denied` (403),
`throttled` (429), `invalid_webhook` (400), `login_locked` (429), `spam_detected` (400 — заполнено скрытое
поле-ловушка `website`), `too_many_pending_orders` (400 — у телефона уже 3 неоплаченных/неподтверждённых
заказа), `online_payment_unavailable` (400 — онлайн-оплата выключена), `section_disabled` (409 — владелец
выключил раздел «Цветы поштучно» или «Собрать букет»).

Лимиты запросов (с одного IP): все запросы — 180/мин и 3000/ч; `POST /checkout` — 6/мин и 20/ч;
поиск заказа — 10/мин; геокодер (`/geo/*`) — 30/мин и 600/сутки; вход сотрудника — 10/мин.

## Авторизация

| Клиент | Заголовки | Канал заказа |
|---|---|---|
| Сайт (покупатель) | — (без регистрации); после входа через Telegram/ВК — HttpOnly-cookie `cu_customer` (сайт) или `X-Customer-Token` (старые клиенты) | `web` |
| Бот-процесс | `Authorization: Bot <BOT_SERVICE_TOKEN>` + `X-Bot-Channel: telegram\|vk` | `telegram` / `vk` |
| Сотрудник | HttpOnly-cookie `cu_staff` (ставит `POST /admin/auth/login`, в JSON токена нет) или `Authorization: Bearer <token>` | — |

**Cookie и защита от CSRF.** Секреты входа сайт хранит только в HttpOnly-cookie (`SameSite=Strict`, в боевом
режиме `Secure`): `cu_staff` (путь `/api/v1/admin`, 72 ч), `cu_customer` (путь `/api/v1`, 180 дней), `cu_login`
(путь `/api/v1/account/login`, 10 мин). Запросы, меняющие данные (POST/PATCH/PUT/DELETE), учитывают cookie
только с заголовком `X-Requested-With: fetch` — его ставит `lib/api.ts`; без заголовка запрос считается анонимным.

Вход покупателя на сайте необязателен: заказ можно оформить и без него. Токен сессии покупателя
выдаётся после подтверждения входа в чате с ботом (см. «Вход покупателя через Telegram / ВКонтакте»)
и живёт 180 дней; в БД хранится только его SHA-256.

Канал определяется **сервером** по авторизации. Ограничения ботов (нет конструктора и поштучных
цветов) проверяются в сервисном слое — прямой вызов API их не обходит.

## Публичный API (сайт и боты)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Проверка БД и Redis |
| GET | `/settings/public` | Название, логотип, цвета, контакты, график, правила, разделы `flowers_section_enabled` / `constructor_section_enabled` (для витрины); приём заказов `orders_enabled` + `orders_closed_message`; вход `customer_login {telegram, vk, test_mode, enabled}`; `seo {site_url, pages{home…product: {title, description}}, yandex_verification, google_verification, organization}` |
| GET | `/faq` | «Частые вопросы» для главной: `{blocks: [{title, items: [{q, a}]}]}` (свои блоки владельца или стандартные из настроек) |
| GET | `/catalog/categories?type=bouquet\|flower` | Категории витрины в порядке, заданном в админке (`{id, name, slug, count}`) |
| GET | `/about` | Страница «О нас»: `{title, lead, text, photos: [{id, url, caption}]}` |
| GET | `/catalog/products?type=bouquet\|flower&category=&q=&in_stock=1&featured=1&sort=` | Каталог с актуальным `available` |
| GET | `/catalog/products/{slug}` | Карточка товара (фото, описание, состав, наличие) |
| GET | `/constructor/options` | Цветы, зелень, упаковка, ленты, открытки, работа флориста (**только сайт**). У каждой позиции `constructor_image` — фото бутона/ветки без фона (WebP) или текстура упаковки; `null` — на эскизе рисуется схематично |
| POST | `/constructor/quote` | Расчёт цены индивидуального букета на сервере (**только сайт**) |
| POST | `/carts` | Создать корзину → `{token, items, total…}` |
| GET | `/carts/{token}` | Корзина с актуальными ценами и наличием |
| POST | `/carts/{token}/items` | `{product_id, quantity}` |
| PATCH / DELETE | `/carts/{token}/items/{item_id}` | Изменить количество `{quantity}` / удалить |
| POST | `/carts/{token}/custom-bouquet` | `{composition, quantity}` — индивидуальный букет (**только сайт**) |
| GET | `/delivery/zones` | Зоны доставки: цена, порог бесплатной доставки `free_from`, цвет, границы `polygons` (`[[[lat, lon], …], …]`) |
| GET | `/delivery/geocode?q=Красавинская 8` | Поиск адреса (Яндекс Геокодер или Nominatim) → `{results: [{address, full_address, lat, lon, house, zone, token}]}`; `zone: null` — сюда не доставляем |
| GET | `/delivery/reverse?lat=&lon=` | Адрес по точке на карте → `{result, zone, geocoder}` |
| GET | `/delivery/slots?date=YYYY-MM-DD&fulfillment=delivery\|pickup` | Интервалы и свободные места |
| POST | `/checkout` | Оформление заказа (идемпотентно по `Idempotency-Key`) |
| GET | `/orders/track/{token}` | Статус заказа по секретной ссылке: состав, история, `photos` (фото букета от флориста), `photo_before`, `delivery.{address_pending, surprise, anonymous}` |
| POST | `/orders/lookup` | `{number, phone}` → `{token}` |
| POST | `/orders/track/{token}/pay` | Новая ссылка на оплату |
| GET | `/payments/{token}` | Данные платежа для страницы оплаты |
| POST | `/payments/{token}/simulate` | **Тестовая оплата**: `{action: succeed\|fail\|cancel\|refund_succeed\|refund_fail}` |
| POST | `/payments/webhook/{provider}` | Webhook провайдера (подпись HMAC обязательна, идемпотентно) |
| POST | `/account/login/start` | `{channel: telegram\|vk, order_token?}` → `{code, link, expires_in, channel}` + cookie `cu_login` — начать вход через мессенджер |
| POST | `/account/login/status` | токен — из cookie `cu_login` (или `{token}` в теле) → `{status: pending\|confirmed\|used\|cancelled\|expired}`; при `confirmed` — **один раз** ставит cookie `cu_customer` (повторный опрос → `used`). `GET ?token=` больше не принимается (405) |
| POST | `/account/login/test-confirm` | подтвердить вход без мессенджера (**только** `CUSTOMER_LOGIN_TEST_MODE=true`, иначе 404) |
| POST | `/account/session/adopt` | перенести сессию из заголовка `X-Customer-Token` (старая версия сайта) в cookie `cu_customer` |
| GET / PATCH | `/account/me` | Профиль покупателя: `{name, phone, email, channels, last_delivery, orders}` / изменить `{name, phone, email}` |
| POST | `/account/logout`, `/account/logout-all` | Выйти на этом устройстве / на всех |
| POST, GET | `/simulator/{telegram\|vk}/message`, `/inbox` | Отладочный вход в движок ботов; **выключен** (`BOT_SIMULATOR_ENABLED=false` → 404), на сайте не показывается |

### Пример: индивидуальный букет

```http
POST /api/v1/constructor/quote
{"composition": {"flowers": [{"item_id": 1, "quantity": 5}], "greenery": [],
                 "packaging_id": 20, "ribbon_id": null, "card_id": null,
                 "card_text": "С днём рождения!", "wishes": "без эвкалипта"}}

200 {"materials_total": 110000, "florist_fee": 30000, "unit_price": 140000, "total": 140000, "lines": [...]}
```
`item_id` — идентификаторы складских позиций (`inventory_item_id` из `/constructor/options`).
Нельзя выбрать больше, чем доступно (`insufficient_stock`), меньше / больше стеблей, чем задано в настройках
(по умолчанию 3…30; больше 30 цветков нельзя ни при каких настройках — ошибка `too_many_stems`,
в `details` — `max` и `requested`). `packaging_id: null` — букет **без упаковки** (стебли перевязываются лентой или шпагатом).
`"florist_choice": true` — режим «По фото»: покупатель выбрал только цветы, бумагу и ленту, раскладку
делает флорист (`layout` сервер игнорирует). В заказе (`items[].design`) возвращаются `florist_choice` и
`items[]` с `name`, `image` (фото товара), `constructor_image`, `color_hex` для отрисовки.

### Пример: оформление заказа

```http
POST /api/v1/checkout
Idempotency-Key: 5b0c…
{
  "cart_token": "…",
  "customer": {"name": "Анна", "phone": "+7 912 000-00-00", "email": ""},
  "recipient": {"name": "Мария", "phone": "+79120000001"},
  "fulfillment": "delivery",                 // или "pickup" — тогда delivery не нужен
  "delivery": {"address": "Кондратово, Красавинская улица, 8", "lat": 57.98832, "lon": 56.12075,
               "address_token": "…",       // token из /delivery/geocode — адрес уже проверен
               "apartment": "5", "entrance": "2", "floor": "4",
               "surprise": false,          // сюрприз: не звонить получателю заранее (только с адресом)
               "anonymous": false},        // не говорить, от кого букет
  "photo_before": true,                      // прислать фото букета перед отправкой (только доставка)
  "date": "2025-05-20", "slot_id": 2,
  "payment_method": "online",                // "on_delivery" — только если владелец включил в настройках
  "comment": "", "card_text": ""
}

201 {"number": "10042", "token": "…", "status": "awaiting_payment", "payment_status": "pending",
     "payment_url": "http://localhost:3000/pay/…", "total": 290000, "items": [...], ...}
```
Индивидуальный букет, предзаказ или неизвестный адрес → `status: "awaiting_confirmation"`, `payment_url: null`
(ссылка на оплату появится после подтверждения флористом).

**«Не знаю адрес — узнайте у получателя».** Вместо адреса и координат передаётся зона (район / населённый пункт):
`"delivery": {"ask_recipient": true, "zone_id": 1, "address_hint": "работает в центре Перми", "anonymous": true}`.
Нужен телефон получателя (`recipient_phone_required`), сюрприз с этим режимом несовместим (`surprise_needs_address`),
без зоны — `zone_required`. Цена доставки — по выбранной зоне. Флорист звонит получателю и вписывает адрес
(`PATCH /admin/orders/{id}/delivery`); до этого заказ нельзя подтвердить и передать в работу (`409 address_pending`).

Адрес проверяется на сервере: зона определяется по точке (`lat/lon`) внутри границ зоны, а не по выбору покупателя.
Ошибки `422`: `address_required`, `address_not_found` (нет такого дома), `address_mismatch` (точка дальше
`ADDRESS_MAX_DISTANCE_M` от найденного адреса), `address_out_of_zone` («Сюда мы не доставляем»),
`online_payment_required` (оплата при получении выключена или в заказе индивидуальный букет).
Стоимость доставки: `price` зоны, `0` — если сумма товаров ≥ `free_from` (по умолчанию 1 500 ₽).

Индивидуальный букет в корзине и заказе содержит `design`: состав, `layout` (`[{item_id, x, y, r, f}]` — где стоит
каждый цветок на эскизе, 0…1, угол поворота и `f: true` — цветок отражён) и `items` (`[{id, name, species, color_hex, type, constructor_image}]`) —
по ним сайт и админка рисуют тот же эскиз из фото цветов.

### Пример: запрет для бота

```http
POST /api/v1/carts/{token}/custom-bouquet
Authorization: Bot <BOT_SERVICE_TOKEN>
X-Bot-Channel: vk

403 {"error": {"code": "channel_restricted", "message": "Конструктор букетов недоступен в ВКонтакте. Соберите букет на сайте."}}
```

Если в запросе есть `X-Customer-Token`, заказ привязывается к вошедшему покупателю (уведомления о статусе
уходят в его Telegram/ВК, контакты сохраняются для следующего оформления). Без токена покупатель
ищется по телефону, как раньше.

### Вход покупателя через Telegram / ВКонтакте

```http
POST /api/v1/account/login/start
{"channel": "telegram", "order_token": "…"}    // order_token — необязательно: привязать уже оформленный заказ

201 {"code": "654721", "channel": "telegram", "expires_in": 600,        // + Set-Cookie: cu_login=…; HttpOnly
     "link": "https://t.me/<бот>?start=login_<код-ссылки>"}       // ВК: https://vk.me/club<ID>?ref=login_<код>&ref_source=site
```
1. Сайт открывает `link`; бот присылает «Войти на сайт „Цветы Урала“?» с кнопками **Войти** / **Это не я**
   (если ссылка не открылась — покупатель отправляет боту 6-значный `code`).
2. Сайт опрашивает `POST /account/login/status` раз в 2 с (браузер сам передаёт cookie `cu_login`). После нажатия
   «Войти» — `{status: "confirmed"}` и cookie `cu_customer` (выдаётся один раз; JavaScript страницы её не видит).
   Если подтверждённый вход не забрали за 10 минут — `expired`, сессия не создаётся.
3. Запрос живёт 10 минут; 5 неверных кодов подряд от одного чата — блокировка на 30 минут; лимиты
   12 запусков/мин и 120 опросов/мин с IP.

### Ответ движка ботов (отладочный эндпоинт)

```json
{"messages": [{"text": "Здравствуйте! Это бот магазина «Цветы Урала»…", "photo": null,
  "buttons": [[{"text": "💐 Каталог букетов", "payload": "cat", "url": null, "request_contact": false}],
              [{"text": "🌷 Наличие цветов", "payload": "flowers"}, {"text": "🛒 Корзина", "payload": "cart"}]]}]}
```
Тот же формат (`BotEngine` → `OutMessage`) рендерят адаптеры: Telegram — inline-клавиатура,
ВК — inline-keyboard с payload.

## Админ-API (`/api/v1/admin/…`, Bearer-токен)

Роли: **O** — владелец, **F** — флорист, **C** — курьер.

| Метод | Путь | Роли | Описание |
|---|---|---|---|
| POST | `/admin/auth/login` | — | `{username, password}` → `{user}` + HttpOnly-cookie `cu_staff`, `user.weak_password=true` — стандартный пароль (нужно сменить). 10 попыток/мин с IP; после 5 неверных паролей логин блокируется на 15 мин (`429`, `login_locked`) |
| POST | `/admin/auth/password` | O F C | `{old_password, new_password}` → `{user}` + новый cookie `cu_staff`: смена своего пароля (от 10 символов), старые сеансы завершаются; 5 попыток/мин |
| POST | `/admin/auth/logout`, GET `/admin/auth/me` | O F C | Выход (только на этом устройстве, cookie стирается) / текущий пользователь. У каждого устройства свой токен (таблица `staff_tokens`, до 10 на сотрудника) |
| POST | `/admin/auth/adopt` | O F C | `Authorization: Bearer <старый токен из localStorage>` → тот же вход переносится в cookie `cu_staff` |
| GET | `/admin/dashboard` | O F C | Показатели (выручка — только O; курьеру — его доставки) |
| GET | `/admin/orders?status=&scope=active&source=&q=&date=` | O F C | Заказы (курьер — только назначенные) |
| GET | `/admin/orders/{id}` | O F C | Заказ: состав-снимок, история, платежи, резервы, уведомления |
| POST | `/admin/orders/{id}/transition` | O F C* | `{status, comment}` — только разрешённые переходы |
| POST | `/admin/orders/{id}/confirm` | O F | Подтвердить (индивидуальный букет / заказ при получении) |
| POST | `/admin/orders/{id}/cancel` | O F | `{reason}` — освобождение резервов / возврат |
| POST | `/admin/orders/{id}/assign-courier` | O F | `{courier_id}` |
| POST | `/admin/orders/{id}/refund` | O | Возврат оплаты |
| POST | `/admin/orders/{id}/notes` | O F | Внутренняя заметка |
| PATCH | `/admin/orders/{id}/delivery` | O F | `{address, apartment, entrance, floor}` — адрес, который назвал получатель (или исправленный после звонка); до передачи курьеру. Адрес геокодируется; цена доставки не меняется, а если адрес в другой зоне — в ответе `warning` и запись в истории |
| POST | `/admin/orders/{id}/photos` | O F | multipart `image` — фото собранного букета (до 6). Первое фото уходит покупателю в мессенджер, все видны на странице заказа. Если покупатель просил фото (`photo_before`), без него заказ не передать курьеру — `409 photo_required` |
| DELETE | `/admin/order-photos/{id}` | O F | Удалить фото букета |
| GET | `/admin/couriers`, `/admin/deliveries?date=` | O F (C — свои) | Курьеры, доставки на дату |
| GET / POST | `/admin/categories?kind=bouquet\|flower` | O F | Категории витрины: список / создание `{kind, name}` |
| PATCH / DELETE | `/admin/categories/{id}` | O F | Переименовать `{name}` / удалить (`?move_to=<id>` — перенести товары, иначе они остаются без категории) |
| POST | `/admin/categories/{id}/products` | O F | Добавить товары в категорию `{product_ids}` |
| POST | `/admin/categories/order` | O F | Порядок на витрине `{kind, ids}` |
| GET / PATCH | `/admin/about` | O | Страница «О нас» `{title, lead, text}` |
| GET / PUT / DELETE | `/admin/faq` | O | «Частые вопросы»: `{blocks, custom}`; PUT `{blocks: [{title, items: [{q, a}]}]}` (ошибки — поле `faq.<блок>.<вопрос>.q\|a`, `faq.<блок>.title`); DELETE — вернуть стандартные |
| POST, PATCH / DELETE, POST | `/admin/about/photos`, `/admin/about/photos/{id}`, `/admin/about/photos/order` | O | Фото карусели (multipart `image`, `caption`), подпись / удаление, порядок `{ids}` |
| GET/POST | `/admin/products` | O F | Список / создание. Цена продажи `price` — O и F, закупочная `purchase_price` — только O |
| PATCH | `/admin/products/{id}` | O F | Изменение: `price`, `stock` (абсолютный остаток → пересчёт в журнале склада), `species`, `components` (рецептура букета `[{item_id, quantity}]`), `allow_made_to_order`, видимость |
| DELETE | `/admin/products/{id}` | O F | Удаление. **Владелец** удаляет любой товар навсегда (карточка, фото, строки корзин); в прошлых заказах остаются название, цена и эскиз, складская позиция с историей уходит в архив склада (если входит в рецептуры — остаётся рабочей). Товар в незавершённых заказах только снимается с продажи (`archived: true`, номера заказов в `message`). **Флорист** удаляет товары без истории, остальные снимаются с продажи. Ответ `{ok, archived, message}` |
| POST / DELETE | `/admin/products/{id}/images`, `/admin/product-images/{id}` | O F | Фото товара (multipart) |
| POST / DELETE | `/admin/products/{id}/constructor-image` | O F | Фото для конструктора (multipart `image`, `remove_background=true\|false`): цветы и зелень — однотонный фон убирается автоматически, обрезка по бутону, WebP; упаковка — квадратная текстура 256×256 |
| POST | `/admin/products/{id}/constructor-image/crop` | O F | Кадрирование фото для конструктора `{x, y, w, h}` (доли 0…1 от исходника) |
| GET / POST | `/admin/inventory?archived=0\|1&q=` | O F (создание — O) | Остатки: фактический, резерв, доступно, минимум / новая позиция `{name, category, unit, sku, purchase_price, sale_price, min_stock}` |
| PATCH / DELETE | `/admin/inventory/{id}` | O | Изменить позицию / удалить (если есть история движений — архивируется; позиция с товаром витрины удаляется вместе с товаром, как `DELETE /admin/products/{id}` владельцем) |
| POST | `/admin/inventory/supply` | O F | Поставка `{lines: [{item_id, quantity, unit_cost}], comment}` |
| POST | `/admin/inventory/write-off` | O F | Списание `{item_id, quantity, reason}` |
| POST | `/admin/inventory/adjust` | O F | Корректировка `{item_id, delta, reason}` |
| POST | `/admin/inventory/count` | O F | Инвентаризация `{counts: [{item_id, counted}], comment}` |
| GET | `/admin/inventory/movements?item_id=&type=&date_from=&date_to=&q=&limit=&export=csv` | O F | История операций; `export=csv` — выгрузка для Excel (`;`, UTF-8 BOM) |
| GET | `/admin/inventory/demand` | O F | Планируемый спрос (предзаказы) |
| POST | `/admin/store-sale` | O F | Продажа в магазине `{lines: [{product_id, quantity}], payment: cash\|card}` |
| GET / PATCH | `/admin/recipes`, `/admin/recipes/{id}` | O F | Рецептуры и компоненты |
| POST | `/admin/recipes/{id}/assemble` | O F | Сборка `{count}` — списание компонентов, приход букета |
| GET | `/admin/customers`, `/admin/customers/{id}` | O F | Клиенты, каналы, заказы |
| POST | `/admin/support/{notification_id}/reply` | O F | Ответ клиенту на запрос из бота |
| GET/POST, PATCH, DELETE | `/admin/staff`, `/admin/staff/{id}` | O | Сотрудники и роли; `password` от 10 символов; смена пароля, отключение и удаление завершают сеансы сотрудника; нельзя удалить себя и последнего владельца, доставки удалённого курьера возвращаются «без курьера» |
| GET | `/admin/security/check` | O | Проверка настроек безопасности: `{production, critical, warnings, items: [{code, level, title, detail, fix}]}` |
| GET / PATCH | `/admin/settings` | O | Название, логотип, цвета, контакты, график, правила резерва, `allow_cash_on_delivery` (по умолчанию `false`), точка магазина `shop_lat/shop_lon`, разделы сайта `flowers_section_enabled` / `constructor_section_enabled` (по умолчанию `true`; выключенный раздел скрыт из каталога, а корзина и оформление отвечают `section_disabled`); `orders_enabled` (false — корзина, оформление и боты отвечают `409 orders_closed`, продажа в магазине работает) и `orders_closed_message`; `customer_login_enabled` (вход покупателей); `seo_pages {ключ: {title, description}}` (ошибки — `seo.<ключ>.title`), `yandex_verification` / `google_verification` (код или весь `<meta>`-тег). GET дополнительно отдаёт `orders_closed_default`, `seo_defaults`, `seo_page_list`, `site_url` (multipart для изображений) |
| CRUD | `/admin/delivery-zones[/{id}]`, `/admin/delivery-slots[/{id}]` | O | Зоны (`name, price, free_from, color, polygons, is_active`) и интервалы |
| GET | `/admin/audit-log` | O | Журнал действий сотрудников |

\* курьер — только `ready → handed_to_courier → delivered` по своим заказам.

## Webhook платёжного провайдера

`POST /api/v1/payments/webhook/simulator`, заголовок `X-Simulator-Signature: <HMAC-SHA256(body, PAYMENT_SIMULATOR_SECRET)>`.
События: `payment.succeeded`, `payment.failed`, `payment.canceled`, `refund.succeeded`, `refund.failed`.
Каждое событие сохраняется в `payment_webhook_events` с уникальным id: повторная доставка
возвращает `200` без повторного эффекта (нет повторного списания/подтверждения).

`POST /api/v1/payments/webhook/rollypay` — колбэки RollyPay (`payment.paid`, `payment.canceled`,
`payment.expired`, `payment.refunded`, `payment.chargeback`, `refund_request.completed`). Заголовки
`X-Signature: <hex HMAC-SHA256(X-Timestamp + "." + тело, ROLLYPAY_SIGNING_SECRET)>` и `X-Timestamp`
обязательны (иначе `400`, RollyPay повторит доставку). Затем статус и сумма запрашиваются у API RollyPay
(`GET /api/v1/payments/{payment_id}` с ключом кассы). Промежуточные статусы (`created`, `processing`)
и тестовые платежи при выключенном `ROLLYPAY_TEST_MODE` — `200 {"status": "ignored"}`.
`GET /api/v1/orders/track/{token}` и снятие просроченных резервов дополнительно сверяют неоплаченные
попытки с API кассы (не чаще раза в 20 с на заказ) — на случай, если уведомление не дошло.

`POST /api/v1/payments/webhook/yookassa` — HTTP-уведомления ЮKassa (`payment.succeeded`, `payment.canceled`,
`refund.succeeded`). Телу уведомления сервер не доверяет: статус и сумма запрашиваются у API ЮKassa
по id объекта с секретным ключом магазина.
