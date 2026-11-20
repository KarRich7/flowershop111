"use client";
// «Букет по фото»: покупатель выбирает только цветы, упаковку и ленту — по фотографиям, без эскиза.
// Форму, высоту и расстановку флорист делает на своё усмотрение (в составе заказа — florist_choice).
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, request } from "@/lib/api";
import { money, plural } from "@/lib/format";
import type { Composition, ConstructorOptions, Product, Quote } from "@/lib/types";
import { KindIcon, kindOf } from "./bouquet/draw";
import { useCart } from "./CartProvider";
import { ordersOpen } from "./OrdersClosed";
import { useShop } from "./ShopProvider";
import { NoneTile, Tile } from "./ConstructorView";
import { HandIcon, MinusIcon, PlusIcon } from "./Icons";
import { useToast } from "./Toast";

const DRAFT_KEY = "cu_bouquet_photo_v1";

export function PhotoConstructorView() {
  const [opts, setOpts] = useState<ConstructorOptions | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [qty, setQty] = useState<Record<number, number>>({});
  const [packaging, setPackaging] = useState<number | null>(null);
  const [ribbon, setRibbon] = useState<number | null>(null);
  const [species, setSpecies] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteErr, setQuoteErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);
  const [ready, setReady] = useState(false);
  const { addCustom } = useCart();
  const shopNow = useShop();
  const closed = !ordersOpen(shopNow); // владелец закрыл приём заказов — собрать эскиз можно, купить нельзя
  const toast = useToast();
  const seq = useRef(0);

  useEffect(() => {
    request<ConstructorOptions>("/constructor/options").then(setOpts).catch((e) => setLoadErr(e.message));
  }, []);

  // черновик переживает перезагрузку; остатки и лимит проверяем заново
  useEffect(() => {
    if (!opts) return;
    let d: { qty?: Record<string, number>; packaging?: number | null; ribbon?: number | null } = {};
    try {
      d = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
    } catch {}
    const next: Record<number, number> = {};
    let total = 0;
    for (const f of opts.flowers) {
      const want = Math.min(Math.floor(Number(d.qty?.[f.inventory_item_id]) || 0), f.available, opts.max_stems - total);
      if (want > 0) {
        next[f.inventory_item_id] = want;
        total += want;
      }
    }
    setQty(next);
    const ok = (id: number | null | undefined, list: Product[]) => (id && list.some((p) => p.inventory_item_id === id && p.available > 0) ? id : null);
    const firstPack = opts.packaging.find((p) => p.available > 0)?.inventory_item_id ?? null;
    setPackaging("packaging" in d && d.packaging == null ? null : ok(d.packaging, opts.packaging) ?? firstPack);
    setRibbon(ok(d.ribbon, opts.ribbons));
    setReady(true);
  }, [opts]);

  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ qty, packaging, ribbon }));
      } catch {}
    }, 300);
    return () => clearTimeout(t);
  }, [ready, qty, packaging, ribbon]);

  const stems = Object.values(qty).reduce((a, b) => a + b, 0);
  const composition: Composition = useMemo(
    () => ({
      flowers: Object.entries(qty)
        .filter(([, n]) => n > 0)
        .map(([id, n]) => ({ item_id: Number(id), quantity: n })),
      greenery: [],
      packaging_id: packaging,
      ribbon_id: ribbon,
      card_id: null,
      card_text: "",
      wishes: "",
      layout: [],
      florist_choice: true,
    }),
    [qty, packaging, ribbon],
  );
  const quoteKey = JSON.stringify(composition);
  const minStems = opts?.min_stems ?? 1;

  useEffect(() => {
    if (!ready) return;
    setAdded(false);
    const body = JSON.parse(quoteKey) as Composition;
    const n = body.flowers.reduce((a, r) => a + r.quantity, 0);
    if (n < minStems) {
      seq.current++;
      setQuote(null);
      setQuoteErr("");
      return;
    }
    const my = ++seq.current;
    const t = setTimeout(async () => {
      try {
        const q = await request<Quote>("/constructor/quote", { body: { composition: body, quantity: 1 } });
        if (my === seq.current) {
          setQuote(q);
          setQuoteErr("");
        }
      } catch (e) {
        if (my === seq.current) {
          setQuote(null);
          setQuoteErr(e instanceof ApiError ? e.message : "Не удалось рассчитать");
        }
      }
    }, 250);
    return () => clearTimeout(t);
  }, [quoteKey, ready, minStems]);

  if (loadErr) return <div className="notice red">Конструктор недоступен: {loadErr}</div>;
  if (!opts) return <div className="skeleton" style={{ height: 480 }} />;

  const max = opts.max_stems;
  const full = stems >= max;
  const need = Math.max(0, opts.min_stems - stems);
  const setN = (p: Product, n: number) => {
    const cur = qty[p.inventory_item_id] || 0;
    const room = cur + (max - stems);
    if (n > cur && n > room) {
      toast(`В букете не больше ${max} ${plural(max, "цветка", "цветков", "цветков")}`, "err");
      return;
    }
    if (n > p.available) {
      toast(`${p.name}: в наличии только ${p.available} шт.`, "err");
      return;
    }
    setQty((q) => {
      const next = { ...q };
      if (n > 0) next[p.inventory_item_id] = n;
      else delete next[p.inventory_item_id];
      return next;
    });
  };

  const speciesList = Array.from(new Set(opts.flowers.map((f) => f.species || f.category))).filter(Boolean);
  const flowerList = opts.flowers.filter((f) => !species || (f.species || f.category) === species);
  const picked = opts.flowers.filter((f) => qty[f.inventory_item_id]);
  const packItem = opts.packaging.find((p) => p.inventory_item_id === packaging) || null;
  const ribbonItem = opts.ribbons.find((p) => p.inventory_item_id === ribbon) || null;
  const canBuy = !!quote && !busy && !need && !closed;

  let status = "Оплата онлайн при оформлении";
  if (!stems) status = `От ${opts.min_stems} до ${max} цветков`;
  else if (need) status = `Добавьте ещё ${need} ${plural(need, "цветок", "цветка", "цветков")}`;
  else if (quoteErr) status = quoteErr;
  if (closed) status = "Приём заказов временно закрыт";

  async function addToCart() {
    setBusy(true);
    try {
      await addCustom(composition, 1);
      setAdded(true);
      toast("Букет добавлен в корзину", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Не удалось добавить", "err");
    } finally {
      setBusy(false);
    }
  }

  const buy = added ? (
    <Link href="/cart" className="btn btn-outline">Открыть корзину</Link>
  ) : (
    <button className="btn" disabled={!canBuy} onClick={addToCart}>{busy ? "Добавляем…" : "В корзину"}</button>
  );

  return (
    <div className="pc">
      <div className="pc-main">
        <section className="pc-sec" aria-labelledby="pc-h-fl">
          <div className="pc-sec-head">
            <h2 id="pc-h-fl" className="pc-h"><span className="pc-step">1</span>Цветы</h2>
            <span className={`pc-count ${full ? "full" : ""}`} aria-live="polite">
              <b className="num">{stems}</b> из <span className="num">{max}</span>
            </span>
          </div>
          <div className="chips scroll bq-chips">
            <button className={`chip ${!species ? "on" : ""}`} onClick={() => setSpecies("")}>Все</button>
            {speciesList.map((s) => (
              <button key={s} className={`chip ${species === s ? "on" : ""}`} onClick={() => setSpecies(s)}>{s}</button>
            ))}
          </div>
          {full && (
            <p className="notice amber bq-limit" role="status">
              В букете уже {max} {plural(max, "цветок", "цветка", "цветков")} — это максимум. Нужен букет больше — выберите готовый в каталоге или позвоните нам.
            </p>
          )}
          <div className="pc-grid">
            {flowerList.map((f) => (
              <FlowerCard key={f.id} p={f} n={qty[f.inventory_item_id] || 0} full={full} onSet={(n) => setN(f, n)} />
            ))}
          </div>
        </section>

        <section className="pc-sec" aria-labelledby="pc-h-wrap">
          <div className="pc-sec-head">
            <h2 id="pc-h-wrap" className="pc-h"><span className="pc-step">2</span>Бумага и упаковка</h2>
          </div>
          <div className="bq-tiles pc-tiles">
            <NoneTile on={!packaging} label="Без упаковки" onPick={() => setPackaging(null)} />
            {opts.packaging.map((p) => (
              <Tile key={p.id} p={p} on={packaging === p.inventory_item_id} onPick={() => setPackaging(p.inventory_item_id)} />
            ))}
          </div>
        </section>

        <section className="pc-sec" aria-labelledby="pc-h-rb">
          <div className="pc-sec-head">
            <h2 id="pc-h-rb" className="pc-h"><span className="pc-step">3</span>Лента</h2>
          </div>
          <div className="bq-tiles pc-tiles">
            <NoneTile on={!ribbon} label="Без ленты" onPick={() => setRibbon(null)} />
            {opts.ribbons.map((p) => (
              <Tile key={p.id} p={p} on={ribbon === p.inventory_item_id} onPick={() => setRibbon(p.inventory_item_id)} />
            ))}
          </div>
        </section>
      </div>

      <aside className="pc-side" aria-label="Ваш букет">
        <div className="pc-card">
          <h3 className="pc-side-h">Ваш букет</h3>
          <div className="pc-florist">
            <span className="pc-florist-ic" aria-hidden><HandIcon /></span>
            <div>
              <b>Оформление — на усмотрение флориста</b>
              <p>Флорист сам подберёт форму, высоту и расстановку под выбранные цветы и упаковку.</p>
            </div>
          </div>
          {picked.length ? (
            <ul className="pc-thumbs" aria-label="Выбранные цветы">
              {picked.map((f) => (
                <li key={f.id} title={`${f.name} × ${qty[f.inventory_item_id]}`}>
                  <Thumb p={f} />
                  <span className="pc-thumb-n num">{qty[f.inventory_item_id]}</span>
                </li>
              ))}
              {packItem && <li className="aux" title={packItem.name}><Thumb p={packItem} /></li>}
              {ribbonItem && <li className="aux" title={ribbonItem.name}><Thumb p={ribbonItem} /></li>}
            </ul>
          ) : (
            <p className="muted small pc-empty">Выберите цветы — от {opts.min_stems} до {max} штук, затем бумагу и ленту.</p>
          )}
          <div className="pc-progress" aria-hidden>
            <span style={{ width: `${Math.min(100, (stems / max) * 100)}%` }} />
          </div>
          {quote && (
            <div className="bq-lines pc-lines">
              {quote.lines.map((l) => (
                <div className="sum-row" key={l.item_id}>
                  <span>{l.name} {l.quantity > 1 ? <span className="muted">× {l.quantity}</span> : null}</span>
                  <span className="num nowrap">{money(l.total)}</span>
                </div>
              ))}
              <div className="sum-row">
                <span>Работа флориста</span>
                <span className="num">{money(quote.florist_fee)}</span>
              </div>
            </div>
          )}
          <div className="bq-bar pc-bar">
            <div className="bq-bar-sum">
              <div className="bq-total num">{quote ? money(quote.total) : money(0)}</div>
              <div className="tiny muted">{status}</div>
            </div>
            {buy}
          </div>
        </div>
        <p className="tiny muted bq-foot">
          Индивидуальный букет оплачивается только онлайн. Цена фиксируется при оформлении; если какого-то цветка не окажется, флорист предложит замену.
        </p>
      </aside>

      <div className="pc-mbar" role="region" aria-label="Итог">
        <div className="bq-bar-sum">
          <div className="bq-total num">{quote ? money(quote.total) : money(0)}</div>
          <div className="tiny muted"><span className="num">{stems}</span> из <span className="num">{max}</span> · {need ? status : "оформит флорист"}</div>
        </div>
        {buy}
      </div>
    </div>
  );
}

