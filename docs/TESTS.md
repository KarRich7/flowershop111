# Автоматические проверки

* **Backend (pytest + PostgreSQL):** `cd backend && python -m pytest -rA` → **191 passed** (~2 мин), полный список — `test_results.txt`.
* **E2E (Playwright, реальный браузер против работающего стенда):** `node e2e/smoke.cjs` → **23 PASS / 0 FAIL / 2 SKIP** (шаги входа покупателя — только с `CUSTOMER_LOGIN_TEST_MODE=true`), лог — `e2e_results.txt`.
* **TypeScript:** `cd frontend && npm run typecheck` — без ошибок; `npm run build` — успешно.

## Обязательные проверки из ТЗ (п. 14)

| № | Требование | Тест(ы) |
|---|---|---|
| 1 | Заказ готового букета через сайт уменьшает доступное количество | `test_channels_stock::test_web_order_reduces_available_stock` |
| 2 | Telegram и ВК отображают обновлённый остаток | `test_channels_stock::test_bots_see_stock_after_web_order` |
| 3 | Продажа в физическом магазине обновляет наличие во всех каналах | `test_channels_stock::test_store_sale_updates_all_channels`, `…test_store_sale_cannot_take_reserved_stock` |
| 4 | Последний букет нельзя продать одновременно двум клиентам | `test_concurrency::test_last_bouquet_sold_only_once[сайт+сайт / сайт+Telegram / Telegram+ВК]`, `…test_parallel_store_sale_and_web_order` — настоящие параллельные потоки и транзакции PostgreSQL |
| 5 | Истёкший неоплаченный резерв освобождает товар | `test_reservations::test_expired_unpaid_online_reservation_is_released` |
| 6 | Подтверждённая оплата при получении не отменяется таймером онлайн-платежа | `test_reservations::test_confirmed_cod_order_not_cancelled_by_timer` (+ `test_unconfirmed_cod_order_expires_after_hold`, `test_paid_order_is_never_expired`) |
| 7 | Через ботов нельзя заказать отдельные цветы или индивидуальный букет | `test_channels_stock::test_bots_cannot_order_flowers_or_custom_bouquets_service[telegram/vk]`, `…_api` (прямой вызов API с сервисным токеном) |
| 8 | Конструктор на сайте корректно считает стоимость | `test_constructor_assembly::test_constructor_price_is_materials_plus_florist_fee`, `…_follows_current_prices`, `…_validates_composition` |
| 9 | Сборка готового букета не приводит к двойному списанию | `test_constructor_assembly::test_assembled_bouquet_sold_without_second_write_off`, `…test_made_to_order_bouquet_consumes_components_once`, `…test_mixed_stock_and_made_to_order` |
| 10 | Отмена заказа корректно обрабатывает остатки | `test_reservations::test_cancel_before_assembly_releases_reservation`, `…test_cancel_after_ready_returns_finished_bouquet`, `…made_to_order_bouquet_goes_to_stock`, `…custom_bouquet_warns` |
| 11 | Повторное уведомление об оплате не приводит к повторному списанию | `test_payments_checkout::test_duplicate_payment_webhook_has_no_double_effect` (+ `test_webhook_with_bad_signature_rejected`, `test_payment_after_expiry_is_refunded`) |
| 12 | Заказ с самовывозом не требует адреса доставки | `test_payments_checkout::test_pickup_order_without_address` (+ `test_delivery_requires_address`) |
| 13 | Курьер не видит чужие заказы | `test_permissions::test_courier_sees_only_assigned_orders`, `…test_courier_order_detail_has_no_financials` |

## Безопасность (`tests/test_security.py`, 21 тест)

