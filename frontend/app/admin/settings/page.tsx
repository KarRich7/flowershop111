"use client";
import { SecurityStatus } from "@/components/admin/SecurityStatus";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { Logo } from "@/components/Logo";
import { ZoneEditor } from "@/components/maps/ZoneEditor";
import { ZoneMap } from "@/components/maps/ZoneMap";
import { ColorInput, Field } from "@/components/Field";
import { useShop } from "@/components/ShopProvider";
import { useToast } from "@/components/Toast";
import { adminApi, toKopecks, toRub, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import * as V from "@/lib/validate";

type S = Record<string, string | number | boolean | null>;
type Zone = { id: number; name: string; description: string; price: number; free_from: number | null; is_active: boolean; color: string; polygons: [number, number][][]; sort_order: number };
type Slot = { id: number; start_time: string; end_time: string; capacity: number; is_active: boolean };

type TextRule = { k: string; label: string; ph?: string; check: (v: string) => string | null; max: number; type?: string };
const TEXT: TextRule[] = [
  { k: "shop_name", label: "Название магазина", max: 120, check: (v) => V.text(v, "Название магазина", { required: true, min: 2, max: 120 }) },
  { k: "tagline", label: "Подпись над названием", max: 200, check: (v) => V.text(v, "Подпись", { max: 200 }) },
  { k: "city", label: "Город", max: 80, check: (v) => V.text(v, "Город", { required: true, min: 2, max: 80 }) },
  { k: "address", label: "Адрес самовывоза", max: 255, check: (v) => V.text(v, "Адрес", { required: true, min: 5, max: 255 }) },
  { k: "phone", label: "Телефон", max: 40, type: "tel", ph: "+7 (342) 000-00-00", check: (v) => V.phone(v, "Телефон") },
  { k: "email", label: "E-mail", max: 120, type: "email", check: (v) => V.email(v) },
  { k: "working_hours", label: "Часы работы", max: 120, ph: "Ежедневно 08:00–21:00", check: (v) => V.text(v, "Часы работы", { required: true, min: 2, max: 120 }) },
  { k: "telegram_url", label: "Telegram-бот", max: 200, ph: "https://t.me/имя_бота", check: (v) => V.url(v, ["t.me", "telegram.me"]) },
  { k: "vk_url", label: "Сообщество VK", max: 200, ph: "https://vk.com/имя", check: (v) => V.url(v, ["vk.com", "vk.ru", "m.vk.com"]) },
];

type NumRule = { k: string; label: string; unit: string; min: number; max: number; hint: string };
const GROUPS: { title: string; rules: NumRule[] }[] = [
  {
    title: "Оплата и резерв",
    rules: [
      { k: "online_reservation_minutes", label: "Ждём онлайн-оплату", unit: "мин", min: 5, max: 120, hint: "Не оплатили — заказ отменяется" },
      { k: "cod_unconfirmed_hold_minutes", label: "Резерв при оплате при получении", unit: "мин", min: 10, max: 1440, hint: "Пока флорист не подтвердит заказ" },
      { k: "confirmation_hold_hours", label: "Ждём подтверждения флориста", unit: "ч", min: 1, max: 72, hint: "Свои букеты и предзаказы" },
    ],
  },
  {
    title: "Сроки",
    rules: [
      { k: "min_lead_minutes", label: "Время на сборку до доставки", unit: "мин", min: 0, max: 720, hint: "Плюс 30 минут на дорогу" },
      { k: "pickup_ready_minutes", label: "Сборка к самовывозу", unit: "мин", min: 0, max: 480, hint: "После оплаты" },
      { k: "preorder_threshold_days", label: "Предзаказ — дальше чем", unit: "дн.", min: 1, max: 60, hint: "Такой заказ подтверждает флорист" },
      { k: "max_order_days_ahead", label: "Заказы вперёд на", unit: "дн.", min: 1, max: 365, hint: "Дальние даты недоступны" },
    ],
  },
  {
    title: "Конструктор букета",
    rules: [
      { k: "min_custom_stems", label: "Минимум цветов", unit: "шт", min: 1, max: 30, hint: "Зелень не считается" },
      { k: "max_custom_stems", label: "Максимум цветов", unit: "шт", min: 1, max: 30, hint: "Не больше 30" },
    ],
  },
];
const NUM_KEYS = GROUPS.flatMap((g) => g.rules);
const COLORS: [string, string][] = [["primary_color", "Основной цвет"], ["accent_color", "Акцент"], ["background_color", "Фон"]];

function validateSettings(f: S): V.Errors {
  const e: Record<string, string | null> = {};
  TEXT.forEach((r) => (e[r.k] = r.check(String(f[r.k] ?? ""))));
  NUM_KEYS.forEach((r) => (e[r.k] = V.int(String(f[r.k] ?? ""), r.label, { min: r.min, max: r.max })));
  COLORS.forEach(([k, l]) => (e[k] = V.hex(String(f[k] ?? ""), l, true)));
  e.florist_fee = V.rub(String(f.florist_fee ?? ""), "Работа флориста", { max: 10000 });
  if (!e.min_custom_stems && !e.max_custom_stems && Number(f.min_custom_stems) > Number(f.max_custom_stems)) e.min_custom_stems = "Минимум больше максимума";
  if (!e.preorder_threshold_days && !e.max_order_days_ahead && Number(f.preorder_threshold_days) > Number(f.max_order_days_ahead)) e.preorder_threshold_days = "Не может быть больше срока приёма заказов";
  const lat = String(f.shop_lat ?? ""), lon = String(f.shop_lon ?? "");
  if (lat || lon) {
    const la = Number(lat.replace(",", ".")), lo = Number(lon.replace(",", "."));
    if (!Number.isFinite(la) || la < 41 || la > 82) e.shop_lat = "Широта от 41 до 82, например 57.986";
    if (!Number.isFinite(lo) || lo < 19 || lo > 180) e.shop_lon = "Долгота от 19 до 180, например 56.118";
  }
  return V.collect(e);
}

type Tab = "shop" | "orders" | "delivery" | "seo" | "system";
const TABS: [Tab, string][] = [["shop", "Магазин"], ["orders", "Заказы и оплата"], ["delivery", "Доставка"], ["seo", "Поиск (SEO)"], ["system", "Система"]];
/** На какой вкладке поле — чтобы при ошибке открыть её */
const tabOf = (k: string): Tab =>
  k.startsWith("seo") || k.endsWith("_verification") ? "seo"
    : k === "shop_lat" || k === "shop_lon" ? "delivery"
      : NUM_KEYS.some((r) => r.k === k) || k === "florist_fee" ? "orders" : "shop";

type SeoPage = { title: string; description: string };
/** Дополнительные поля ответа /admin/settings для вкладки «Поиск (SEO)» */
type SeoInfo = {
  seo_pages?: Record<string, SeoPage>;
  seo_defaults?: Record<string, SeoPage>;
  seo_page_list?: { key: string; path: string; label: string }[];
  site_url?: string;
  orders_closed_default?: string;
};
/** Свой ли ключ у объекта: «constructor» есть у любого объекта JavaScript, поэтому obj[key] не годится */
const hasKey = (o: object, k: string) => Object.prototype.hasOwnProperty.call(o, k);
// рекомендации поисковиков: длиннее — обрежут в выдаче
const TITLE_REC = 60;
const DESC_REC = 160;

export default function SettingsPage() {
  const me = useStaff();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("shop");
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("tab");
    if (TABS.some(([k]) => k === q)) setTab(q as Tab);
    else if (window.location.hash === "#security") setTab("system");
  }, []);
  const openTab = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", t === "shop" ? "/admin/settings" : `/admin/settings?tab=${t}`);
  };
  const { data, error, setData } = useAdmin<S>(me.role === "owner" ? "/settings" : null);
  const [f, setF] = useState<S | null>(null);
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const [seo, setSeo] = useState<Record<string, SeoPage>>({});
  const [ordersBusy, setOrdersBusy] = useState(false);
  const info = (data || {}) as unknown as SeoInfo;
  useEffect(() => {
    if (!data) return;
    setF({ ...data, florist_fee: toRub(data.florist_fee as number) });
    setSeo({ ...((data as unknown as SeoInfo).seo_pages || {}) });
  }, [data]);
  if (me.role !== "owner") return <ErrorBox text="Раздел доступен только владельцу" />;
  const set = (k: string, v: string | boolean) => {
    setF((x) => (x ? { ...x, [k]: v } : x));
    setErrors((e) => ({ ...e, [k]: "" }));
  };

  async function save() {
    if (!f) return;
    const errs = validateSettings(f);
    setErrors(errs);
    if (V.hasErrors(errs)) {
      const first = Object.keys(errs).find((k) => errs[k]);
      if (first) setTab(tabOf(first));
      toast("Проверьте выделенные поля", "err");
      return;
    }
    setBusy(true);
    const body: Record<string, unknown> = {};
    TEXT.forEach((r) => (body[r.k] = String(f[r.k] ?? "").trim()));
    NUM_KEYS.forEach((r) => (body[r.k] = Number(f[r.k])));
    COLORS.forEach(([k]) => (body[k] = f[k]));
    body.florist_fee = toKopecks(f.florist_fee as string) || 0;
    body.allow_cash_on_delivery = Boolean(f.allow_cash_on_delivery);
    body.flowers_section_enabled = f.flowers_section_enabled !== false;
    body.constructor_section_enabled = f.constructor_section_enabled !== false;
    body.customer_login_enabled = f.customer_login_enabled !== false;
    body.orders_enabled = f.orders_enabled !== false;
    body.orders_closed_message = String(f.orders_closed_message ?? "").trim();
    body.seo_pages = seo;
    body.yandex_verification = String(f.yandex_verification ?? "").trim();
    body.google_verification = String(f.google_verification ?? "").trim();
    if (f.shop_lat !== "" && f.shop_lat != null && f.shop_lon !== "" && f.shop_lon != null) {
      body.shop_lat = Number(String(f.shop_lat).replace(",", "."));
      body.shop_lon = Number(String(f.shop_lon).replace(",", "."));
    }
    try {
      setData(await adminApi<S>("/settings", { method: "PATCH", body }));
      toast("Настройки сохранены", "ok");
    } catch (e) {
      const msg = V.serverError(e, setErrors);
      const field = e instanceof ApiError ? (e.details?.field as string | undefined) : undefined;
      if (field) setTab(tabOf(field));
      toast(msg, "err");
    } finally {
      setBusy(false);
    }
  }

  /** Открыть/закрыть приём заказов — сохраняется сразу, без кнопки «Сохранить» */
  async function toggleOrders() {
    if (!f) return;
    const open = f.orders_enabled === false;
    if (!open && !window.confirm("Закрыть приём заказов? Покупатели не смогут оформить новый заказ на сайте и в ботах, пока вы снова не откроете приём.")) return;
    setOrdersBusy(true);
    try {
      const r = await adminApi<S>("/settings", { method: "PATCH", body: { orders_enabled: open, orders_closed_message: String(f.orders_closed_message ?? "").trim() } });
      setF((x) => (x ? { ...x, orders_enabled: r.orders_enabled, orders_closed_message: r.orders_closed_message } : x));
      toast(open ? "Приём заказов открыт" : "Приём заказов закрыт", "ok");
    } catch (e) {
      toast(V.serverError(e, setErrors), "err");
    } finally {
      setOrdersBusy(false);
    }
  }

  async function upload(key: "logo" | "hero_image", file: File) {
    if (file.size > 8 * 1024 * 1024) return toast("Файл больше 8 МБ", "err");
    const fd = new FormData();
    fd.append(key, file);
    try {
      setData(await adminApi<S>("/settings", { method: "POST", form: fd }));
      toast("Изображение загружено", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }

  const sections: [string, string, string][] = [
    ["flowers_section_enabled", "Цветы поштучно", "Отдельные цветы и зелень"],
    ["constructor_section_enabled", "Собрать букет", "Конструктор своего букета"],
    ["customer_login_enabled", "Кнопка «Войти»", "Вход покупателей через Telegram и ВКонтакте"],
  ];
  const ordersOn = f?.orders_enabled !== false;
  const constructorOn = f?.constructor_section_enabled !== false;

  return (
    <>
      <PageTop title="Настройки">
        {tab !== "system" && <button className="btn btn-sm" disabled={busy || !f} onClick={save}>{busy ? "Сохраняем…" : "Сохранить"}</button>}
      </PageTop>
      <ErrorBox text={error} />
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => openTab(k)}>{l}</button>
        ))}
      </div>
      {!f ? <Loading /> : (
        <div className="stack">
          {tab === "shop" && (
            <>
              <div className={`card orders-card ${ordersOn ? "" : "off"}`} data-testid="orders-switch">
                <div className="row-between">
                  <div>
                    <div className="panel-title" style={{ margin: 0 }}>
                      Приём заказов: <span className={`badge ${ordersOn ? "green" : "amber"}`}>{ordersOn ? "открыт" : "закрыт"}</span>
                    </div>
                    <span className="hint">
                      {ordersOn
                        ? "Покупатели оформляют заказы на сайте и в ботах."
                        : "На сайте видна плашка с вашим сообщением, кнопки «В корзину» и оформление отключены, боты тоже не принимают заказы."}
                    </span>
                  </div>
                  <button type="button" className={`btn btn-sm ${ordersOn ? "btn-danger" : ""}`} disabled={ordersBusy} onClick={toggleOrders}>
                    {ordersBusy ? "Сохраняем…" : ordersOn ? "Закрыть приём заказов" : "Открыть приём заказов"}
                  </button>
                </div>
                <Field label="Сообщение покупателям, пока приём закрыт" error={errors.orders_closed_message} hint="Например: «Мы в отпуске до 15 января. Заказы на праздники — по телефону». Пусто — стандартный текст.">
                  <textarea className="textarea" rows={2} maxLength={300} placeholder={info.orders_closed_default || ""} value={String(f.orders_closed_message ?? "")} onChange={(e) => set("orders_closed_message", e.target.value)} />
                </Field>
                <p className="hint" style={{ margin: "8px 0 0" }}>
                  Кнопка сохраняет сразу. Уже оформленные заказы не затрагиваются: их можно подтверждать, собирать и доставлять. Продажи на кассе в магазине работают.
                </p>
              </div>
              <div className="card">
                <div className="panel-title">Разделы сайта</div>
                <div className="sections-grid">
                  {sections.map(([k, l, h]) => (
                    <label key={k} className="checkbox section-toggle">
                      <input type="checkbox" checked={f[k] !== false} onChange={(e) => set(k, e.target.checked)} />
                      <span><b>{l}</b> <span className="hint">— {h}</span></span>
                    </label>
                  ))}
                </div>
                <p className="hint" style={{ margin: "8px 0 0" }}>
                  Выключенный раздел пропадает из меню, и такие заказы не принимаются. Без кнопки «Войти» покупатели оформляют заказ как обычно — по имени и телефону.
                </p>
              </div>
              <div className="grid-2">
                <div className="card">
                  <div className="panel-title">Контакты</div>
                  <div className="stack">
                    {TEXT.map((r) => (
                      <Field key={r.k} label={r.label} error={errors[r.k]}>
                        <input className="input" type={r.type || "text"} maxLength={r.max} placeholder={r.ph} value={String(f[r.k] ?? "")} onChange={(e) => set(r.k, e.target.value)} />
                      </Field>
                    ))}
                  </div>
                </div>
                <div className="card">
                  <div className="panel-title">Логотип и цвета</div>
                  <div className="notice small" style={{ marginBottom: 12, background: "#fff", border: "1px solid var(--line)" }}>
                    <Logo settings={{ shop_name: String(f.shop_name || ""), tagline: String(f.tagline || ""), logo: (f.logo as string) || null }} />
                  </div>
                  <div className="form-grid">
                    {COLORS.map(([k, l]) => (
                      <Field key={k} label={l} error={errors[k]}>
                        <ColorInput value={String(f[k] || "")} invalid={!!errors[k]} label={l} onChange={(v) => set(k, v)} />
                      </Field>
                    ))}
                  </div>
                  <div className="row" style={{ marginTop: 14 }}>
                    <label className="btn btn-sm btn-ghost">Загрузить логотип<input type="file" accept="image/png,image/webp,image/jpeg,image/svg+xml" hidden onChange={(e) => { const x = e.target.files?.[0]; e.target.value = ""; if (x) upload("logo", x); }} /></label>
                    <label className="btn btn-sm btn-ghost">Обложка для соцсетей<input type="file" accept="image/png,image/webp,image/jpeg" hidden onChange={(e) => { const x = e.target.files?.[0]; e.target.value = ""; if (x) upload("hero_image", x); }} /></label>
                  </div>
                  {f.hero_image && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={String(f.hero_image)} alt="Обложка" style={{ marginTop: 12, borderRadius: 12, maxHeight: 120, objectFit: "cover", width: "100%" }} />
                  )}
                </div>
              </div>
            </>
          )}

          {tab === "orders" && (
            <div className="rules-grid">
              {GROUPS.filter((g) => constructorOn || !g.title.startsWith("Конструктор")).map((g) => (
                <div className="card rules-card" key={g.title}>
                  <h3>{g.title}</h3>
                  <div className="stack">
                    {g.title.startsWith("Конструктор") && (
                      <NumInput label="Работа флориста" unit="₽" hint="Добавляется к цене каждого своего букета"
                        value={String(f.florist_fee ?? "")} error={errors.florist_fee} decimal onChange={(v) => set("florist_fee", v)} />
                    )}
                    {g.rules.map((r) => (
                      <NumInput key={r.k} label={r.label} unit={r.unit} hint={r.hint}
                        value={String(f[r.k] ?? "")} error={errors[r.k]} min={r.min} max={r.max} onChange={(v) => set(r.k, v)} />
                    ))}
                    {g.title.startsWith("Оплата") && (
                      <div className="rules-switch">
                        <label className="checkbox">
                          <input type="checkbox" checked={Boolean(f.allow_cash_on_delivery)} onChange={(e) => set("allow_cash_on_delivery", e.target.checked)} /> Разрешить оплату при получении
                        </label>
                        <span className="hint">Выключено — только онлайн-оплата</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "delivery" && (
            <>
              <Zones />
              <Slots />
              <div className="card">
                <div className="panel-title">Точка самовывоза на карте</div>
                <div className="form-grid">
                  <Field label="Широта" error={errors.shop_lat}><input className="input" inputMode="decimal" value={String(f.shop_lat ?? "")} onChange={(e) => set("shop_lat", e.target.value)} /></Field>
                  <Field label="Долгота" error={errors.shop_lon}><input className="input" inputMode="decimal" value={String(f.shop_lon ?? "")} onChange={(e) => set("shop_lon", e.target.value)} /></Field>
                </div>
                <ShopPoint lat={f.shop_lat} lon={f.shop_lon} onPick={(lat, lon) => setF((x) => (x ? { ...x, shop_lat: lat.toFixed(6), shop_lon: lon.toFixed(6) } : x))} />
                <p className="hint" style={{ marginTop: 8 }}>Нажмите на карту, чтобы перенести метку, затем «Сохранить».</p>
              </div>
            </>
          )}

          {tab === "seo" && (
            <SeoTab
              info={info}
              seo={seo}
              errors={errors}
              yandex={String(f.yandex_verification ?? "")}
              google={String(f.google_verification ?? "")}
              onPage={(k, part, v) => {
                setSeo((x) => {
                  const cur = hasKey(x, k) ? x[k] : { title: "", description: "" };
                  return { ...x, [k]: { title: cur.title || "", description: cur.description || "", [part]: v } };
                });
                setErrors((e) => ({ ...e, [`seo.${k}.${part}`]: "" }));
              }}
              onCode={(k, v) => set(k, v)}
            />
          )}

          {tab === "system" && (
            <>
              <Messengers />
              <MapsStatus />
              <div id="security"><SecurityStatus /></div>
              <div className="card row-between">
                <div>
                  <div className="panel-title" style={{ margin: 0 }}>Журнал действий</div>
                  <span className="hint">Кто и что менял в админке</span>
                </div>
                <Link href="/admin/audit" className="btn btn-sm btn-outline">Открыть</Link>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

type Check = { ok: boolean | null; message: string };
type MapsReport = {
  maps: Check & { key: string };
  geocoder: Check & { key: string; separate_key: boolean; hint: string };
  nominatim: Check;
  active: string;
  active_label: string;
  yandex_paused: boolean;
};

/** Ключ Яндекс Карт: принят ли картой и HTTP Геокодером. Ключ — секрет сервера (.env), здесь только проверка */
function MapsStatus() {
  const shop = useShop();
  const [r, setR] = useState<MapsReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function check() {
    setBusy(true);
    setErr("");
    try {
      setR(await adminApi<MapsReport>("/maps/check"));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Не удалось проверить");
    } finally {
      setBusy(false);
    }
  }
  const row = (name: string, c: Check, extra?: string) => (
    <div className={`msg-row ${c.ok ? "on" : ""}`}>
      <span className={`msg-dot ${c.ok === false ? "bad" : ""}`} aria-hidden />
      <div>
        <b>{name}</b> — {c.message}
        {extra && <div className="hint">{extra}</div>}
      </div>
    </div>
  );
  return (
    <div className="card" data-testid="maps-status">
      <div className="row-between">
        <div className="panel-title" style={{ margin: 0 }}>Карта и поиск адресов</div>
        <button className="btn btn-sm btn-outline" onClick={check} disabled={busy}>{busy ? "Проверяем…" : "Проверить ключ Яндекса"}</button>
      </div>
      {!r ? (
        <p className="hint" style={{ marginTop: 10, marginBottom: 0 }}>
          Сейчас адреса проверяет: <b>{shop.maps?.geocoder === "yandex" ? "Яндекс" : shop.maps?.geocoder === "nominatim" ? "Nominatim (OpenStreetMap)" : "—"}</b>.
        </p>
      ) : (
        <div className="msg-status" style={{ marginTop: 12 }}>
          {row("Карта (JavaScript API)", r.maps)}
          {row(`HTTP Геокодер Яндекса${r.geocoder.separate_key ? " (отдельный ключ)" : ""}`, r.geocoder, r.geocoder.hint)}
          {row("Запасной геокодер OpenStreetMap", r.nominatim)}
          <p className="hint" style={{ margin: 0 }}>
            Сейчас адреса проверяет: <b>{r.active_label}</b>
            {r.yandex_paused ? " — Яндекс отклонил запрос, сайт попробует его снова через 10 минут. Покупатели в это время оформляют заказы как обычно." : "."}
          </p>
        </div>
      )}
      {err && <div className="notice red small" style={{ marginTop: 10 }}>{err}</div>}
    </div>
  );
}

/** Статус ботов: токены — секреты сервера (.env), в админке их не вводят; здесь — что подключено и как включить */
function Messengers() {
  const shop = useShop();
  const tg = !!shop.bots?.telegram_connected;
  const vk = !!shop.bots?.vk_connected;
  const rows = [
    { name: "Telegram-бот", on: tg && !!shop.customer_login?.telegram, env: "TELEGRAM_BOT_TOKEN и TELEGRAM_BOT_USERNAME", warn: tg && !shop.customer_login?.telegram ? "Токен задан, но не удалось узнать имя бота — укажите TELEGRAM_BOT_USERNAME" : "" },
    { name: "ВКонтакте", on: vk, env: "VK_GROUP_TOKEN и VK_GROUP_ID", warn: "" },
  ];
  return (
    <div className="card">
      <div className="panel-title">Мессенджеры</div>
      <div className="msg-status">
        {rows.map((r) => (
          <div key={r.name} className={`msg-row ${r.on ? "on" : ""}`}>
            <span className="msg-dot" aria-hidden />
            <div>
              <b>{r.name}</b> — {r.on ? "подключён" : "не подключён"}
              {!r.on && (
                <div className="hint">
                  {r.warn || <>Нужны {r.env} в <code>.env</code> на сервере — памятка владельца, раздел 5.</>}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function NumInput({ label, unit, hint, value, error, min, max, decimal, onChange }: {
  label: string; unit: string; hint?: string; value: string; error?: string; min?: number; max?: number; decimal?: boolean; onChange: (v: string) => void;
}) {
  return (
    <Field label={label} error={error} hint={hint}>
      <span className="input-unit">
        <input className="input" inputMode={decimal ? "decimal" : "numeric"} type={decimal ? "text" : "number"} min={min} max={max} step={1} value={value} onChange={(e) => onChange(e.target.value)} />
        <span>{unit}</span>
      </span>
    </Field>
  );
}

function ShopPoint({ lat, lon, onPick }: { lat: S[string]; lon: S[string]; onPick: (lat: number, lon: number) => void }) {
  const la = Number(lat), lo = Number(lon);
  const point: [number, number] | null = lat !== "" && lat != null && lon !== "" && lon != null && Number.isFinite(la) && Number.isFinite(lo) ? [la, lo] : null;
  return <ZoneMap zones={[]} point={point} onPick={onPick} zoom={14} className="sm" />;
}

function zoneErrors(name: string, price: string, free: string): V.Errors {
  return V.collect({
    name: V.text(name, "Название района", { required: true, min: 2, max: 120 }),
    price: V.rub(price, "Стоимость", { max: 100000 }),
    free_from: V.rub(free, "Бесплатно от", { required: false, min: 1, max: 1_000_000 }),
  });
}

function Zones() {
  const toast = useToast();
  const { data, reload } = useAdmin<Zone[]>("/delivery-zones");
  const [edits, setEdits] = useState<Record<number, Partial<Record<keyof Zone, string | boolean>>>>({});
  const [errs, setErrs] = useState<Record<string, V.Errors>>({});
  const [nz, setNz] = useState({ name: "", price: "", free_from: "1500" });
  const [editing, setEditing] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  async function save(z: Zone) {
    const e = edits[z.id] || {};
    const er = zoneErrors(String(e.name ?? z.name), String(e.price ?? toRub(z.price)), String(e.free_from ?? toRub(z.free_from)));
    setErrs((x) => ({ ...x, [z.id]: er }));
    if (V.hasErrors(er)) return toast(Object.values(er)[0], "err");
    const body: Record<string, unknown> = {};
    if (e.name !== undefined) body.name = String(e.name).trim();
    if (e.price !== undefined) body.price = toKopecks(e.price as string) || 0;
    if (e.free_from !== undefined) body.free_from = toKopecks(e.free_from as string);
    if (e.is_active !== undefined) body.is_active = e.is_active;
    if (e.color !== undefined) body.color = e.color;
    try {
      await adminApi(`/delivery-zones/${z.id}`, { method: "PATCH", body });
      setEdits((x) => ({ ...x, [z.id]: {} }));
      toast("Район сохранён", "ok");
      reload();
    } catch (err) {
      toast(V.serverError(err, (fn) => setErrs((x) => ({ ...x, [z.id]: fn(x[z.id] || {}) }))), "err");
    }
  }
  async function remove(z: Zone) {
    if (!confirm(`Удалить район «${z.name}»? Адреса из него перестанут приниматься. Прошлые заказы с доставкой в этот район сохранятся.`)) return;
    try {
      const r = await adminApi<{ message: string }>(`/delivery-zones/${z.id}`, { method: "DELETE" });
      if (editing === z.id) setEditing(null);
      toast(r.message, "ok");
      reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Ошибка", "err");
    }
  }
  async function add() {
    const er = zoneErrors(nz.name, nz.price, nz.free_from);
    setErrs((x) => ({ ...x, new: er }));
    if (V.hasErrors(er)) return;
    try {
      const r = await adminApi<Zone[]>("/delivery-zones", { body: { name: nz.name.trim(), price: toKopecks(nz.price) || 0, free_from: toKopecks(nz.free_from) } });
      setNz({ name: "", price: "", free_from: "1500" });
      reload();
      const created = r.find((z) => z.name === nz.name.trim());
      if (created) setEditing(created.id);
      toast("Район добавлен — нарисуйте его границы на карте", "ok");
    } catch (err) {
      toast(V.serverError(err, (fn) => setErrs((x) => ({ ...x, new: fn(x.new || {}) }))), "err");
    }
  }
  const ne = errs.new || {};
  return (
    <div className="card">
      <div className="panel-title">Районы доставки</div>
      <p className="hint" style={{ marginTop: -6 }}>Адреса вне активных районов не принимаются. Не возите в район — снимите галочку «Активен».</p>
      {!data ? <Loading /> : (
        <div className="stack">
          <div className="table-wrap zone-table" style={{ border: 0 }}>
            <table className="t">
              <thead><tr><th>Цвет</th><th>Район</th><th>Стоимость, ₽</th><th>Бесплатно от, ₽</th><th className="num">Контуров</th><th>Активен</th><th></th></tr></thead>
              <tbody>
                {data.map((z) => {
                  const e = edits[z.id] || {};
                  const er = errs[z.id] || {};
                  const changed = Object.keys(e).length > 0;
                  const upd = (k: keyof Zone, v: string | boolean) => {
                    setEdits((x) => ({ ...x, [z.id]: { ...(x[z.id] || {}), [k]: v } }));
                    setErrs((x) => ({ ...x, [z.id]: { ...(x[z.id] || {}), [k]: "" } }));
                  };
                  return (
                    <tr key={z.id} className={editing === z.id ? "zone-edit-on" : ""}>
                      <td style={{ width: 56 }}>
                        <input type="color" aria-label="Цвет района" value={String(e.color ?? z.color ?? "#5b7f4f").toLowerCase()} onChange={(ev) => upd("color", ev.target.value)} style={{ width: 36, height: 32, border: 0, background: "none", padding: 0 }} />
                      </td>
                      <td><input className={`input input-sm ${er.name ? "invalid" : ""}`} title={er.name || ""} maxLength={120} value={String(e.name ?? z.name)} onChange={(ev) => upd("name", ev.target.value)} /></td>
                      <td style={{ width: 128 }}><input className={`input input-sm ${er.price ? "invalid" : ""}`} title={er.price || ""} inputMode="decimal" value={String(e.price ?? toRub(z.price))} onChange={(ev) => upd("price", ev.target.value)} /></td>
                      <td style={{ width: 140 }}><input className={`input input-sm ${er.free_from ? "invalid" : ""}`} title={er.free_from || ""} inputMode="decimal" placeholder="нет" value={String(e.free_from ?? toRub(z.free_from))} onChange={(ev) => upd("free_from", ev.target.value)} /></td>
                      <td className="num">{z.polygons.length || <span style={{ color: "var(--red)" }}>нет</span>}</td>
                      <td><input type="checkbox" checked={Boolean(e.is_active ?? z.is_active)} onChange={(ev) => upd("is_active", ev.target.checked)} /></td>
                      <td className="nowrap">
                        <button className="btn btn-xs btn-ghost" onClick={() => setEditing(editing === z.id ? null : z.id)}>Границы</button>{" "}
                        <button className="btn btn-xs" disabled={!changed} onClick={() => save(z)}>Сохранить</button>{" "}
                        <button className="btn btn-xs btn-quiet" style={{ color: "var(--red)" }} onClick={() => remove(z)} aria-label={`Удалить район ${z.name}`}>Удалить</button>
                        {Object.values(er).filter(Boolean).length > 0 && <div className="field-err">{Object.values(er).filter(Boolean)[0]}</div>}
                      </td>
                    </tr>
                  );
                })}
                <tr>
                  <td></td>
                  <td><input className={`input input-sm ${ne.name ? "invalid" : ""}`} maxLength={120} placeholder="Новый район" value={nz.name} onChange={(e) => { setNz({ ...nz, name: e.target.value }); setErrs((x) => ({ ...x, new: {} })); }} /></td>
                  <td><input className={`input input-sm ${ne.price ? "invalid" : ""}`} inputMode="decimal" placeholder="500" value={nz.price} onChange={(e) => { setNz({ ...nz, price: e.target.value }); setErrs((x) => ({ ...x, new: {} })); }} /></td>
                  <td><input className={`input input-sm ${ne.free_from ? "invalid" : ""}`} inputMode="decimal" placeholder="нет" value={nz.free_from} onChange={(e) => { setNz({ ...nz, free_from: e.target.value }); setErrs((x) => ({ ...x, new: {} })); }} /></td>
                  <td></td>
                  <td></td>
                  <td>
                    <button className="btn btn-xs" onClick={add}>Добавить район</button>
                    {Object.values(ne).filter(Boolean).length > 0 && <div className="field-err">{Object.values(ne).filter(Boolean)[0]}</div>}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <ZoneEditor zones={data} editingId={editing} onSave={saveRings} onCancel={() => setEditing(null)} busy={saving} />
        </div>
      )}
    </div>
  );

  async function saveRings(rings: [number, number][][]) {
    if (!editing) return;
    setSaving(true);
    try {
      await adminApi(`/delivery-zones/${editing}`, { method: "PATCH", body: { polygons: rings } });
      toast(rings.length ? "Границы района сохранены" : "Границы удалены: район не принимает адреса", "ok");
      setEditing(null);
      reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Ошибка", "err");
    } finally {
      setSaving(false);
    }
  }
}

function Slots() {
  const toast = useToast();
  const { data, reload } = useAdmin<Slot[]>("/delivery-slots");
  const [ns, setNs] = useState({ start_time: "", end_time: "", capacity: "4" });
  const [err, setErr] = useState("");
  async function patch(s: Slot, body: Record<string, unknown>) {
    try {
      await adminApi(`/delivery-slots/${s.id}`, { method: "PATCH", body });
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
      reload();
    }
  }
  async function remove(s: Slot) {
    if (!confirm(`Удалить интервал ${s.start_time}–${s.end_time}?`)) return;
    try {
      const r = await adminApi<{ message: string }>(`/delivery-slots/${s.id}`, { method: "DELETE" });
      toast(r.message, "ok");
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }
  async function add() {
    const e = V.time(ns.start_time, "Начало") || V.time(ns.end_time, "Конец")
      || (ns.end_time <= ns.start_time ? "Конец интервала должен быть позже начала" : null)
      || V.int(ns.capacity, "Заказов в интервал", { min: 1, max: 100 });
    setErr(e || "");
    if (e) return;
    try {
      await adminApi("/delivery-slots", { body: { ...ns, capacity: Number(ns.capacity) } });
      setNs({ start_time: "", end_time: "", capacity: "4" });
      reload();
    } catch (x) {
      setErr(V.serverError(x));
    }
  }
  return (
    <div className="card">
      <div className="panel-title">Интервалы доставки и самовывоза</div>
      <p className="hint" style={{ marginTop: -6 }}>Набралось максимум заказов — интервал на эту дату закрывается.</p>
      {!data ? <Loading /> : (
        <div className="table-wrap" style={{ border: 0 }}>
          <table className="t">
            <thead><tr><th>Интервал</th><th>Макс. заказов в интервал</th><th>Активен</th><th></th></tr></thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)}</b></td>
                  <td style={{ width: 200 }}>
                    <input className="input input-sm" type="number" min={1} max={100} step={1} defaultValue={s.capacity}
                      onBlur={(e) => {
                        const bad = V.int(e.target.value, "Заказов", { min: 1, max: 100 });
                        if (bad) { toast(`Макс. заказов: ${bad.toLowerCase()}`, "err"); e.target.value = String(s.capacity); return; }
                        if (Number(e.target.value) !== s.capacity) patch(s, { capacity: Number(e.target.value) });
                      }} />
                  </td>
                  <td><input type="checkbox" checked={s.is_active} onChange={(e) => patch(s, { is_active: e.target.checked })} /></td>
                  <td><button className="btn btn-xs btn-quiet" style={{ color: "var(--red)" }} onClick={() => remove(s)}>Удалить</button></td>
                </tr>
              ))}
              <tr>
                <td className="row" style={{ flexWrap: "nowrap" }}>
                  <input className="input input-sm" type="time" aria-label="Начало" value={ns.start_time} onChange={(e) => { setNs({ ...ns, start_time: e.target.value }); setErr(""); }} />
                  <input className="input input-sm" type="time" aria-label="Конец" value={ns.end_time} onChange={(e) => { setNs({ ...ns, end_time: e.target.value }); setErr(""); }} />
                </td>
                <td><input className="input input-sm" type="number" min={1} max={100} aria-label="Макс. заказов" value={ns.capacity} onChange={(e) => { setNs({ ...ns, capacity: e.target.value }); setErr(""); }} /></td>
                <td colSpan={2}>
                  <button className="btn btn-xs" onClick={add}>Добавить интервал</button>
                  {err && <div className="field-err">{err}</div>}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Counter({ n, rec }: { n: number; rec: number }) {
  return <span className={`seo-count ${n > rec ? "over" : ""}`}>{n} / {rec}</span>;
}

/** Вкладка «Поиск (SEO)»: заголовки и описания страниц, коды подтверждения Яндекса и Google, карта сайта */
function SeoTab({ info, seo, errors, yandex, google, onPage, onCode }: {
  info: SeoInfo;
  seo: Record<string, SeoPage>;
  errors: V.Errors;
  yandex: string;
  google: string;
  onPage: (key: string, part: "title" | "description", v: string) => void;
  onCode: (key: string, v: string) => void;
}) {
  const site = (info.site_url || "").replace(/\/+$/, "");
  const host = site.replace(/^https?:\/\//, "");
  const pages = info.seo_page_list || [];
  return (
    <>
      <div className="notice small seo-help">
        <b>Как это работает.</b> <b>Заголовок</b> — синяя ссылка на сайт в выдаче Яндекса и Google, <b>описание</b> — одна-две строки под ней.
        Пустое поле — используется стандартный текст (он показан серым). Советы: начинайте заголовок с того, что ищут покупатели,
        например «Доставка цветов в Кондратово»; заголовок — до {TITLE_REC} символов, описание — до {DESC_REC}; у каждой страницы свой текст.
        Изменения поисковики увидят при следующем обходе сайта — обычно через 1–3 недели.
      </div>
      {pages.map((pg) => {
        // hasKey: ключ "constructor" есть у любого объекта JavaScript — берём только свои поля
        const own = (hasKey(seo, pg.key) && seo[pg.key]) || { title: "", description: "" };
        const def = (info.seo_defaults && hasKey(info.seo_defaults, pg.key) && info.seo_defaults[pg.key]) || { title: "", description: "" };
        const isTpl = pg.key === "product";
        const sample = (t: string) => (isTpl ? t.replace(/\{name\}/g, "Букет «Нежность»").replace(/\{price\}/g, "3 500 ₽").replace(/\{description\}/g, "Розы и эвкалипт в крафте.") : t);
        const title = own.title.trim() || def.title;
        const desc = own.description.trim() || def.description;
        return (
          <div className="card seo-card" key={pg.key} data-testid={`seo-${pg.key}`}>
            <div className="row-between" style={{ marginBottom: 12 }}>
              <div className="panel-title" style={{ margin: 0 }}>{pg.label}</div>
              {!isTpl && site ? (
                <a className="hint" href={site + pg.path} target="_blank" rel="noopener noreferrer">{host}{pg.path === "/" ? "" : pg.path} ↗</a>
              ) : (
                <span className="hint">{pg.path}</span>
              )}
            </div>
            {isTpl && (
              <p className="hint" style={{ margin: "-4px 0 12px" }}>
                Один шаблон для всех букетов и цветов. Вместо <code>{"{name}"}</code> подставится название, <code>{"{price}"}</code> — цена,{" "}
                <code>{"{description}"}</code> — краткое описание товара.
              </p>
            )}
            <div className="stack" style={{ gap: 12 }}>
              <Field label="Заголовок (title)" error={errors[`seo.${pg.key}.title`]}>
                <input className="input" maxLength={120} placeholder={def.title} value={own.title} onChange={(e) => onPage(pg.key, "title", e.target.value)} />
                {!isTpl && <Counter n={title.length} rec={TITLE_REC} />}
              </Field>
              <Field label="Описание (description)" error={errors[`seo.${pg.key}.description`]}>
                <textarea className="textarea" rows={2} maxLength={300} placeholder={def.description} value={own.description} onChange={(e) => onPage(pg.key, "description", e.target.value)} />
                {!isTpl && <Counter n={desc.length} rec={DESC_REC} />}
              </Field>
              <div className="seo-preview" aria-label="Как может выглядеть в поиске">
                <div className="seo-preview-url">{host || "ваш-сайт.ru"}{isTpl ? "/product/…" : pg.path === "/" ? "" : pg.path}</div>
                <div className="seo-preview-title">{sample(title)}</div>
                <div className="seo-preview-desc">{sample(desc)}</div>
              </div>
            </div>
          </div>
        );
      })}

      <div className="card">
        <div className="panel-title">Подтверждение прав на сайт</div>
        <p className="hint" style={{ marginTop: -6 }}>
          Нужно один раз, чтобы видеть статистику поиска и отправлять страницы на индексацию. Можно вставить сам код или весь тег{" "}
          <code>{"<meta …>"}</code> целиком — лишнее уберём.
        </p>
        <div className="grid-2">
          <div className="stack" style={{ gap: 8 }}>
            <Field label="Яндекс Вебмастер — код мета-тега" error={errors.yandex_verification}>
              <input className="input" maxLength={300} placeholder={'<meta name="yandex-verification" content="…" />'} value={yandex} onChange={(e) => onCode("yandex_verification", e.target.value)} />
            </Field>
            <ol className="hint seo-steps">
              <li>Откройте <a href="https://webmaster.yandex.ru" target="_blank" rel="noopener noreferrer">webmaster.yandex.ru</a> → «Добавить сайт» → {site || "адрес сайта"}.</li>
              <li>Способ проверки — «Мета-тег»: скопируйте тег и вставьте сюда.</li>
              <li>Нажмите «Сохранить» здесь, затем «Проверить» в Вебмастере.</li>
            </ol>
          </div>
          <div className="stack" style={{ gap: 8 }}>
            <Field label="Google Search Console — код тега HTML" error={errors.google_verification}>
              <input className="input" maxLength={300} placeholder={'<meta name="google-site-verification" content="…" />'} value={google} onChange={(e) => onCode("google_verification", e.target.value)} />
            </Field>
            <ol className="hint seo-steps">
              <li>Откройте <a href="https://search.google.com/search-console" target="_blank" rel="noopener noreferrer">Search Console</a> → «Ресурс с префиксом URL» → {site || "адрес сайта"}.</li>
              <li>Способ проверки — «Тег HTML»: скопируйте тег и вставьте сюда.</li>
              <li>Нажмите «Сохранить» здесь, затем «Подтвердить» в Search Console.</li>
            </ol>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="panel-title">Карта сайта</div>
        <p className="hint" style={{ margin: 0 }}>
          Список всех страниц и букетов обновляется сам:{" "}
          {site ? <a href={`${site}/sitemap.xml`} target="_blank" rel="noopener noreferrer"><code>{site}/sitemap.xml</code></a> : <code>/sitemap.xml</code>}.
          Добавьте этот адрес в Яндекс Вебмастере (Индексирование → Файлы Sitemap) и в Search Console (Файлы Sitemap).
        </p>
      </div>
    </>
  );
}
