"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AddressPicker, EMPTY_ADDRESS, addressProblem, type AddressValue } from "@/components/checkout/AddressPicker";
import { MessengerLogin } from "@/components/account/MessengerLogin";
import { useCart } from "@/components/CartProvider";
import { OrdersClosedNotice, ordersOpen } from "@/components/OrdersClosed";
import { useCustomer } from "@/components/CustomerProvider";
import { useShop } from "@/components/ShopProvider";
import { ApiError, newKey, request } from "@/lib/api";
import { loadContact, phoneHuman, rememberOrder, saveContact } from "@/lib/customer";
import { dateLong, money, todayIso } from "@/lib/format";
import { paymentHref } from "@/lib/payment";
import type { GeoAddress, OrderPublic, Slot, Zone } from "@/lib/types";
import * as V from "@/lib/validate";

const FIELDS = ["name", "phone", "email", "recipient_name", "recipient_phone", "zone_id", "address_hint", "apartment", "entrance", "floor", "card_text", "comment"];

type Ful = "delivery" | "pickup";
type Pay = "online" | "on_delivery";

export default function CheckoutPage() {
  const shop = useShop();
  const { cart, loading, reset } = useCart();
  const router = useRouter();
  const { me, ready: meReady, logout } = useCustomer();
  const idem = useRef(newKey());
  const [zones, setZones] = useState<Zone[]>([]);
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [f, setF] = useState({
    name: "", phone: "", email: "",
    fulfillment: "delivery" as Ful, apartment: "", entrance: "", floor: "",
    recipientSelf: true, recipient_name: "", recipient_phone: "",
    // как вручить — опции, привычные по крупным цветочным сервисам
    askAddress: false, zone_id: 0, address_hint: "", surprise: false, anonymous: false, photo_before: true,
    date: todayIso(), slot_id: 0, payment_method: "online" as Pay, card_text: "", comment: "", agree: true,
  });
  const [addr, setAddr] = useState<AddressValue>(EMPTY_ADDRESS);
  const [err, setErr] = useState("");
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  // Дата выбирается автоматически (ближайшая со свободным временем), пока покупатель не выбрал её сам
  const autoDate = useRef(true);
  const [dateNote, setDateNote] = useState("");
  const hpRef = useRef<HTMLInputElement>(null);
  const errRef = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLDivElement>(null);
  const [asideSeen, setAsideSeen] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => {
    setF((x) => ({ ...x, [k]: v }));
    setErrors((e) => (e[k as string] ? { ...e, [k as string]: "" } : e));
  };
  const fe = (k: string) => (errors[k] ? <span className="field-err" role="alert">{errors[k]}</span> : null);
  const cls = (k: string) => `input ${errors[k] ? "invalid" : ""}`;

  useEffect(() => {
    request<Zone[]>("/delivery/zones").then(setZones).catch(() => setZones([]));
  }, []);

  // Запоминаем покупателя: данные профиля (вход через Telegram/ВК) или контакты прошлого заказа на этом устройстве
  useEffect(() => {
    if (!meReady) return;
    const src = me ? { name: me.name, phone: phoneHuman(me.phone), email: me.email } : loadContact();
    if (!src) return;
    setF((x) => ({ ...x, name: x.name || src.name || "", phone: x.phone || src.phone || "", email: x.email || src.email || "" }));
  }, [me, meReady]);

  const last = me?.last_delivery || null;
  const [lastBusy, setLastBusy] = useState(false);
  async function applyLastAddress() {
    if (!last) return;
    setLastBusy(true);
    try {
      const r = await request<{ results: GeoAddress[] }>(`/delivery/geocode?q=${encodeURIComponent(last.address)}`);
      const hit = r.results.find((x) => x.house) || r.results[0];
      setAddr(hit ? { query: hit.address, lat: hit.lat, lon: hit.lon, token: hit.token, tokenFor: hit.address, zone: hit.zone, house: hit.house, checked: true } : { ...EMPTY_ADDRESS, query: last.address });
    } catch {
      setAddr({ ...EMPTY_ADDRESS, query: last.address });
    } finally {
      setLastBusy(false);
    }
    setF((x) => ({ ...x, apartment: x.apartment || last.apartment, entrance: x.entrance || last.entrance, floor: x.floor || last.floor }));
  }

  // при смене доставки/самовывоза снова ищем ближайшую дату (у самовывоза время на сегодня длиннее)
  useEffect(() => {
    if (autoDate.current) setF((x) => (x.date === todayIso() ? x : { ...x, date: todayIso() }));
  }, [f.fulfillment]);

  useEffect(() => {
    let alive = true;
    setSlots(null);
    request<Slot[]>(`/delivery/slots?date=${f.date}&fulfillment=${f.fulfillment}`)
      .then((s) => {
        if (!alive) return;
        const ahead = Math.round((new Date(f.date).getTime() - new Date(todayIso()).getTime()) / 86400000);
        if (autoDate.current && !s.some((sl) => sl.available) && ahead < Math.min(7, shop.max_order_days_ahead || 7)) {
          const next = todayIso(ahead + 1);
          if (ahead === 0) {
            setDateNote(f.fulfillment === "pickup"
              ? "На сегодня самовывоз уже недоступен — выбрали ближайшую дату."
              : "На сегодня доставка уже не успевает — выбрали ближайшую дату со свободным временем.");
          }
          setF((x) => ({ ...x, date: next }));
          return;
        }
        if (autoDate.current && ahead === 0) setDateNote("");
        setSlots(s);
        setF((x) => (s.some((sl) => sl.id === x.slot_id && sl.available) ? x : { ...x, slot_id: s.find((sl) => sl.available)?.id || 0 }));
      })
      .catch(() => alive && setSlots([]));
    return () => {
      alive = false;
    };
  }, [f.date, f.fulfillment, shop.max_order_days_ahead]);

  // нижняя панель «Итого» на телефоне прячется, когда видна карточка заказа
  useEffect(() => {
    const el = asideRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setAsideSeen(e.isIntersecting), { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, [loading, !!cart?.items.length]);

  // прокрутка к шагу формы (шапка сайта липкая — отступ задан в CSS через scroll-margin-top)
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  // ошибка без поля: показываем у нужного шага, остальные — в карточке «Ваш заказ»
  const [errAt, setErrAt] = useState("");
  function fail(msg: string, at = "") {
    setErr(msg);
    setErrAt(at);
    if (at) go(at);
    else requestAnimationFrame(() => errRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }));
  }

  const other = f.fulfillment === "delivery" && !f.recipientSelf;
  const askAddress = other && f.askAddress;
  const zone = askAddress ? zones.find((z) => z.id === f.zone_id) || null : addr.checked ? addr.zone : null;
  const itemsTotal = cart?.items_total || 0;
  const deliveryCost = f.fulfillment === "delivery" && zone ? (zone.free_from && itemsTotal >= zone.free_from ? 0 : zone.price) : 0;
  const hasCustom = !!cart?.items.some((i) => i.type === "custom_bouquet");
  // онлайн-касса может быть не подключена — тогда единственный способ оплаты «при получении»
  const online = shop.online_payment_enabled !== false;
  const codAllowed = !online || (shop.allow_cash_on_delivery && !hasCustom);
  const payMethod: Pay = !online ? "on_delivery" : codAllowed ? f.payment_method : "online";
  const addrErr = f.fulfillment !== "delivery" ? null : askAddress ? (f.zone_id ? null : "Выберите, куда примерно везти") : addressProblem(addr);
  const daysAhead = useMemo(() => Math.round((new Date(f.date).getTime() - new Date(todayIso()).getTime()) / 86400000), [f.date]);
  // как на сервере: предзаказ — дата позже, чем через preorder_threshold_days дней
  const isPreorder = daysAhead > shop.preorder_threshold_days;
  // флорист сначала подтверждает заказ, оплата — после подтверждения
  const needsConfirm = hasCustom || isPreorder || askAddress;
  const pickup = f.fulfillment === "pickup";
  const slot = slots?.find((x) => x.id === f.slot_id && x.available) || null;
  const total = itemsTotal + deliveryCost;
  const loginOn = shop.customer_login?.enabled !== false && !!(shop.customer_login?.telegram || shop.customer_login?.vk);

  // что ещё не заполнено — список в карточке «Ваш заказ» со ссылками на нужный шаг
  const todo: { id: string; label: string }[] = [];
  if (!pickup) {
    if (other && V.personName(f.recipient_name)) todo.push({ id: "co-where", label: "Имя получателя" });
    if (other && V.phone(f.recipient_phone)) todo.push({ id: "co-where", label: "Телефон получателя" });
    if (addrErr) todo.push({ id: "co-where", label: askAddress ? "Куда примерно везти" : "Адрес доставки" });
  }
  if (!slot) todo.push({ id: "co-when", label: pickup ? "Время получения" : "Время доставки" });
  if (V.personName(f.name)) todo.push({ id: "co-contacts", label: "Ваше имя" });
  if (V.phone(f.phone)) todo.push({ id: "co-contacts", label: "Ваш телефон" });
  const stepDone = (id: string) => !todo.some((t) => t.id === id);

  // «Что будет дальше» — простыми словами, зависит от выбранной оплаты и способа получения
  const when = slot ? `${dateLong(f.date)}, ${slot.label}` : dateLong(f.date);
  const next: string[] = [];
  if (payMethod === "online" && !needsConfirm) {
    next.push(`Оплатите картой или через СБП — сразу после кнопки ниже. Букет закрепим за вами на ${shop.online_reservation_minutes} мин.`);
  } else if (payMethod === "online") {
    next.push(askAddress ? "Флорист позвонит получателю и узнает адрес, не говоря, что это цветы." : hasCustom ? "Флорист проверит состав букета и подтвердит заказ." : "Флорист подтвердит предзаказ.");
    next.push("На странице заказа появится кнопка оплаты — картой или через СБП.");
  } else {
    next.push("Магазин позвонит и подтвердит заказ.");
    next.push(pickup ? "Оплата в магазине при получении." : "Оплата курьеру при получении.");
  }
  if (!pickup && f.photo_before) next.push("Пришлём фото букета перед отправкой.");
  next.push(pickup ? `Напишем, когда букет будет готов. Забрать: ${when}.` : `Курьер привезёт букет: ${when}.`);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setErrAt("");
    if (!cart) return;
    const errs = V.collect({
      name: V.personName(f.name, "Имя"),
      phone: V.phone(f.phone),
      email: V.email(f.email),
      recipient_name: other ? V.personName(f.recipient_name, "Имя получателя") : null,
      recipient_phone: other ? V.phone(f.recipient_phone, "Телефон получателя") : null,
      zone_id: askAddress && !f.zone_id ? "Выберите район или населённый пункт" : null,
      address_hint: askAddress ? V.text(f.address_hint, "Что известно об адресе", { max: 120 }) : null,
      apartment: f.fulfillment === "delivery" && !askAddress ? V.text(f.apartment, "Квартира", { max: 20 }) : null,
      entrance: f.fulfillment === "delivery" && !askAddress ? V.text(f.entrance, "Подъезд", { max: 10 }) : null,
      floor: f.fulfillment === "delivery" && !askAddress ? V.int(f.floor, "Этаж", { required: false, min: -5, max: 100 }) : null,
      card_text: V.text(f.card_text, "Текст открытки", { max: 300 }),
      comment: V.text(f.comment, "Комментарий", { max: 1000 }),
    });
    setErrors(errs);
    if (V.hasErrors(errs)) {
      setErr("Проверьте выделенные поля");
      const first = FIELDS.find((k) => errs[k]);
      if (first) document.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
      return;
    }
    if (addrErr) return fail(addrErr, "co-where");
    if (!slot) return fail(pickup ? "Выберите время получения" : "Выберите время доставки", "co-when");
    setBusy(true);
    try {
      const body = {
        cart_token: cart.token,
        customer: { name: f.name.trim(), phone: f.phone, email: f.email.trim() },
        fulfillment: f.fulfillment,
        date: f.date,
        slot_id: f.slot_id,
        payment_method: payMethod,
        delivery:
          f.fulfillment !== "delivery"
            ? undefined
            : askAddress
              ? { ask_recipient: true, zone_id: f.zone_id, address_hint: f.address_hint.trim(), anonymous: f.anonymous }
              : {
                  address: addr.query.trim(),
                  lat: addr.lat,
                  lon: addr.lon,
                  address_token: addr.token && addr.tokenFor === addr.query ? addr.token : null,
                  apartment: f.apartment,
                  entrance: f.entrance,
                  floor: f.floor,
                  surprise: other && f.surprise,
                  anonymous: other && f.anonymous,
                },
        photo_before: f.fulfillment === "delivery" && f.photo_before,
        recipient: f.fulfillment === "delivery" && !f.recipientSelf ? { name: f.recipient_name, phone: f.recipient_phone } : undefined,
        card_text: f.card_text,
        comment: f.comment,
        website: hpRef.current?.value || "",
      };
      const order = await request<OrderPublic>("/checkout", { body, headers: { "Idempotency-Key": idem.current } });
      saveContact({ name: f.name.trim(), phone: f.phone, email: f.email.trim() });
      rememberOrder(order.token, order.number);
      reset();
      if (order.payment_url) {
        const pay = paymentHref(order.payment_url);
        if (pay.internal) router.push(pay.href);
        else window.location.href = pay.href; // форма оплаты кассы на её домене
      } else router.push(`/order/${order.token}?new=1`);
    } catch (e2) {
      fail(V.serverError(e2, setErrors, FIELDS) || "Не удалось оформить заказ");
      idem.current = newKey();
      setBusy(false);
    }
  }

  if (loading) return <div className="container section"><div className="skeleton" style={{ height: 400 }} /></div>;
  if (!ordersOpen(shop))
    return (
      <div className="container section">
        <h1 style={{ marginTop: 0 }}>Оформление заказа</h1>
        <OrdersClosedNotice s={shop} />
        <p style={{ marginTop: 16 }}>
          <Link href="/" style={{ color: "var(--green)", fontWeight: 600 }}>На главную</Link>
        </p>
      </div>
    );
  if (!cart || !cart.items.length)
    return (
      <div className="container section">
        <div className="card empty">
          Корзина пуста. <Link href="/bouquets" style={{ color: "var(--green)", fontWeight: 600 }}>Перейти в каталог</Link>
        </div>
      </div>
    );

  // номера шагов: при самовывозе шага «Кому и куда» нет
  let n = 0;
  const num = () => ++n;
  const btnText = payMethod === "online" && !needsConfirm ? "Перейти к оплате" : "Оформить заказ";

  return (
    <div className="container">
      <div className="page-head co-head">
        <h1>Оформление заказа</h1>
        <p className="muted">Заполните шаги по порядку. Звёздочка * — обязательное поле, остальное по желанию.</p>
      </div>
      <form className="cart-grid" onSubmit={submit} noValidate>
        <div className="stack">
          {meReady && me ? (
            <section className="card signed-card">
              <div className="signed-row">
                <span className={`signed-badge ${me.channels[0]?.channel || "telegram"}`} aria-hidden>
                  {(me.name || "?").slice(0, 1).toUpperCase()}
                </span>
                <div className="grow">
                  <b>{me.name || "Покупатель"}</b>
                  <div className="small muted">
                    Вы вошли через {me.channels.map((c) => c.label + (c.username ? ` (@${c.username})` : "")).join(" и ") || "мессенджер"}.
                    {" "}Статус заказа придёт в {me.channels.map((c) => c.label).join(" и ") || "мессенджер"}.
                  </div>
                </div>
                <button type="button" className="btn btn-sm btn-quiet" onClick={logout}>Выйти</button>
              </div>
            </section>
          ) : meReady && loginOn ? (
            <details className="card signin-card co-signin">
              <summary>
                <span>
                  <b>Уже покупали у нас? Войдите через Telegram или ВКонтакте</b>
                  <span className="small muted">Необязательно: подставим ваши данные и пришлём статус заказа в мессенджер</span>
                </span>
              </summary>
              <div className="co-signin-body">
                <MessengerLogin />
                <p className="tiny muted" style={{ margin: "10px 0 0" }}>Можно оформить и без входа — статус будет на странице заказа.</p>
              </div>
            </details>
          ) : null}

          <Step id="co-how" n={num()} title="Как получить букет" done>
            <div className="radio-cards">
              <button type="button" className={`radio-card ${!pickup ? "on" : ""}`} aria-pressed={!pickup} onClick={() => set("fulfillment", "delivery")}>
                <b>Доставка курьером</b>
                <span>привезём в выбранное время</span>
              </button>
              <button type="button" className={`radio-card ${pickup ? "on" : ""}`} aria-pressed={pickup} onClick={() => set("fulfillment", "pickup")}>
                <b>Самовывоз</b>
                <span>бесплатно, {shop.address || "из магазина"}</span>
              </button>
            </div>
            {pickup && (
              <div className="notice green small" style={{ marginTop: 16 }}>
                Заберите заказ по адресу: <b>{shop.address}</b>. {shop.working_hours}. Мы напишем, когда букет будет готов.
              </div>
            )}
          </Step>

          {!pickup && (
            <Step id="co-where" n={num()} title="Кому и куда доставить" done={stepDone("co-where")}>
              <div className="form-grid">
                <div className="full">
                  <div className="label" style={{ marginBottom: 8 }}>Кому доставить</div>
                  <div className="radio-cards" data-testid="recipient-choice">
                    <button type="button" className={`radio-card ${f.recipientSelf ? "on" : ""}`} aria-pressed={f.recipientSelf} onClick={() => set("recipientSelf", true)}>
                      <b>Мне</b>
                      <span>курьер позвонит вам</span>
                    </button>
                    <button type="button" className={`radio-card ${!f.recipientSelf ? "on" : ""}`} aria-pressed={!f.recipientSelf} onClick={() => set("recipientSelf", false)}>
                      <b>Другому человеку</b>
                      <span>в подарок: можно сюрпризом или анонимно</span>
                    </button>
                  </div>
                </div>
                {other && (
                  <>
                    <label className="field">
                      <span>Имя получателя *</span>
                      <input className={cls("recipient_name")} data-field="recipient_name" required maxLength={80} value={f.recipient_name} onChange={(e) => set("recipient_name", e.target.value)} />
                      {fe("recipient_name")}
                    </label>
                    <label className="field">
                      <span>Телефон получателя *</span>
                      <input className={cls("recipient_phone")} data-field="recipient_phone" required type="tel" maxLength={20} placeholder="+7 900 000-00-00" value={f.recipient_phone} onChange={(e) => set("recipient_phone", e.target.value)} />
                      {fe("recipient_phone")}
                    </label>
                    <label className={`option full ${f.askAddress ? "on" : ""}`}>
                      <input type="checkbox" data-testid="ask-address" checked={f.askAddress} onChange={(e) => setF((x) => ({ ...x, askAddress: e.target.checked, surprise: e.target.checked ? false : x.surprise }))} />
                      <span>
                        <b>Не знаю адрес — узнайте у получателя</b>
                        <span>Флорист позвонит получателю и уточнит, куда привезти, не говоря, что это цветы. Оплата — после этого звонка.</span>
                      </span>
                    </label>
                  </>
                )}
                {askAddress ? (
                  <>
                    <label className="field">
                      <span>Куда примерно везти *</span>
                      <select className={cls("zone_id")} data-field="zone_id" value={f.zone_id || ""} onChange={(e) => set("zone_id", Number(e.target.value) || 0)}>
                        <option value="">Район или населённый пункт</option>
                        {zones.map((z) => (
                          <option key={z.id} value={z.id}>{z.name} — {z.free_from && itemsTotal >= z.free_from ? "бесплатно" : money(z.price)}</option>
                        ))}
                      </select>
                      {fe("zone_id") || <span className="hint">Стоимость доставки — по этой зоне</span>}
                    </label>
                    <label className="field">
                      <span>Что известно об адресе</span>
                      <input className={cls("address_hint")} data-field="address_hint" maxLength={120} placeholder="Например: работает в центре Перми" value={f.address_hint} onChange={(e) => set("address_hint", e.target.value)} />
                      {fe("address_hint")}
                    </label>
                  </>
                ) : (
                  <>
                    <div className="full label" style={{ marginBottom: -4 }}>Адрес доставки *</div>
                    {last && !addr.query && (
                      <div className="full">
                        <button type="button" className="chip last-addr" onClick={applyLastAddress} disabled={lastBusy}>
                          <span aria-hidden>↺</span> {lastBusy ? "Проверяем адрес…" : `Как в прошлый раз: ${last.address}${last.apartment ? `, кв. ${last.apartment}` : ""}`}
                        </button>
                      </div>
                    )}
                    <div className="full">
                      <AddressPicker zones={zones} value={addr} onChange={setAddr} itemsTotal={itemsTotal} />
                    </div>
                    <label className="field">
                      <span>Квартира / офис</span>
                      <input className={cls("apartment")} data-field="apartment" maxLength={20} value={f.apartment} onChange={(e) => set("apartment", e.target.value)} />
                      {fe("apartment")}
                    </label>
                    <div className="form-grid" style={{ gap: 12 }}>
                      <label className="field">
                        <span>Подъезд</span>
                        <input className={cls("entrance")} data-field="entrance" maxLength={10} value={f.entrance} onChange={(e) => set("entrance", e.target.value)} />
                        {fe("entrance")}
                      </label>
                      <label className="field">
                        <span>Этаж</span>
                        <input className={cls("floor")} data-field="floor" inputMode="numeric" maxLength={3} value={f.floor} onChange={(e) => set("floor", e.target.value)} />
                        {fe("floor")}
                      </label>
                    </div>
                  </>
                )}
                <div className="full">
                  <div className="label" style={{ margin: "4px 0 8px" }}>Пожелания к вручению</div>
                  <div className="options">
                    {other && !askAddress && (
                      <label className={`option ${f.surprise ? "on" : ""}`}>
                        <input type="checkbox" checked={f.surprise} onChange={(e) => set("surprise", e.target.checked)} />
                        <span>
                          <b>Сюрприз: не звонить заранее</b>
                          <span>Курьер позвонит получателю, только когда будет у двери. Если никого не окажется дома, свяжемся с вами.</span>
                        </span>
                      </label>
                    )}
                    {other && (
                      <label className={`option ${f.anonymous ? "on" : ""}`}>
                        <input type="checkbox" checked={f.anonymous} onChange={(e) => set("anonymous", e.target.checked)} />
                        <span>
                          <b>Не говорить, от кого букет</b>
                          <span>Курьер не назовёт отправителя. Не подписывайте открытку, если хотите остаться инкогнито.</span>
                        </span>
                      </label>
                    )}
                    <label className={`option ${f.photo_before ? "on" : ""}`}>
                      <input type="checkbox" data-testid="photo-before" checked={f.photo_before} onChange={(e) => set("photo_before", e.target.checked)} />
                      <span>
                        <b>Прислать фото букета перед отправкой</b>
                        <span>Фото появится на странице заказа{me ? " и придёт в мессенджер" : ""} до того, как курьер выедет.</span>
                      </span>
                    </label>
                  </div>
                </div>
              </div>
              {errAt === "co-where" && addrErr && <div className="notice red small" style={{ marginTop: 12 }} role="alert">{addrErr}</div>}
            </Step>
          )}

          <Step id="co-when" n={num()} title={pickup ? "Когда заберёте" : "Когда доставить"} done={stepDone("co-when")}>
            <div className="form-grid">
              <label className="field">
                <span>Дата</span>
                <input className="input" type="date" value={f.date} min={todayIso()} max={todayIso(shop.max_order_days_ahead || 30)} onChange={(e) => {
                  if (!e.target.value) return;
                  autoDate.current = false;
                  setDateNote("");
                  set("date", e.target.value);
                }} />
              </label>
              <div className="field">
                <span>&nbsp;</span>
                <div className="hint" style={{ paddingTop: 10 }}>
                  {dateLong(f.date)}
                  {isPreorder && " · предзаказ: флорист подтвердит заказ и соберёт его к выбранной дате"}
                </div>
              </div>
            </div>
            {dateNote && <div className="notice small" style={{ marginTop: 12 }}>{dateNote}</div>}
            <div className="label" style={{ margin: "16px 0 8px" }}>Время {pickup ? "получения" : "доставки"} *</div>
            {slots === null ? (
              <div className="skeleton" style={{ height: 56 }} />
            ) : slots.length ? (
              <div className="slots">
                {slots.map((sl) => (
                  <button type="button" key={sl.id} disabled={!sl.available} aria-pressed={f.slot_id === sl.id} className={`slot ${f.slot_id === sl.id ? "on" : ""}`} onClick={() => set("slot_id", sl.id)} title={sl.reason}>
                    <b>{sl.label}</b>
                    <span>{sl.available ? (sl.remaining <= 2 ? `осталось мест: ${sl.remaining}` : "свободно") : sl.reason || "недоступно"}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="notice amber small">На эту дату нет свободного времени. Выберите другую дату.</div>
            )}
            {errAt === "co-when" && !slot && <div className="notice red small" style={{ marginTop: 12 }} role="alert">{err}</div>}
          </Step>

          <Step id="co-contacts" n={num()} title="Ваши контакты" done={stepDone("co-contacts")} hint="Позвоним или напишем, если нужно что-то уточнить по заказу.">
            <div className="form-grid">
              <label className="field">
                <span>Имя *</span>
                <input className={cls("name")} data-field="name" required maxLength={80} value={f.name} onChange={(e) => set("name", e.target.value)} autoComplete="name" />
                {fe("name")}
              </label>
              <label className="field">
                <span>Телефон *</span>
                <input className={cls("phone")} data-field="phone" required type="tel" maxLength={20} placeholder="+7 900 000-00-00" value={f.phone} onChange={(e) => set("phone", e.target.value)} autoComplete="tel" />
                {fe("phone")}
              </label>
              <label className="field full">
                <span>E-mail</span>
                <input className={cls("email")} data-field="email" type="email" maxLength={120} value={f.email} onChange={(e) => set("email", e.target.value)} autoComplete="email" />
                {fe("email") || <span className="hint">Необязательно. Ссылка на заказ появится на следующем шаге</span>}
              </label>
            </div>
          </Step>

          <Step id="co-pay" n={num()} title="Оплата" done>
            <div className="radio-cards">
              {online && (
                <button type="button" className={`radio-card ${payMethod === "online" ? "on" : ""}`} aria-pressed={payMethod === "online"} onClick={() => set("payment_method", "online")}>
                  <b>Онлайн картой</b>
                  <span>{shop.payment_test_mode ? "тестовая оплата, деньги не списываются" : "картой или через СБП"}</span>
                </button>
              )}
              {codAllowed && (
                <button type="button" className={`radio-card ${payMethod === "on_delivery" ? "on" : ""}`} aria-pressed={payMethod === "on_delivery"} onClick={() => set("payment_method", "on_delivery")}>
                  <b>При получении</b>
                  <span>{online ? "после подтверждения магазином" : "наличными или переводом курьеру / в магазине"}</span>
                </button>
              )}
            </div>
            <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
              {payMethod === "on_delivery"
                ? "Магазин подтвердит заказ по телефону, после этого букет закрепляется за вами."
                : needsConfirm
                  ? `${hasCustom ? "Индивидуальный букет оплачивается только онлайн. " : ""}Сначала флорист ${askAddress ? "узнает адрес у получателя" : hasCustom ? "подтвердит состав" : "подтвердит предзаказ"}, затем на странице заказа появится кнопка оплаты.`
                  : `Товары резервируются на ${shop.online_reservation_minutes} мин, оплатите заказ за это время.`}
            </p>
          </Step>

          <Step id="co-card" n={num()} title="Открытка и комментарий" optional done={!!(f.card_text.trim() || f.comment.trim())}>
            <div className="form-grid">
              <label className="field">
                <span>Текст для открытки</span>
                <textarea className={`textarea ${errors.card_text ? "invalid" : ""}`} data-field="card_text" maxLength={300} value={f.card_text} onChange={(e) => set("card_text", e.target.value)} placeholder="Например: С днём рождения! Люблю тебя" />
                {fe("card_text") || <span className="hint">Открытка бесплатно · {f.card_text.length}/300</span>}
              </label>
              <label className="field">
                <span>Комментарий к заказу</span>
                <textarea className={`textarea ${errors.comment ? "invalid" : ""}`} data-field="comment" maxLength={1000} value={f.comment} onChange={(e) => set("comment", e.target.value)} placeholder="Например: домофон не работает, оставить у консьержа" />
                {fe("comment")}
              </label>
            </div>
          </Step>
        </div>

        <aside className="sticky-aside">
          <div className="card" ref={asideRef} id="co-summary">
            <h3>Ваш заказ</h3>
            {cart.items.map((i) => (
              <div className="sum-row" key={i.id}>
                <span>
                  {i.name} <span className="muted">× {i.quantity}</span>
                </span>
                <span className="nowrap">{money(i.total)}</span>
              </div>
            ))}
            <hr className="divider" />
            <div className="sum-row">
              <span>Товары</span>
              <span>{money(itemsTotal)}</span>
            </div>
            <div className="sum-row">
              <span>{pickup ? "Самовывоз" : "Доставка"}</span>
              <span>{pickup ? "бесплатно" : zone ? (deliveryCost ? money(deliveryCost) : "бесплатно") : askAddress ? "выберите зону" : "укажите адрес"}</span>
            </div>
            <div className="sum-row total">
              <span>Итого</span>
              <span>{money(total)}</span>
            </div>
            {!pickup && (zone?.free_from ?? shop.free_delivery_from) && itemsTotal < (zone?.free_from ?? shop.free_delivery_from ?? 0) ? (
              <div className="hint">
                Доставка бесплатно от {money((zone?.free_from ?? shop.free_delivery_from) as number)}, добавьте ещё на {money(((zone?.free_from ?? shop.free_delivery_from) as number) - itemsTotal)}
              </div>
            ) : null}

            {todo.length ? (
              <div className="co-todo" data-testid="co-todo">
                <div className="co-todo-title">Осталось заполнить:</div>
                <ul>
                  {todo.map((t) => (
                    <li key={t.label}>
                      <button type="button" onClick={() => go(t.id)}>{t.label}</button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="co-ready" data-testid="co-ready">✓ Всё заполнено — можно оформлять</div>
            )}

            <div className="co-next">
              <div className="co-todo-title">Что будет дальше</div>
              <ol>
                {next.map((t) => <li key={t}>{t}</li>)}
              </ol>
            </div>

            <label className="checkbox small" style={{ marginTop: 16 }}>
              <input type="checkbox" checked={f.agree} onChange={(e) => set("agree", e.target.checked)} /> Согласен на обработку персональных данных
            </label>
            {err && !errAt && <div className="notice red small" style={{ marginTop: 12 }} ref={errRef} role="alert">{err}</div>}
            {addrErr && addr.lat != null && <div className="hint" style={{ marginTop: 12 }}>{addrErr}</div>}
            <button className="btn btn-block btn-lg" style={{ marginTop: 16 }} disabled={busy || !f.agree || !!cart.problems.length || (!!addrErr && addr.lat != null)}>
              {busy ? "Оформляем…" : pickup || zone ? `${btnText} · ${money(total)}` : btnText}
            </button>
            {!f.agree && <div className="hint" style={{ marginTop: 8 }}>Отметьте согласие на обработку данных, чтобы оформить заказ</div>}
            <p className="tiny muted" style={{ marginTop: 12, marginBottom: 0 }}>Итоговая сумма и наличие проверяются на сервере в момент оформления.</p>
          </div>
        </aside>
        {/* ловушка для спам-ботов: поле не видно людям и не заполняется автозаполнением */}
        <div className="hp-field" aria-hidden="true">
          <label>Сайт <input ref={hpRef} type="text" name="website" tabIndex={-1} autoComplete="off" defaultValue="" /></label>
        </div>
        <div className={`co-mbar ${asideSeen ? "hide" : ""}`}>
          <div>
            <div className="tiny muted">
              {todo.length ? `Осталось заполнить: ${todo.length}` : "Всё заполнено"} · итого{!pickup && !zone ? " без доставки" : ""}
            </div>
            <b className="co-mbar-total">{money(total)}</b>
          </div>
          <button type="button" className="btn" onClick={() => asideRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            К оформлению ↓
          </button>
        </div>
      </form>
    </div>
  );
}

/** Шаг оформления: номер (или ✓, когда всё нужное заполнено), заголовок, подсказка */
function Step({ id, n, title, hint, done, optional, children }: { id: string; n: number; title: string; hint?: string; done?: boolean; optional?: boolean; children: React.ReactNode }) {
  return (
    <section className="card co-step" id={id} aria-labelledby={`${id}-t`}>
      <div className="co-step-head">
        <span className={`co-num ${done ? "done" : ""}`} aria-hidden>{done ? "✓" : n}</span>
        <div>
          <h2 className="co-step-title" id={`${id}-t`}>
            <span className="sr-only">Шаг {n}. </span>{title}
            {optional && <span className="co-opt"> · необязательно</span>}
          </h2>
          {hint && <p className="small muted co-step-hint">{hint}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}