| Что проверяется | Тест |
|---|---|
| Блокировка входа после неверных паролей; подмена `X-Forwarded-For` не ломает вход | `test_login_locks_after_repeated_failures`, `test_spoofed_forwarded_for_does_not_break_login` |
| Стандартный пароль помечается как небезопасный; смена пароля завершает старые сеансы; вход с телефона и компьютера одновременно, выход — только на своём устройстве | `test_demo_password_is_reported_as_weak`, `test_change_password_rotates_token`, `test_staff_can_be_signed_in_on_phone_and_computer` |
| Сотрудники: пароль от 10 символов, удаление (кроме себя), проверка безопасности — только владелец | `test_new_staff_password_must_be_strong`, `test_owner_deletes_staff_but_not_self`, `test_security_check_only_for_owner` |
| Загрузка фото: пересохранение без EXIF, отказ для подделок и «фото-бомб» | `test_uploaded_photo_is_reencoded_without_metadata`, `test_upload_rejects_fake_and_giant_images`, `test_settings_logo_upload_uses_clean_file` |
| Спам-заказы: honeypot, лимит неоплаченных на телефон, лимит оформлений с IP; лимит поиска заказа | `test_checkout_honeypot_rejects_bots`, `test_pending_orders_per_phone_are_limited`, `test_checkout_is_rate_limited_per_ip`, `test_order_lookup_is_rate_limited_per_ip`, `test_internal_addresses_are_recognised` |
| Без онлайн-оплаты — заказы с оплатой при получении; ЮKassa: платёж, проверка уведомления через API, отказ для мусорных уведомлений | `test_without_online_payments_orders_are_cash_on_delivery`, `test_yookassa_payment_flow_with_verified_webhook`, `test_yookassa_webhook_endpoint_rejects_garbage` |
| RollyPay: платёж, подпись колбэка (без подписи / чужой секрет / устаревший / подмена тела — 400), статус из API, тестовый платёж в боевом режиме не учитывается, сверка суммы, поздняя оплата после истечения, ручной возврат и его подтверждение колбэком, тестовый режим, сверка статуса без колбэка, отчёт о незаданных ключах, понятная ошибка при недоступной кассе | `tests/test_rollypay.py` (10 тестов) |
| Суточный лимит Яндекс Геокодера; объяснение, почему «Сегодня» недоступно | `test_yandex_daily_limit_switches_to_nominatim`, `test_today_note_explains_cutoff` |

## Дополнительно

Полный сценарий бота Telegram и ВК (каталог → корзина → контакты → доставка → оплата → история),
отладочный API движка ботов (выключен по умолчанию), запрос флористу; идемпотентность оформления заказа; неизменяемость снимка заказа;
стоимость и бесплатная доставка; скрытие внутренних данных в публичном статусе; права
владельца/флориста (цены, возвраты); недопустимые переходы статусов; предзаказ без резерва;
поштучная продажа цветов на сайте; упаковка не продаётся отдельно; health-check.

## Доработки второй итерации

| Требование | Тест(ы) |
|---|---|
| Только онлайн-оплата (при получении — только если включил владелец; индивидуальный букет — всегда онлайн) | `test_delivery_zones::test_only_online_payment_by_default`, `…test_custom_bouquet_is_online_only` |
| Бесплатная доставка от 1 500 ₽ | `test_delivery_zones::test_free_delivery_from_1500`, `test_payments_checkout::test_delivery_cost_and_free_threshold` |
| Зона по точке на карте, вне зон — отказ, проверка адреса | `test_delivery_zones::test_point_in_polygon_and_zone_lookup`, `…test_web_delivery_requires_point_on_map`, `…test_delivery_outside_zones_is_rejected`, `…test_signed_address_is_verified_and_zone_set_by_server`, `…test_forged_token_triggers_geocoder_check`, `…test_geocoder_unavailable_keeps_zone_check_and_logs_note`, `…test_geocode_and_reverse_api`, `…test_rejected_yandex_key_falls_back_to_nominatim` |
| Карта и границы зон в API, редактирование границ владельцем | `test_delivery_zones::test_public_zones_and_settings_expose_map_data`, `…test_owner_edits_zone_polygon` |
| Бот: «Данные указаны правильно?» с кнопками «Да» / «Изменить» | `test_bots::test_bot_delivery_confirmation_and_edit` (+ `test_full_bot_checkout[telegram/vk]`) |
| Флорист меняет цену продажи, остаток и рецептуру, но не закупочную цену | `test_permissions::test_florist_sets_sale_price_but_not_purchase_price`, `…test_florist_creates_bouquet_with_stock_and_recipe` |
| Расстановка цветов на эскизе сохраняется в заказе | `test_constructor_assembly::test_constructor_layout_is_saved_with_order` |
| Не больше 30 цветков в индивидуальном букете (даже если в БД осталось 101), лимит в настройках — не выше 30 | `test_constructor_assembly::test_constructor_allows_at_most_30_flowers`, `test_admin_catalog::test_shop_settings_are_owner_only_and_validated` |
| «Букет по фото»: оформление на усмотрение флориста, без эскиза, цена с сервера, сохраняется в корзине и заказе | `test_constructor_assembly::test_florist_choice_bouquet_has_no_sketch` |
| Фото для конструктора: удаление однотонного фона, текстура упаковки, права, попадание в конструктор и эскиз заказа, привязка демо-фото к существующей БД | `test_constructor_photos` (5 тестов) |

