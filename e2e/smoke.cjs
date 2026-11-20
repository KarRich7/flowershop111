// E2E smoke-тест витрины, конструктора, оплаты, входа через мессенджер и админки (Playwright + Chromium).
// Запуск: BASE_URL=http://localhost:3000 SHOTS=./shots node e2e/smoke.cjs
// Шаги входа покупателя проверяются, если backend запущен с CUSTOMER_LOGIN_TEST_MODE=true (иначе — SKIP).
const path = require("path");
const fs = require("fs");
let pw;
try { pw = require("playwright"); } catch { pw = require(process.env.PLAYWRIGHT_MODULE || "/vercel/sandbox/node_modules/playwright") /* npm i -D playwright && npx playwright install chromium */; }
const BASE = process.env.BASE_URL || "http://localhost:3000";
// Владелец (после смены пароля передайте свой: OWNER_PASS=... node e2e/smoke.cjs).
// Флориста и курьера тест создаёт сам на время прогона и удаляет в конце.
const OWNER_USER = process.env.OWNER_USER || "owner";
const OWNER_PASS = process.env.OWNER_PASS || "owner12345";
const STAFF_PASS = process.env.E2E_STAFF_PASS || "E2e-Staff-Pass-2025";
const SHOTS = process.env.SHOTS || path.join(__dirname, "..", "shots");
fs.mkdirSync(SHOTS, { recursive: true });