function Thumb({ p }: { p: Product }) {
  const src = p.image || p.constructor_image;
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt="" loading="lazy" /> : <span className="swatch" style={{ background: p.color_hex || "#ddd" }} />;
}

function FlowerCard({ p, n, full, onSet }: { p: Product; n: number; full: boolean; onSet: (n: number) => void }) {
  const out = p.available <= 0;
  const src = p.image || p.constructor_image;
  return (
    <div className={`pc-item ${n ? "on" : ""} ${out ? "dis" : ""}`} data-item={p.inventory_item_id}>
      <div className="pc-img">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={p.name} loading="lazy" draggable={false} />
        ) : (
          <KindIcon kind={kindOf({ species: p.species, name: p.name, type: p.type })} color={p.color_hex || "#d9a7b0"} size={64} />
        )}
        {n > 0 && <span className="pc-badge num">× {n}</span>}
      </div>
      <div className="pc-body">
        <div className="pc-name">{p.name}</div>
        <div className="pc-meta">
          <span className="num">{money(p.price)}</span>
          <span>{out ? "нет в наличии" : <>в наличии <span className="num">{p.available}</span></>}</span>
        </div>
        {n === 0 ? (
          <button type="button" className="btn btn-outline btn-sm pc-add" disabled={out || full} onClick={() => onSet(1)} aria-label={`Добавить: ${p.name}`}>
            <PlusIcon /> {out ? "Нет в наличии" : "Добавить"}
          </button>
        ) : (
          <div className="stepper pc-stepper">
            <button type="button" className="icon-btn" onClick={() => onSet(n - 1)} aria-label={`Убрать: ${p.name}`}><MinusIcon /></button>
            <span className="num stepper-n">{n}</span>
            <button type="button" className="icon-btn" onClick={() => onSet(n + 1)} disabled={n >= p.available || full} aria-label={`Добавить: ${p.name}`}><PlusIcon /></button>
          </div>
        )}
      </div>
    </div>
  );
}