## Доработки третьей итерации

| Требование | Тест(ы) |
|---|---|
| Категории букетов и цветов: создание, переименование, порядок, удаление с переносом, добавление товаров; курьеру недоступно | `test_admin_catalog::test_florist_manages_bouquet_categories`, `…test_category_order_drives_storefront`, `…test_flower_categories_include_greenery_and_courier_has_no_access`, `…test_product_category_must_exist` |
| Проверка данных (товары, настройки, интервалы, склад, оформление заказа) | `test_admin_catalog::test_product_patch_rejects_invalid_values`, `…test_shop_settings_are_owner_only_and_validated`, `…test_slots_are_validated`, `…test_stock_operations_validate_input_and_export_csv`, `…test_checkout_rejects_invalid_contacts` |
| Флорист добавляет упаковку и ленты для конструктора; удаление товара (неиспользуемый — удаляется, с историей — в архив) | `test_admin_catalog::test_florist_creates_packaging_and_ribbon_for_constructor`, `…test_product_delete_removes_unused_and_archives_used` |
| Вырезание цветка по фото: исходник сохраняется, рамку можно изменить | `test_admin_catalog::test_constructor_photo_keeps_source_and_crop_can_be_changed` (+ `test_constructor_photos`) |
| Букет без упаковки, отражённый цветок сохраняется в эскизе | `test_admin_catalog::test_bouquet_without_packaging_and_flip_in_layout` |
| «О нас» и данные магазина меняет только владелец | `test_admin_catalog::test_about_page_is_owner_only_and_public`, `…test_shop_settings_are_owner_only_and_validated` |
| Зоны доставки добавляются и удаляются | `test_admin_catalog::test_owner_adds_and_deletes_zones` |
| Склад полностью из админки (создание, изменение, удаление/архив, CSV) | `test_admin_catalog::test_owner_manages_inventory_items`, `…test_stock_operations_validate_input_and_export_csv` |
| Вход покупателя через Telegram/ВК: ссылка, подтверждение в боте, только тот же пользователь, отмена и истечение, ручной код и лимит попыток, ВК по `ref` | `test_customer_login::test_telegram_login_flow`, `…test_confirm_requires_same_messenger_user`, `…test_cancel_and_expired`, `…test_manual_code_and_attempt_limit`, `…test_vk_login_by_ref`, `…test_login_unavailable_without_bots` |
| Вошедший покупатель: заказ привязан к нему, статусы уходят в мессенджер; гостевой заказ подключается позже; профиль, выход; тестовый режим | `test_customer_login::test_checkout_signed_in_links_order_and_notifies_messenger`, `…test_anonymous_order_connects_notifications_later`, `…test_profile_update_and_logout`, `…test_test_mode_confirm` |

## Доработки пятой итерации

| Требование | Тест(ы) |
|---|---|
| Владелец удаляет любой товар навсегда, история заказов и эскизы сохраняются | `test_admin_catalog::test_owner_deletes_any_product_forever`, `…test_custom_bouquet_sketch_survives_flower_deletion`, `test_payments_checkout::test_order_snapshot_is_immutable` |
| После «Передан курьеру» — только «Доставлен» | `test_permissions::test_courier_sees_only_assigned_orders` (проверка `allowed_transitions == ["delivered"]`, переход в «Готов» → 409) |
| Миграция зон Екатеринбурга → Кондратово/Пермь: архив зон с доставками, демо-адреса, свои зоны владельца не трогаются | `test_delivery_zones::test_migration_replaces_old_ekaterinburg_demo_zones`, `…test_migration_keeps_owner_zones` |
| Проверка ключа Яндекса в админке: только владелец, причина 403, ключ не раскрывается | `test_delivery_zones::test_maps_check_for_owner_only_and_hides_key` |
| «Не знаю адрес»: зона и телефон получателя, без адреса не подтвердить, флорист вписывает адрес | `test_delivery_options::test_unknown_address_is_asked_from_recipient`, `…test_unknown_address_needs_recipient_phone_and_no_surprise` |
| Сюрприз и анонимность видны курьеру | `test_delivery_options::test_surprise_and_anonymous_are_visible_to_courier` |
| Фото перед отправкой: без фото не передать курьеру, уведомление покупателю, фото на странице заказа, курьер не загружает | `test_delivery_options::test_photo_before_dispatch`, `…test_photo_upload_rejects_non_image` |
| Адрес нельзя менять после передачи курьеру | `test_delivery_options::test_address_can_not_be_changed_after_handover` |
| Кнопки действий — только выполнимые переходы (нет «Ожидает самовывоза» у доставки, «Подтверждён» у неоплаченного онлайн-заказа; курьеру — только его шаги) | `test_permissions::test_action_buttons_match_fulfillment_payment_and_role` |