const results = [];
const errors = [];
function ok(name) { results.push(["PASS", name]); console.log("PASS", name); }
/** После «Оформить заказ»: ждём страницу заказа, а если форма показала ошибку — сообщаем её текст */
async function waitOrder(page) {
  try {
    await page.waitForURL(/\/order\//, { timeout: 15000 });
  } catch (e) {
    const errs = await page.locator(".notice.red, .field-err").allInnerTexts().catch(() => []);
    throw new Error("заказ не оформлен" + (errs.length ? ": " + errs.join(" | ") : ""));
  }
}
function skip(name, why) { results.push(["SKIP", name, why]); console.log("SKIP", name, "—", why); }
function fail(name, e) { results.push(["FAIL", name, String(e && e.message || e)]); console.log("FAIL", name, e && e.message || e); }

async function step(name, fn) {
  try { await fn(); ok(name); } catch (e) { fail(name, e); }
}

(async () => {
  const exe = process.env.CHROMIUM || (fs.existsSync("/usr/local/bin/chromium") ? "/usr/local/bin/chromium" : undefined);
  const browser = await pw.chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ru-RU", timezoneId: "Asia/Yekaterinburg" });
  const page = await desktop.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror ${page.url()}: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console ${page.url()}: ${m.text()}`); });
  const shot = async (p, name, full = true) => {
    await p.waitForTimeout(400);
    if (full) await p.addStyleTag({ content: ".header{position:relative!important}.adm-side{position:relative!important;height:auto!important;min-height:100%}" });
    await p.screenshot({ path: path.join(SHOTS, name), fullPage: full });
  };

  await step("Главная открывается, есть букеты", async () => {
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Популярные букеты" }).waitFor();
    if ((await page.locator(".pcard").count()) < 4) throw new Error("мало карточек");
    await shot(page, "d01_home.png");
  });

  await step("Каталог букетов и фильтр", async () => {
    await page.goto(BASE + "/bouquets", { waitUntil: "networkidle" });
    const all = await page.locator(".pcard").count();
    if (all !== 20) throw new Error(`ожидалось 20 букетов, есть ${all}`);
    await page.getByRole("button", { name: /Пионы/ }).click();
    const n = await page.locator(".pcard").count();
    if (n < 1 || n >= all) throw new Error("фильтр не работает");
    await page.getByRole("button", { name: /Все букеты/ }).click();
    await shot(page, "d02_bouquets.png");
  });

  let stockBefore = 0;
  // букет с остатком (демо-остатки расходуются прошлыми прогонами — берём любой в наличии)
  const bouquets = await (await page.request.get(BASE + "/api/v1/catalog/products?type=bouquet")).json();
  const pick = bouquets.find((p) => p.available >= 2) || bouquets.find((p) => p.available >= 1) || bouquets[0];
  const shopPublic = await (await page.request.get(BASE + "/api/v1/settings/public")).json();
  const loginTest = !!(shopPublic.customer_login && shopPublic.customer_login.test_mode);
  await step("Карточка товара → в корзину", async () => {
    await page.goto(BASE + "/product/" + pick.slug, { waitUntil: "networkidle" });
    const hint = await page.locator(".hint", { hasText: "Доступно к заказу" }).innerText();
    stockBefore = Number((hint.match(/\d+/) || [0])[0]);
    await shot(page, "d03_product.png", false);
    await page.locator(".pd").getByRole("button", { name: /В корзину/ }).click();
    await page.locator(".toast", { hasText: "в корзине" }).waitFor();
  });

  await step("Корзина показывает товар", async () => {
    await page.goto(BASE + "/cart", { waitUntil: "networkidle" });
    await page.locator(".cart-line", { hasText: pick.name }).waitFor();
    await shot(page, "d04_cart.png", false);
  });

  let payUrl = "";
  await step("Оформление: доставка + онлайн-оплата → страница оплаты", async () => {
    await page.goto(BASE + "/checkout", { waitUntil: "networkidle" });
    if (shopPublic.customer_login && (shopPublic.customer_login.telegram || shopPublic.customer_login.vk)) {
      // вход необязателен — свёрнут в одну строку над шагами оформления
      await page.locator(".signin-card summary", { hasText: "Войдите через Telegram или ВКонтакте" }).waitFor();
    }
    await page.getByLabel("Имя *").fill("Тест Покупатель");
    await page.getByLabel("Телефон *").fill("+7 900 111-22-33");
    // адрес: поиск по геокодеру → выбор из списка → проверка зоны доставки
    const addr = page.locator('input[autocomplete="street-address"]');
    await addr.fill("Красавинская 8");
    await page.getByRole("button", { name: "Найти" }).click();
    await page.locator(".geo-results button").first().click({ timeout: 15000 });
    await page.locator(".zone-status", { hasText: "Доставляем" }).waitFor({ timeout: 10000 });
    // наличными — нельзя: по умолчанию доступна только онлайн-оплата
    if (await page.getByRole("button", { name: /При получении/ }).count()) throw new Error("видна оплата при получении");
    // ближайший доступный интервал (если на сегодня нет — берём завтра)
    await page.waitForSelector(".slot");
    if (!(await page.locator(".slot:not([disabled])").count())) {
      const d = new Date(Date.now() + 86400000).toLocaleDateString("en-CA", { timeZone: "Asia/Yekaterinburg" });
      await page.locator('input[type="date"]').fill(d);
      await page.waitForTimeout(800);
    }
    await page.locator(".slot:not([disabled])").first().click();
    // шаги отмечены галочками, список «Осталось заполнить» пуст, есть «Что будет дальше»
    await page.getByTestId("co-ready").waitFor();
    if ((await page.locator(".co-step").count()) !== 6) throw new Error("ожидалось 6 шагов оформления при доставке");
    if (await page.locator(".co-num:not(.done)").count() > 1) throw new Error("заполненные шаги не отмечены галочкой");
    await page.locator(".co-next li").first().waitFor();
    await shot(page, "d05_checkout.png");
    await page.getByRole("button", { name: /Перейти к оплате/ }).click();
    await page.waitForURL(/\/pay\//, { timeout: 15000 });
    payUrl = page.url();
    await page.getByText("Тестовая оплата").waitFor();
    await shot(page, "d06_pay.png", false);
  });

  await step("Наличие уменьшилось сразу после оформления (резерв)", async () => {
    const r = await page.request.get(BASE + "/api/v1/catalog/products/" + pick.slug);
    const d = await r.json();
    if (!(d.available === stockBefore - 1)) throw new Error(`было ${stockBefore}, стало ${d.available}`);
  });

  await step("Тестовая оплата: успешная оплата → заказ подтверждён", async () => {
    await page.getByRole("button", { name: /^Оплатить/ }).click();
    await page.getByText("Оплата прошла успешно").waitFor({ timeout: 10000 });
    await shot(page, "d07_paid.png", false);
    await page.getByRole("link", { name: "Перейти к заказу" }).click();
    await page.waitForURL(/\/order\//);
    await page.locator(".badge", { hasText: "Подтверждён" }).first().waitFor();
    await shot(page, "d08_order.png");
  });

  await step("Конструктор: «+», перетаскивание, фото цветов, отражение выбранного цветка, «Без упаковки», цена с сервера", async () => {
    await page.goto(BASE + "/constructor", { waitUntil: "networkidle" });
    await page.evaluate(() => localStorage.removeItem("cu_bouquet_draft_v2"));
    await page.reload({ waitUntil: "networkidle" });
    const rows = page.locator(".bq-row");
    await rows.first().waitFor();
    // строки с остатком ≥ 6 (демо-остатки расходуются прошлыми прогонами)
    const ok = [];
    for (let i = 0; i < (await rows.count()) && ok.length < 3; i++) {
      const t = await rows.nth(i).innerText();
      const m = t.match(/в наличии\s*(\d+)/);
      if (m && Number(m[1]) >= 6) ok.push(i);
    }
    if (ok.length < 3) throw new Error("мало цветов в наличии для теста");
    for (let i = 0; i < 5; i++) await rows.nth(ok[0]).getByRole("button", { name: /^Добавить/ }).click();
    for (let i = 0; i < 4; i++) await rows.nth(ok[1]).getByRole("button", { name: /^Добавить/ }).click();
    const heads = page.locator(".bq-svg g.bq-head");
    const before = await heads.count();
    // перетаскивание строки на эскиз
    await rows.nth(ok[2]).scrollIntoViewIfNeeded();
    const src = await rows.nth(ok[2]).boundingBox();
    const svg = await page.locator(".bq-svg").boundingBox();
    await page.mouse.move(src.x + 30, src.y + 30);
    await page.mouse.down();
    await page.mouse.move(src.x + 60, src.y + 40, { steps: 4 });
    await page.mouse.move(svg.x + svg.width * 0.5, svg.y + svg.height * 0.32, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(500);
    if ((await heads.count()) !== before + 1) throw new Error(`перетаскивание: было ${before}, стало ${await heads.count()}`);
    if (!(await page.locator(".bq-svg image").count())) throw new Error("на эскизе нет фото цветов");
    // выбор цветка на эскизе → панель «Отразить / Повернуть / Убрать»
    // цветок, бутон которого не закрыт упаковкой: точка в центре картинки попадает в тот же стебель
    await page.locator(".bq-svg").scrollIntoViewIfNeeded();
    const target = await page.evaluate(() => {
      for (const g of Array.from(document.querySelectorAll(".bq-svg g.bq-head")).reverse()) {
        const img = g.querySelector("image") || g;
        const r = img.getBoundingClientRect();
        const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const hit = document.elementFromPoint(x, y);
        if (hit && hit.closest("g.bq-head") === g) return { uid: g.getAttribute("data-uid"), x, y };
      }
      return null;
    });
    if (!target) throw new Error("не нашлось видимого цветка для выбора");
    const uid = target.uid;
    await page.mouse.click(target.x, target.y);
    await page.locator(".bq-sel-bar").waitFor();
    await page.locator(".bq-sel-bar").getByRole("button", { name: "Отразить" }).click();
    if ((await page.locator(`.bq-svg g.bq-head[data-uid="${uid}"]`).getAttribute("data-flip")) !== "1") throw new Error("цветок не отразился");
    await page.locator(".bq-sel-bar").getByRole("button", { name: /Повернуть вправо|↻/ }).first().click().catch(() => {});
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: /Зелень/ }).click();
    await page.locator(".bq-row").first().getByRole("button", { name: /^Добавить/ }).click();
    await page.getByRole("tab", { name: /Упаковка/ }).click();
    // «Без упаковки» — отдельный вариант, букет можно купить и без неё
    await page.locator(".bq-tile.none", { hasText: "Без упаковки" }).click();
    await page.waitForTimeout(700);
    if (await page.getByRole("button", { name: "В корзину" }).isDisabled()) throw new Error("без упаковки нельзя купить");
    await page.locator(".bq-tile:not(.none)").nth(1).click();
    await page.waitForTimeout(900);
    const total = await page.locator(".bq-total").first().innerText();
    if (!/[1-9]/.test(total)) throw new Error("нет итога: " + total);
    await shot(page, "d09_constructor.png");
    await page.getByRole("button", { name: "В корзину" }).click();
    await page.locator(".toast", { hasText: "Букет добавлен" }).waitFor();
  });

  await step("Конструктор: объёмная лента (PNG с сервера) и примерка букета в вазе", async () => {
    // упаковка не коробка + любая лента → на эскизе картинка банта
    const packs = page.locator(".bq-tiles").first().locator(".bq-tile:not(.none)");
    const nPacks = await packs.count();
    for (let i = 0; i < nPacks; i++) {
      if (!/коробк/i.test(await packs.nth(i).innerText())) { await packs.nth(i).click(); break; }
    }
    await page.locator(".bq-tiles").nth(1).locator(".bq-tile:not(.none)").first().click();
    const rib = page.locator(".bq-svg image[data-ribbon]");
    await rib.first().waitFor();
    const href = await rib.first().getAttribute("href");
    const res = await page.request.get(BASE + href);
    if (res.status() !== 200 || !/image\/png/.test(res.headers()["content-type"] || "")) throw new Error(`лента ${href}: ${res.status()}`);
    // «В вазе»: упаковка снята, стебли в воде, форма вазы переключается
    await page.getByRole("button", { name: "В вазе" }).click();
    await page.locator('.bq-svg [data-vase="cylinder"]').waitFor();
    await page.getByRole("radio", { name: "Шар" }).click();
    await page.locator('.bq-svg [data-vase="bubble"]').waitFor();
    await page.locator(".bq-vase-note").waitFor();
    await page.getByRole("radio", { name: "Цилиндр" }).click();
    await page.waitForTimeout(600);
    await shot(page, "d22_constructor_vase.png");
    await page.getByRole("button", { name: "Эскиз" }).click();
    if (await page.locator(".bq-svg [data-vase]").count()) throw new Error("ваза не убралась");
  });

  await step("Конструктор «По фото»: цветы, бумага, лента; не больше 30 цветков; оформление на усмотрение флориста", async () => {
    await page.goto(BASE + "/constructor?mode=photo", { waitUntil: "networkidle" });
    await page.evaluate(() => localStorage.removeItem("cu_bouquet_photo_v1"));
    await page.reload({ waitUntil: "networkidle" });
    const cards = page.locator(".pc-item");
    await cards.first().waitFor();
    // лимит: набираем 30 цветков из карточек с остатком — дальше «Добавить» недоступно
    let n = 0;
    for (let i = 0; i < (await cards.count()) && n < 30; i++) {
      const m = (await cards.nth(i).innerText()).match(/в наличии\s*(\d+)/);
      if (!m) continue;
      const k = Math.min(Number(m[1]), 30 - n);
      for (let j = 0; j < k; j++) await cards.nth(i).getByRole("button", { name: /^Добавить/ }).click();
      n += k;
    }
    if (n < 30) throw new Error("мало цветов в наличии для проверки лимита");
    await page.locator(".pc-count.full").waitFor();
    await page.locator(".bq-limit").waitFor();
    const more = await page.locator(".pc-item button[aria-label^='Добавить']:not([disabled])").count();
    if (more) throw new Error(`после 30 цветков доступно ещё ${more} кнопок «Добавить»`);
    // сервер тоже не примет больше 30
    const itemId = Number(await cards.first().getAttribute("data-item"));
    const r31 = await page.request.post(BASE + "/api/v1/constructor/quote", { data: { composition: { flowers: [{ item_id: itemId, quantity: 31 }], florist_choice: true } } });
    if (r31.status() !== 400 || (await r31.json()).error?.code !== "too_many_stems") throw new Error(`31 цветок: ${r31.status()}`);
    // обычный букет: 3 + 2 цветка, бумага, лента
    await page.evaluate(() => localStorage.removeItem("cu_bouquet_photo_v1"));
    await page.reload({ waitUntil: "networkidle" });
    await cards.first().waitFor();
    const ok = [];
    for (let i = 0; i < (await cards.count()) && ok.length < 2; i++) {
      const m = (await cards.nth(i).innerText()).match(/в наличии\s*(\d+)/);
      if (m && Number(m[1]) >= 4) ok.push(i);
    }
    for (let j = 0; j < 3; j++) await cards.nth(ok[0]).getByRole("button", { name: /^Добавить/ }).click();
    for (let j = 0; j < 2; j++) await cards.nth(ok[1]).getByRole("button", { name: /^Добавить/ }).click();
    await page.locator(".pc-tiles").nth(0).locator(".bq-tile:not(.none)").first().click();
    await page.locator(".pc-tiles").nth(1).locator(".bq-tile:not(.none)").first().click();
    await page.locator(".pc-lines").waitFor();
    if (await page.locator(".bq-svg").count()) throw new Error("в режиме «По фото» не должно быть эскиза");
    const total = await page.locator(".pc-side .bq-total").innerText();
    if (!/[1-9]/.test(total)) throw new Error("нет итога: " + total);
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot(page, "d24_constructor_photo.png", false);
    await page.locator(".pc-side").getByRole("button", { name: "В корзину" }).click();
    await page.locator(".toast", { hasText: "Букет добавлен" }).waitFor();
    await page.goto(BASE + "/cart", { waitUntil: "networkidle" });
    await page.locator(".cart-line .fchoice").waitFor();
    await page.getByText("оформление на усмотрение флориста").first().waitFor();
    await shot(page, "d25_cart_photo_bouquet.png", false);
  });

  let signedIn = false;
  if (loginTest) {
    await step("Вход через Telegram при оформлении (тестовый режим): данные подставлены, покупатель запомнен", async () => {
      await page.goto(BASE + "/checkout", { waitUntil: "networkidle" });
      await page.locator(".signin-card summary").click();
      await page.getByRole("button", { name: "Войти через Telegram" }).click();
      await page.waitForTimeout(500);
      for (const p of desktop.pages()) if (p !== page && /t\.me|vk\.me/.test(p.url() || "about:blank")) await p.close();
      await page.locator(".msgr-wait").waitFor();
      await shot(page, "d10a_login_wait.png", false);
      await page.getByRole("button", { name: /Подтвердить вход/ }).click();
      await page.locator(".signed-card").waitFor({ timeout: 10000 });
      const nm = await page.getByLabel("Имя *").inputValue();
      if (!nm) throw new Error("имя не подставилось из профиля");
      // токен входа — только в HttpOnly-cookie: JavaScript страницы его не видит
      const cookies = await page.context().cookies(BASE + "/api/v1/");
      const sess = cookies.find((c) => c.name === "cu_customer");
      if (!sess || !sess.httpOnly) throw new Error("cookie входа покупателя не установлен");
      const leaked = await page.evaluate(() => document.cookie.includes("cu_customer") || !!localStorage.getItem("cu_customer_token"));
      if (leaked) throw new Error("токен покупателя доступен из JavaScript");
      signedIn = true;
    });
  } else skip("Вход через Telegram при оформлении", "backend без CUSTOMER_LOGIN_TEST_MODE=true");

  await step("Заказ индивидуального букета: самовывоз, ожидает подтверждения", async () => {
    await page.goto(BASE + "/checkout", { waitUntil: "networkidle" });
    await page.getByLabel("Имя *").fill("Тест Конструктор");
    await page.getByLabel("Телефон *").fill("+7 900 111-22-44");
    await page.getByRole("button", { name: /Самовывоз/ }).click();
    await page.waitForTimeout(500);
    if (!(await page.locator(".slot:not([disabled])").count())) {
      const d = new Date(Date.now() + 86400000).toLocaleDateString("en-CA", { timeZone: "Asia/Yekaterinburg" });
      await page.locator('input[type="date"]').fill(d);
      await page.waitForTimeout(800);
    }
    await page.locator(".slot:not([disabled])").first().click();
    if (await page.locator('input[autocomplete="street-address"]').count()) throw new Error("для самовывоза не должен требоваться адрес");
    if ((await page.locator(".co-step").count()) !== 5) throw new Error("при самовывозе шага «Кому и куда доставить» быть не должно");
    await page.getByRole("button", { name: /Оформить заказ/ }).click();
    await waitOrder(page);
    await page.locator(".badge", { hasText: "Ожидает подтверждения" }).first().waitFor();
    if (signedIn) await page.locator(".notify-card", { hasText: "Уведомления включены" }).waitFor();
    await shot(page, "d10_custom_order.png");
  });

  let giftUrl = "";
  await step("Подарок: адрес узнаём у получателя, анонимно, фото перед отправкой; заказ запомнен на устройстве", async () => {
    const list = await (await page.request.get(BASE + "/api/v1/catalog/products?type=bouquet")).json();
    const gift = list.find((p) => p.available >= 1 && !p.made_to_order) || list.find((p) => p.available >= 1);
    if (!gift) throw new Error("нет букетов в наличии");
    await page.goto(BASE + "/product/" + gift.slug, { waitUntil: "networkidle" });
    await page.locator(".pd").getByRole("button", { name: /В корзину/ }).click();
    await page.locator(".toast", { hasText: "в корзине" }).waitFor();
    await page.goto(BASE + "/checkout", { waitUntil: "networkidle" });
    await page.getByLabel("Имя *", { exact: true }).fill("Тест Подарок");
    await page.getByLabel("Телефон *", { exact: true }).fill("+7 900 111-22-55");
    await page.getByRole("button", { name: /Другому человеку/ }).click();
    await page.getByLabel("Имя получателя *").fill("Мария");
    await page.getByLabel("Телефон получателя *").fill("+7 912 000-11-22");
    await page.getByTestId("ask-address").check();
    if (await page.locator('input[autocomplete="street-address"]').count()) throw new Error("при неизвестном адресе не нужна карта");
    if (await page.getByText("Сюрприз: не звонить заранее").count()) throw new Error("сюрприз несовместим с уточнением адреса");
    await page.locator('select[data-field="zone_id"]').selectOption({ index: 1 });
    await page.getByText("Не говорить, от кого букет").click();
    if (!(await page.getByTestId("photo-before").isChecked())) throw new Error("фото перед отправкой должно быть включено");
    await page.waitForSelector(".slot");
    if (!(await page.locator(".slot:not([disabled])").count())) {
      const d = new Date(Date.now() + 86400000).toLocaleDateString("en-CA", { timeZone: "Asia/Yekaterinburg" });
      await page.locator('input[type="date"]').fill(d);
      await page.waitForTimeout(800);
    }
    await page.locator(".slot:not([disabled])").first().click();
    await shot(page, "d27_checkout_gift.png");
    await page.getByRole("button", { name: /Оформить заказ/ }).click();
    await waitOrder(page);
    giftUrl = page.url().split("?")[0];
    await page.locator(".badge", { hasText: "Ожидает подтверждения" }).first().waitFor();
    await page.getByText("Флорист позвонит получателю").waitFor();
    await page.getByText("не говорим, от кого").waitFor();
    await page.goto(BASE + "/track", { waitUntil: "networkidle" });
    await page.getByTestId("saved-orders").locator("a").first().waitFor();
  });

  if (signedIn) {
    await step("Личный кабинет: профиль, каналы и история заказов", async () => {
      await page.goto(BASE + "/account", { waitUntil: "networkidle" });
      await page.locator(".acc-orders, .acc-order").first().waitFor({ timeout: 10000 });
      if (!(await page.getByText("Telegram").count())) throw new Error("нет привязанного Telegram");
      if (!(await page.getByText("Тест Конструктор").count()) && !(await page.locator(".acc-order").count())) throw new Error("нет заказов");
      await shot(page, "d11_account.png");
    });
  } else skip("Личный кабинет: профиль, каналы и история заказов", "покупатель не вошёл (нужен CUSTOMER_LOGIN_TEST_MODE=true)");

  await step("Страница «О нас»: текст и карусель фото", async () => {
    await page.goto(BASE + "/about", { waitUntil: "networkidle" });
    await page.locator(".about-text p").first().waitFor();
    const n = await page.locator(".about-slide").count();
    if (n < 1) throw new Error("нет фото в карусели");
    if (n > 1) {
      await page.getByRole("button", { name: "Следующее фото" }).click();
      await page.waitForTimeout(600);
    }
    await shot(page, "d12_about.png");
  });

  await step("На сайте нет симулятора ботов и ссылки «Для сотрудников»", async () => {
    const r = await page.request.get(BASE + "/simulator");
    if (r.status() !== 404) throw new Error("страница /simulator доступна: " + r.status());
    await page.goto(BASE + "/", { waitUntil: "networkidle" });
    const foot = await page.locator("footer").innerText();
    if (/Симулятор|Для сотрудников/i.test(foot)) throw new Error("в подвале остались лишние ссылки");
  });

  // ---------------- временные сотрудники для проверки ролей (удаляются в конце)
  const ownerLogin = await (await page.request.post(BASE + "/api/v1/admin/auth/login", { data: { username: OWNER_USER, password: OWNER_PASS } })).json();
  // вход — в HttpOnly-cookie (page.request делит cookie с браузером), сайт добавляет только этот заголовок
  const ownerHeaders = { "X-Requested-With": "fetch" };
  if (!ownerLogin.user) throw new Error("owner login failed");
  const tempStaff = [];
  for (const [username, role, first] of [["e2e-florist", "florist", "Тест-флорист"], ["e2e-courier", "courier", "Тест-курьер"]]) {
    const r = await page.request.post(BASE + "/api/v1/admin/staff", { headers: ownerHeaders, data: { username, role, first_name: first, password: STAFF_PASS } });
    if (r.ok()) tempStaff.push((await r.json()).id);
    else {
      const all = await (await page.request.get(BASE + "/api/v1/admin/staff", { headers: ownerHeaders })).json();
      const u = all.find((x) => x.username === username);
      if (u) { await page.request.patch(BASE + `/api/v1/admin/staff/${u.id}`, { headers: ownerHeaders, data: { password: STAFF_PASS, is_active: true } }); tempStaff.push(u.id); }
    }
  }

  // ---------------- админка
  const admin = await desktop.newPage();
  admin.on("pageerror", (e) => errors.push(`pageerror ${admin.url()}: ${e.message}`));
  await step("Админка: вход владельца и сводка", async () => {
    await admin.goto(BASE + "/admin/login", { waitUntil: "networkidle" });
    await shot(admin, "a00_login.png", false);
    await admin.getByLabel("Логин").fill(OWNER_USER);
    await admin.getByLabel("Пароль", { exact: true }).fill(OWNER_PASS);
    await admin.getByRole("button", { name: "Войти" }).click();
    await admin.waitForURL(/\/admin(\/password\?weak=1)?$/);
    if (admin.url().includes("/admin/password")) {
      // демо-пароль владельца: админка сразу предлагает его сменить
      await admin.getByText("демо-пароль").first().waitFor();
      await shot(admin, "a00b_weak_password.png", false);
      await admin.goto(BASE + "/admin", { waitUntil: "networkidle" });
      await admin.locator(".adm-weak").waitFor();
    }
    await admin.getByRole("heading", { name: "Сводка" }).waitFor();
    await admin.waitForTimeout(800);
    await shot(admin, "a01_dashboard.png");
  });

  await step("Админка: подтверждение индивидуального букета", async () => {
    await admin.goto(BASE + "/admin/orders?status=awaiting_confirmation", { waitUntil: "networkidle" });
    await admin.locator("tr.click").first().waitFor();
    await shot(admin, "a02_orders_confirm.png", false);
    await admin.locator("tr.click", { hasText: "Тест Конструктор" }).first().click();
    await admin.waitForURL(/\/admin\/orders\/\d+/);
    await admin.getByRole("button", { name: "Подтвердить состав" }).waitFor();
    await shot(admin, "a03_order_detail.png");
    await admin.getByRole("button", { name: "Подтвердить состав" }).click();
    // онлайн-оплата → после подтверждения флористом заказ ждёт оплаты
    await admin.locator(".adm-top .badge", { hasText: /Ожидает оплаты|Подтверждён/ }).first().waitFor();
  });

  await step("Админка: адрес от получателя → подтверждение → фото букета видно покупателю", async () => {
    if (!giftUrl) throw new Error("нет заказа-подарка");
    await admin.goto(BASE + "/admin/orders?status=awaiting_confirmation", { waitUntil: "networkidle" });
    await admin.locator("tr.click", { hasText: "Тест Подарок" }).first().click();
    await admin.waitForURL(/\/admin\/orders\/\d+/);
    const box = admin.getByTestId("ask-address");
    await box.waitFor();
    if (!(await admin.getByRole("button", { name: "Подтвердить заказ" }).isDisabled())) throw new Error("без адреса подтверждать нельзя");
    await shot(admin, "a16_order_ask_address.png");
    await box.getByLabel("Адрес доставки").fill("Кондратово, Красавинская улица, 8");
    await box.getByLabel("Квартира").fill("12");
    await box.getByRole("button", { name: "Сохранить адрес" }).click();
    await box.waitFor({ state: "detached", timeout: 15000 });
    await admin.getByRole("button", { name: "Подтвердить заказ" }).click();
    await admin.locator(".adm-top .badge", { hasText: /Ожидает оплаты|Подтверждён/ }).first().waitFor();
    // фото букета: берём фото товара с сайта
    const prod = (await (await admin.request.get(BASE + "/api/v1/catalog/products?type=bouquet")).json()).find((p) => p.image);
    const img = await (await admin.request.get(new URL(prod.image, BASE).href)).body();
    await admin.getByTestId("order-photos").locator('input[type="file"]').setInputFiles({ name: "bouquet.jpg", mimeType: "image/jpeg", buffer: img });
    await admin.getByTestId("order-photos").locator(".photo-tile img").first().waitFor({ timeout: 15000 });
    await admin.locator(".badge", { hasText: "Фото отправлено" }).waitFor();
    await shot(admin, "a17_order_photo.png");
    await page.goto(giftUrl, { waitUntil: "networkidle" });
    await page.getByTestId("order-photos").locator("img").first().waitFor();
    await shot(page, "d28_order_photo.png");
  });

  await step("Админка: заказы, склад, продажа, рецептуры, товары, доставки, настройки", async () => {
    await admin.goto(BASE + "/admin/orders", { waitUntil: "networkidle" });
    await admin.locator("tr.click").first().waitFor();
    await shot(admin, "a04_orders.png", false);
    await admin.goto(BASE + "/admin/inventory", { waitUntil: "networkidle" });
    await admin.locator("table.t tbody tr").first().waitFor();
    await shot(admin, "a05_inventory.png", false);
    await admin.goto(BASE + "/admin/store-sale", { waitUntil: "networkidle" });
    await admin.locator(".pos-item").first().waitFor();
    await shot(admin, "a06_store_sale.png", false);
    await admin.goto(BASE + "/admin/recipes", { waitUntil: "networkidle" });
    await admin.locator("table.t tbody tr").first().waitFor();
    await shot(admin, "a07_recipes.png", false);
    await admin.goto(BASE + "/admin/products", { waitUntil: "networkidle" });
    await admin.locator("tr.click").first().waitFor();
    await admin.locator("tr.click").first().click();
    await admin.locator(".modal").waitFor();
    await admin.waitForTimeout(600);
    await shot(admin, "a08_product_edit.png", false);
    await admin.keyboard.press("Escape");
    await admin.goto(BASE + "/admin/deliveries", { waitUntil: "networkidle" });
    await admin.waitForTimeout(800);
    await shot(admin, "a09_deliveries.png", false);
    await admin.goto(BASE + "/admin/settings", { waitUntil: "networkidle" });
    await admin.locator(".panel-title", { hasText: "Разделы сайта" }).waitFor();
    await admin.getByRole("tab", { name: "Доставка" }).click();
    await admin.locator(".panel-title", { hasText: "Районы доставки" }).waitFor();
    await shot(admin, "a10_settings.png", false);
    // статус ботов и подсказка, как их подключить (токены — только в .env)
    await admin.getByRole("tab", { name: "Система" }).click();
    const msg = admin.locator(".card", { has: admin.locator(".panel-title", { hasText: "Мессенджеры" }) });
    await msg.locator(".msg-row").first().waitFor();
    if ((await msg.locator(".msg-row").count()) !== 2) throw new Error("нет статуса Telegram/ВК");
    await msg.scrollIntoViewIfNeeded();
    await shot(admin, "a15_settings_messengers.png", false);
  });

  await step("Продажа в магазине уменьшает остаток на всех каналах", async () => {
    const list = await (await admin.request.get(BASE + "/api/v1/catalog/products?type=flower")).json();
    await admin.goto(BASE + "/admin/store-sale", { waitUntil: "networkidle" });
    await admin.getByRole("button", { name: "Цветы", exact: true }).click();
    const item = admin.locator(".pos-item:not([disabled])").first();
    const name = (await item.locator("b").innerText()).trim();
    const before = list.find((p) => p.name === name);
    await item.click();
    await admin.getByRole("button", { name: "Провести продажу" }).click();
    await admin.locator(".toast", { hasText: "проведена" }).waitFor();
    const after = await (await admin.request.get(BASE + "/api/v1/catalog/products/" + before.slug)).json();
    if (after.available !== before.available - 1) throw new Error(`«${name}»: было ${before.available}, стало ${after.available}`);
  });

  await step("Админка: закрыть приём заказов → на сайте плашка, «В корзину» и оформление недоступны → открыть", async () => {
    await admin.goto(BASE + "/admin/settings", { waitUntil: "networkidle" });
    const box = admin.getByTestId("orders-switch");
    await box.locator("textarea").fill("Мы на инвентаризации до завтра. Срочные заказы — по телефону.");
    admin.once("dialog", (d) => d.accept());
    await box.getByRole("button", { name: "Закрыть приём заказов" }).click();
    await admin.locator(".toast", { hasText: "Приём заказов закрыт" }).waitFor();
    await shot(admin, "a16_orders_closed_settings.png", false);
    const sp = await desktop.newPage();
    try {
      await sp.goto(BASE + "/bouquets", { waitUntil: "networkidle" });
      await sp.getByTestId("orders-closed").filter({ hasText: "инвентаризации" }).waitFor();
      if (await sp.locator(".pcard").getByRole("button", { name: /В корзину/ }).count()) throw new Error("при закрытом приёме видна кнопка «В корзину»");
      await sp.locator(".pcard").getByRole("button", { name: /Заказы на паузе/ }).first().waitFor();
      await shot(sp, "d30_orders_closed.png", false);
      // корзина на сервере тоже не принимает товары
      const cart = await (await sp.request.post(BASE + "/api/v1/carts", { data: {} })).json();
      const prods = await (await sp.request.get(BASE + "/api/v1/catalog/products?type=bouquet")).json();
      const r = await sp.request.post(BASE + `/api/v1/carts/${cart.token}/items`, { data: { product_id: prods[0].id, quantity: 1 } });
      if (r.status() !== 409) throw new Error("сервер принял товар при закрытом приёме: " + r.status());
      await sp.goto(BASE + "/checkout", { waitUntil: "networkidle" });
      await sp.locator(".notice", { hasText: "Приём заказов временно закрыт" }).waitFor();
      if (await sp.locator(".co-step").count()) throw new Error("форма оформления видна при закрытом приёме");
    } finally {
      await sp.close();
    }
    await admin.goto(BASE + "/admin", { waitUntil: "networkidle" });
    await admin.getByTestId("orders-paused").waitFor();
    await shot(admin, "a17_dashboard_orders_paused.png", false);
    await admin.getByRole("button", { name: "Открыть приём заказов" }).click();
    await admin.locator(".toast", { hasText: "Приём заказов открыт" }).waitFor();
    const pub = await (await admin.request.get(BASE + "/api/v1/settings/public")).json();
    if (pub.orders_enabled !== true) throw new Error("приём заказов не открылся");
  });

  await step("Админка: частые вопросы — новый блок и вопрос видны на главной", async () => {
    await admin.goto(BASE + "/admin/faq", { waitUntil: "networkidle" });
    await admin.getByTestId("faq-block").first().waitFor();
    const before = await admin.getByTestId("faq-block").count();
    await admin.getByRole("button", { name: "Новый блок" }).click();
    const blk = admin.getByTestId("faq-block").nth(before);
    await blk.locator("input").first().fill("Уход за букетом");
    await blk.getByLabel("Вопрос", { exact: true }).fill("Как продлить жизнь букету?");
    await blk.getByLabel("Ответ", { exact: true }).fill("Каждый день:\n- меняйте воду;\n- подрезайте стебли наискосок.\n\n**Не ставьте** букет у батареи. Подробнее — [о доставке](/delivery).");
    await blk.getByRole("button", { name: "Как на сайте" }).click();
    await blk.locator(".faq-ed-preview li").nth(1).waitFor();
    await shot(admin, "a18_faq_editor.png", false);
    await admin.getByRole("button", { name: "Сохранить" }).first().click();
    await admin.locator(".toast", { hasText: "Частые вопросы сохранены" }).waitFor();
    const hp = await desktop.newPage();
    try {
      await hp.goto(BASE + "/", { waitUntil: "networkidle" });
      await hp.locator(".faq-block-title", { hasText: "Уход за букетом" }).waitFor();
      const item = hp.locator(".faq-item", { hasText: "Как продлить жизнь букету?" });
      await item.locator("summary").click();
      await item.locator(".faq-a li", { hasText: "подрезайте стебли" }).waitFor();
      await item.locator(".faq-a b", { hasText: "Не ставьте" }).waitFor();
      await item.scrollIntoViewIfNeeded();
      await shot(hp, "d31_home_faq.png", false);
    } finally {
      await hp.close();
    }
    // вернуть стандартные — чтобы повторный прогон начинался с того же
    await admin.goto(BASE + "/admin/faq", { waitUntil: "networkidle" });
    admin.once("dialog", (d) => d.accept());
    await admin.getByRole("button", { name: "Вернуть стандартные" }).click();
    await admin.locator(".toast", { hasText: "Вернули стандартные" }).waitFor();
  });

  await step("Админка: «Поиск (SEO)» — свой заголовок страницы и код Яндекса попадают в HTML", async () => {
    await admin.goto(BASE + "/admin/settings?tab=seo", { waitUntil: "networkidle" });
    const card = admin.getByTestId("seo-delivery");
    await card.getByLabel("Заголовок (title)").fill("Доставка цветов в Кондратово и Перми — E2E");
    await admin.getByLabel("Яндекс Вебмастер — код мета-тега").fill('<meta name="yandex-verification" content="e2e1234567abcdef" />');
    await shot(admin, "a19_settings_seo.png", false);
    await admin.getByRole("button", { name: "Сохранить" }).first().click();
    await admin.locator(".toast", { hasText: "Настройки сохранены" }).waitFor();
    const html = await (await admin.request.get(BASE + "/delivery")).text();
    if (!html.includes("<title>Доставка цветов в Кондратово и Перми — E2E</title>")) throw new Error("заголовок страницы не применился");
    if (!html.includes('name="yandex-verification" content="e2e1234567abcdef"')) throw new Error("код Яндекс Вебмастера не попал в страницу");
    // вернуть как было
    await card.getByLabel("Заголовок (title)").fill("");
    await admin.getByLabel("Яндекс Вебмастер — код мета-тега").fill("");
    await admin.getByRole("button", { name: "Сохранить" }).first().click();
    await admin.locator(".toast", { hasText: "Настройки сохранены" }).waitFor();
    const sm = await (await admin.request.get(BASE + "/sitemap.xml")).text();
    if (!sm.includes("/product/")) throw new Error("в sitemap.xml нет товаров");
  });

  // ---------------- курьер
  const courierCtx = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "ru-RU" });
  const cp = await courierCtx.newPage();
  await step("Курьер видит только свои доставки", async () => {
    await cp.goto(BASE + "/admin/login", { waitUntil: "networkidle" });
    await cp.getByLabel("Логин").fill("e2e-courier");
    await cp.getByLabel("Пароль", { exact: true }).fill(STAFF_PASS);
    await cp.getByRole("button", { name: "Войти" }).click();
    await cp.locator(".kpi").first().waitFor();
    const nav = await cp.locator(".adm-nav").innerText();
    if (/Склад|Настройки|Сотрудники/.test(nav)) throw new Error("курьеру видны лишние разделы");
    await shot(cp, "a11_courier.png", false);
  });
  await courierCtx.close();

  // ---------------- мобильная версия
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "ru-RU" });
  const m = await mobile.newPage();
  m.on("pageerror", (e) => errors.push(`pageerror(m) ${m.url()}: ${e.message}`));
  const noHScroll = async (p) => {
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    if (sw > 392) throw new Error(`горизонтальный скролл на ${p.url()}: ${sw}px`);
  };
  await step("Мобильная версия: главная, каталог, товар, конструктор, корзина, оформление, «О нас», кабинет", async () => {
    await m.goto(BASE + "/", { waitUntil: "networkidle" });
    await shot(m, "m01_home.png", false);
    await noHScroll(m);
    await m.locator(".burger").click();
    await m.waitForTimeout(300);
    await shot(m, "m02_menu.png", false);
    await m.goto(BASE + "/bouquets", { waitUntil: "networkidle" });
    await shot(m, "m03_bouquets.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/product/pionovyy-rassvet", { waitUntil: "networkidle" });
    await noHScroll(m);
    await shot(m, "m04_product.png", true);
    await m.locator(".pd").getByRole("button", { name: /В корзину/ }).click().catch(() => {});
    await m.waitForTimeout(800);
    await m.goto(BASE + "/constructor", { waitUntil: "networkidle" });
    await shot(m, "m05_constructor.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/constructor?mode=photo", { waitUntil: "networkidle" });
    await m.locator(".pc-item").first().waitFor();
    await m.locator(".pc-item").first().getByRole("button", { name: /^Добавить/ }).click().catch(() => {});
    await m.locator(".pc-mbar").waitFor();
    await shot(m, "m12_constructor_photo.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/cart", { waitUntil: "networkidle" });
    await shot(m, "m06_cart.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/checkout", { waitUntil: "networkidle" });
    await shot(m, "m07_checkout.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/about", { waitUntil: "networkidle" });
    await shot(m, "m08_about.png", false);
    await noHScroll(m);
    await m.goto(BASE + "/account", { waitUntil: "networkidle" });
    await shot(m, "m10_account.png", false);
    await noHScroll(m);
  });
  await step("Мобильная админка", async () => {
    await m.goto(BASE + "/admin/login", { waitUntil: "networkidle" });
    await m.getByLabel("Логин").fill("e2e-florist");
    await m.getByLabel("Пароль", { exact: true }).fill(STAFF_PASS);
    await m.getByRole("button", { name: "Войти" }).click();
    await m.getByRole("heading", { name: "Сводка" }).waitFor();
    await m.waitForTimeout(600);
    await shot(m, "m09_admin.png", false);
  });

  await step("Временные сотрудники удалены", async () => {
    const relog = await (await page.request.post(BASE + "/api/v1/admin/auth/login", { data: { username: OWNER_USER, password: OWNER_PASS } })).json();
    for (const id of tempStaff) {
      const r = await page.request.delete(BASE + `/api/v1/admin/staff/${id}`, { headers: { "X-Requested-With": "fetch" } });
      if (!r.ok()) throw new Error(`не удалось удалить сотрудника ${id}: ${r.status()}`);
    }
  });

  await mobile.close();
  await desktop.close();
  await browser.close();
  const failed = results.filter((r) => r[0] === "FAIL").length;
  const skipped = results.filter((r) => r[0] === "SKIP").length;
  console.log(`\nИТОГО: ${results.length - failed - skipped} PASS, ${failed} FAIL${skipped ? `, ${skipped} SKIP` : ""}`);
  if (errors.length) console.log("Ошибки страниц:\n" + Array.from(new Set(errors)).slice(0, 30).join("\n"));
  fs.writeFileSync(path.join(SHOTS, "e2e_results.json"), JSON.stringify({ results, errors }, null, 2));
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