## Разделы сайта (`tests/test_site_sections.py`, 4 теста)

| Требование | Тест(ы) |
|---|---|
| По умолчанию оба раздела включены, флаги есть в `/settings/public` | `test_sections_are_on_by_default` |
| «Цветы поштучно» выключены: цветов и зелени нет в каталоге и категориях, карточка — 404, в корзину не добавить (`section_disabled`), старая корзина помечена и не оформляется; конструктор и продажа в магазине работают | `test_flowers_section_off_hides_and_blocks_single_stems` |
| «Собрать букет» выключен: варианты, расчёт и добавление своего букета — 409, старый свой букет в корзине не оформляется; цветы поштучно продаются | `test_constructor_section_off_blocks_custom_bouquets` |
| Переключает только владелец | `test_only_owner_switches_sections` |

## E2E-сценарии (браузер, Playwright + Chromium)

1. Главная открывается, есть букеты
2. Каталог букетов и фильтр
3. Карточка товара → в корзину
4. Корзина показывает товар
5. Оформление: поиск адреса → зона на карте → онлайн-оплата (оплаты при получении нет) → страница оплаты
6. Наличие уменьшилось сразу после оформления (резерв)
7. Тестовая оплата: успешная оплата → заказ подтверждён
8. Конструктор: «+», перетаскивание мышью на эскиз, фото настоящих цветов, выбор цветка → «Отразить»,
   «Без упаковки» (букет можно купить), цена с сервера, букет в корзину
9. Конструктор: объёмная лента (PNG с сервера отдаётся), «В вазе» — смена формы вазы, «Эскиз»
10. Конструктор «По фото»: лимит 30 цветков (кнопки «Добавить» неактивны, сервер отвечает `too_many_stems`), бумага и лента, нет эскиза, букет в корзине с пометкой «оформление на усмотрение флориста»
11. Вход через Telegram при оформлении (тестовый режим): ожидание подтверждения, имя подставлено, покупатель запомнен
12. Заказ индивидуального букета: самовывоз, ожидает подтверждения, «Уведомления включены»
12а. Подарок: «Другому человеку» → «Не знаю адрес — узнайте у получателя» (карта не нужна, сюрприз недоступен), зона, «Не говорить, от кого», фото перед отправкой включено → заказ ждёт подтверждения; заказ появляется в «Мой заказ» на этом устройстве
13. Личный кабинет: профиль, каналы и история заказов
14. Страница «О нас»: текст и карусель фото
15. На сайте нет симулятора ботов и ссылки «Для сотрудников»
16. Админка: вход владельца и сводка
17. Админка: подтверждение индивидуального букета
17а. Админка: без адреса «Подтвердить заказ» неактивна → флорист вписывает адрес от получателя → подтверждение → загрузка фото букета → фото видно на странице заказа покупателя
18. Админка: заказы, склад, продажа, рецептуры, товары, доставки, настройки (в т.ч. статус Telegram/ВК)
19. Продажа в магазине уменьшает остаток на всех каналах
20. Курьер видит только свои доставки
21. Мобильная версия: главная, каталог, товар, конструктор (оба режима), корзина, оформление, «О нас», кабинет
22. Мобильная админка

Шаги 11–13 выполняются, когда backend запущен с `CUSTOMER_LOGIN_TEST_MODE=true` (иначе — SKIP).
Для теста берётся любой букет в наличии, поэтому сценарий можно повторять на одной и той же БД.

Скриншоты каждого шага (десктоп 1440 px и мобильный 390 px) сохраняются в каталог `SHOTS`;
мобильные проверки дополнительно убеждаются, что нет горизонтальной прокрутки.
Полный сценарий бота (каталог → корзина → контакты → доставка → оплата → история) покрыт
pytest-тестом `test_bots::test_full_bot_checkout[telegram/vk]`.
