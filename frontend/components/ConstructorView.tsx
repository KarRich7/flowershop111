"use client";
// Конструктор букета: цветы перетаскиваются на букет (мышью или долгим нажатием на телефоне)
// или добавляются кнопкой «+». Расположение стеблей сохраняется в заказе как эскиз для флориста.
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ApiError, request } from "@/lib/api";
import { money, plural } from "@/lib/format";
import type { Composition, ConstructorOptions, Product, Quote } from "@/lib/types";
import { BouquetCanvas, KindIcon, VASES, arrange, areaFor, freeSpot, instBox, kindOf, pack, toUV, wrapOf, type CatalogItem, type Inst, type VaseShape } from "./bouquet/draw";
import { useCart } from "./CartProvider";
import { ordersOpen } from "./OrdersClosed";
import { useShop } from "./ShopProvider";
import { CheckIcon, FlipIcon, MinusIcon, PlusIcon, RotateLeftIcon, RotateRightIcon, ShuffleIcon, TrashIcon } from "./Icons";
import { useToast } from "./Toast";

type Tab = "flowers" | "greenery" | "wrap" | "card";
type Drag = { mode: "new"; item_id: number; over: boolean } | { mode: "move"; uid: number; removing: boolean };
type Gesture = {
  mode: "new" | "move";
  item_id: number;
  uid: number;
  pointerId: number;
  touch: boolean;
  x0: number;
  y0: number;
  x: number;
  y: number;
  active: boolean;
  over: boolean;
  removing: boolean;
  timer: number;
};

const DRAFT_KEY = "cu_bouquet_draft_v2";
const LONG_PRESS_MS = 260;

export function ConstructorView() {
  const [opts, setOpts] = useState<ConstructorOptions | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [insts, setInsts] = useState<Inst[]>([]);
  const [packaging, setPackaging] = useState<number | null>(null);
  const [ribbon, setRibbon] = useState<number | null>(null);
  const [card, setCard] = useState<number | null>(null);
  const [cardText, setCardText] = useState("");
  const [wishes, setWishes] = useState("");
  const [tab, setTab] = useState<Tab>("flowers");
  const [species, setSpecies] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteErr, setQuoteErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);
  const [coarse, setCoarse] = useState(false);
  const [view, setView] = useState<"sketch" | "vase">("sketch");
  const [vase, setVase] = useState<VaseShape>("cylinder");
  const [vaseItem, setVaseItem] = useState<Product | null | undefined>(undefined);
  const [vaseBusy, setVaseBusy] = useState(false);
  const { addCustom, add, cart } = useCart();
  const shopNow = useShop();
  const closed = !ordersOpen(shopNow); // владелец закрыл приём заказов — собрать эскиз можно, купить нельзя
  const toast = useToast();

  const svgRef = useRef<SVGSVGElement | null>(null);
  const ghostRef = useRef<HTMLDivElement | null>(null);
  const gesture = useRef<Gesture | null>(null);
  const uidRef = useRef(0);
  const instsRef = useRef<Inst[]>([]);
  instsRef.current = insts;
  const seq = useRef(0);

  useEffect(() => {
    setCoarse(window.matchMedia("(pointer: coarse)").matches);
    request<ConstructorOptions>("/constructor/options").then(setOpts).catch((e) => setLoadErr(e.message));
  }, []);

  const products = useMemo(() => {
    const m = new Map<number, Product>();
    if (opts) [...opts.flowers, ...opts.greenery, ...opts.packaging, ...opts.ribbons, ...opts.cards].forEach((p) => m.set(p.inventory_item_id, p));
    return m;
  }, [opts]);
  const catalog = useMemo(() => {
    const m = new Map<number, CatalogItem>();
    products.forEach((p, id) => m.set(id, { id, name: p.name, species: p.species, color_hex: p.color_hex, type: p.type, constructor_image: p.constructor_image }));
    return m;
  }, [products]);
  const isGreenItem = useCallback((id: number) => products.get(id)?.type === "greenery", [products]);

  // Черновик букета переживает перезагрузку страницы
  useEffect(() => {
    if (!opts) return;
    let draft: { insts?: Inst[]; packaging?: number | null; ribbon?: number | null; card?: number | null; cardText?: string; wishes?: string } = {};
    try {
      draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
    } catch {}
    const used = new Map<number, number>();
    const restored = (draft.insts || []).filter((i) => {
      const p = products.get(i.item_id);
      if (!p || (p.type !== "flower" && p.type !== "greenery")) return false;
      const n = (used.get(i.item_id) || 0) + 1;
      if (n > p.available) return false;
      used.set(i.item_id, n);
      return true;
    });
    // старый черновик больше лимита (раньше было до 101 цветка) — оставляем первые max_stems цветков
    let fl = 0;
    const fine = restored.filter((i) => isGreenItem(i.item_id) || ++fl <= opts.max_stems);
    uidRef.current = fine.reduce((m, i) => Math.max(m, i.uid), 0);
    setInsts(fine);
    const ok = (id: number | null | undefined, list: Product[]) => (id && list.some((p) => p.inventory_item_id === id && p.available > 0) ? id : null);
    // «Без упаковки» (null) — осознанный выбор, его сохраняем; новый черновик начинается с первой доступной упаковки
    const firstPack = opts.packaging.find((p) => p.available > 0)?.inventory_item_id ?? null;
    setPackaging("packaging" in draft && draft.packaging == null ? null : ok(draft.packaging, opts.packaging) ?? firstPack);
    setRibbon(ok(draft.ribbon, opts.ribbons));
    setCard(ok(draft.card, opts.cards));
    setCardText(draft.cardText || "");
    setWishes(draft.wishes || "");
  }, [opts, products, isGreenItem]);

  useEffect(() => {
    if (!opts) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ insts, packaging, ribbon, card, cardText, wishes }));
      } catch {}
    }, 300);
    return () => clearTimeout(t);
  }, [opts, insts, packaging, ribbon, card, cardText, wishes]);

  const counts = useMemo(() => {
    const c = new Map<number, number>();
    insts.forEach((i) => c.set(i.item_id, (c.get(i.item_id) || 0) + 1));
    return c;
  }, [insts]);
  const stems = insts.filter((i) => !isGreenItem(i.item_id)).length;
  const greensN = insts.length - stems;

  const composition: Composition = useMemo(() => {
    const fl: { item_id: number; quantity: number }[] = [];
    const gr: { item_id: number; quantity: number }[] = [];
    counts.forEach((quantity, item_id) => (isGreenItem(item_id) ? gr : fl).push({ item_id, quantity }));
    return {
      flowers: fl,
      greenery: gr,
      packaging_id: packaging,
      ribbon_id: ribbon,
      card_id: card,
      card_text: card ? cardText : "",
      wishes,
      layout: insts.map((i) => ({ item_id: i.item_id, x: +((i.u + 1) / 2).toFixed(4), y: +((i.v + 1) / 2).toFixed(4), r: i.r, ...(i.f ? { f: true } : {}) })),
    };
  }, [counts, isGreenItem, packaging, ribbon, card, cardText, wishes, insts]);
  // Цена от расположения не зависит — пересчитываем только при изменении состава
  const quoteKey = useMemo(() => JSON.stringify({ ...composition, layout: undefined }), [composition]);

  useEffect(() => {
    if (!opts) return;
    setAdded(false);
    const body = JSON.parse(quoteKey) as Composition;
    if (!body.flowers.length) {
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
  }, [quoteKey, opts]);

  // ------------------------------------------------------------------ действия
  const addItem = useCallback(
    (p: Product, at?: { u: number; v: number }) => {
      if (!opts) return;
      const cur = instsRef.current;
      const have = cur.filter((i) => i.item_id === p.inventory_item_id).length;
      if (have >= p.available) {
        toast(p.available ? `${p.name}: в наличии только ${p.available} шт.` : `${p.name} нет в наличии`, "err");
        return;
      }
      const green = p.type === "greenery";
      if (!green && cur.filter((i) => !isGreenItem(i.item_id)).length >= opts.max_stems) {
        toast(`В букете не больше ${opts.max_stems} цветков`, "err");
        return;
      }
      const uid = ++uidRef.current;
      const spot = at ?? (green ? freeSpot(cur, true, uid) : { u: 0, v: 0 });
      const added: Inst = { uid, item_id: p.inventory_item_id, u: spot.u, v: spot.v, r: Math.round((Math.random() - 0.5) * 36), ...(at && !green ? { m: true } : {}) };
      // «+» — цветок встаёт в общую «шапку», остальные чуть раздвигаются; перетащенный — там, где отпустили
      const next = pack([...cur, added], catalog);
      instsRef.current = next;
      setInsts(next);
    },
    [opts, toast, isGreenItem, catalog],
  );
  const removeOne = (itemId: number) => {
    const mine = insts.filter((i) => i.item_id === itemId);
    if (!mine.length) return;
    const last = mine.reduce((a, b) => (b.uid > a.uid ? b : a));
    setInsts(pack(insts.filter((i) => i.uid !== last.uid), catalog));
    if (selected === last.uid) setSelected(null);
  };
  const removeInst = useCallback((uid: number) => {
    setInsts((xs) => pack(xs.filter((i) => i.uid !== uid), catalog));
    setSelected((s) => (s === uid ? null : s));
  }, [catalog]);
  const flipInst = useCallback((uid: number) => setInsts((xs) => xs.map((i) => (i.uid === uid ? { ...i, f: !i.f } : i))), []);
  const rotateInst = useCallback(
    (uid: number, d: number) => setInsts((xs) => xs.map((i) => (i.uid === uid ? { ...i, r: ((((i.r + d + 180) % 360) + 360) % 360) - 180 } : i))),
    [],
  );

  // Панель выбранного цветка висит над ним (или под ним, если цветок у верхнего края)
  const canvasRef = useRef<HTMLDivElement | null>(null);
  // Примерка в вазе: ваза из доп. товаров магазина (если есть) — предлагаем добавить её к заказу
  useEffect(() => {
    if (view !== "vase" || vaseItem !== undefined) return;
    request<Product[]>("/catalog/products?type=addon")
      .then((xs) => setVaseItem(xs.find((x) => /ваз/i.test(x.name)) || null))
      .catch(() => setVaseItem(null));
  }, [view, vaseItem]);
  const [toolPos, setToolPos] = useState<{ left: number; top: number; below: boolean } | null>(null);
  useLayoutEffect(() => {
    const place = () => {
      const svg = svgRef.current;
      const box = canvasRef.current;
      const b = selected != null && !drag ? instBox(catalog, insts, packaging ? catalog.get(packaging) : null, selected) : null;
      const m = svg?.getScreenCTM();
      if (!b || !m || !box) return setToolPos(null);
      const top = new DOMPoint(b.x, b.y - b.r).matrixTransform(m);
      const bottom = new DOMPoint(b.x, b.y + b.r).matrixTransform(m);
      const rc = box.getBoundingClientRect();
      const below = top.y - rc.top < 60;
      const half = Math.min(100, rc.width / 2);
      setToolPos({
        left: Math.min(Math.max(top.x - rc.left, half), rc.width - half),
        top: below ? bottom.y - rc.top + 8 : top.y - rc.top - 8,
        below,
      });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [selected, drag, insts, packaging, catalog]);

  // ------------------------------------------------------------------ перетаскивание
  const area = areaFor(wrapOf(packaging ? catalog.get(packaging) : null));
  const areaRef = useRef(area);
  areaRef.current = area;
  const addRef = useRef(addItem);
  addRef.current = addItem;

  const overCanvas = (x: number, y: number) => {
    const r = svgRef.current?.getBoundingClientRect();
    return !!r && x >= r.left - 8 && x <= r.right + 8 && y >= r.top - 8 && y <= r.bottom + 8;
  };
  const uvAt = (x: number, y: number) => {
    const svg = svgRef.current;
    const m = svg?.getScreenCTM();
    if (!svg || !m) return null;
    const pt = new DOMPoint(x, y).matrixTransform(m.inverse());
    return toUV(areaRef.current, pt.x, pt.y);
  };
  const moveGhost = (x: number, y: number) => {
    if (ghostRef.current) ghostRef.current.style.transform = `translate(${x}px, ${y}px)`;
  };

  useEffect(() => {
    const activate = (g: Gesture) => {
      g.active = true;
      if (g.mode === "new") {
        g.over = overCanvas(g.x, g.y);
        setDrag({ mode: "new", item_id: g.item_id, over: g.over });
        requestAnimationFrame(() => moveGhost(g.x, g.y));
        if (g.touch) navigator.vibrate?.(12);
      } else {
        setSelected(null);
        setDrag({ mode: "move", uid: g.uid, removing: false });
      }
    };
    const onMove = (e: PointerEvent) => {
      const g = gesture.current;
      if (!g || e.pointerId !== g.pointerId) return;
      g.x = e.clientX;
      g.y = e.clientY;
      const dist = Math.hypot(g.x - g.x0, g.y - g.y0);
      if (!g.active) {
        if (g.mode === "move") {
          if (dist > 3) activate(g);
        } else if (!g.touch) {
          if (dist > 4) activate(g);
        } else if (dist > 10) {
          clearTimeout(g.timer); // это прокрутка списка, а не перетаскивание
          gesture.current = null;
        }
        if (!g.active) return;
      }
      if (g.mode === "new") {
        moveGhost(g.x, g.y);
        const over = overCanvas(g.x, g.y);
        if (over !== g.over) {
          g.over = over;
          setDrag({ mode: "new", item_id: g.item_id, over });
        }
      } else {
        const inside = overCanvas(g.x, g.y);
        if (inside) {
          const uv = uvAt(g.x, g.y);
          if (uv) setInsts((xs) => xs.map((i) => (i.uid === g.uid ? { ...i, u: uv.u, v: uv.v, m: true } : i)));
        }
        if (inside === g.removing) {
          g.removing = !inside;
          setDrag({ mode: "move", uid: g.uid, removing: g.removing });
        }
      }
    };
    const finish = (e: PointerEvent, cancelled: boolean) => {
      const g = gesture.current;
      if (!g || e.pointerId !== g.pointerId) return;
      clearTimeout(g.timer);
      gesture.current = null;
      if (!g.active) {
        if (g.mode === "move" && !cancelled) setSelected((s) => (s === g.uid ? null : g.uid));
        return;
      }
      setDrag(null);
      if (cancelled) return;
      if (g.mode === "new" && overCanvas(g.x, g.y)) {
        const p = productsRef.current.get(g.item_id);
        const uv = uvAt(g.x, g.y);
        if (p) addRef.current(p, uv || undefined);
      } else if (g.mode === "move" && g.removing) {
        removeInst(g.uid);
      }
    };
    const onUp = (e: PointerEvent) => finish(e, false);
    const onCancel = (e: PointerEvent) => finish(e, true);
    // во время перетаскивания пальцем страница не должна прокручиваться
    const onTouchMove = (e: TouchEvent) => {
      if (gesture.current?.active && e.cancelable) e.preventDefault();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("touchmove", onTouchMove);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [removeInst]);

  const productsRef = useRef(products);
  productsRef.current = products;

  const startNew = (e: React.PointerEvent, p: Product) => {
    if (e.button !== 0 || p.available <= 0) return;
    if ((e.target as HTMLElement).closest("button")) return;
    const touch = e.pointerType !== "mouse";
    if (!touch) e.preventDefault();
    const g: Gesture = { mode: "new", item_id: p.inventory_item_id, uid: 0, pointerId: e.pointerId, touch, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false, over: false, removing: false, timer: 0 };
    if (touch)
      g.timer = window.setTimeout(() => {
        if (gesture.current !== g) return;
        g.active = true;
        g.over = false;
        setDrag({ mode: "new", item_id: g.item_id, over: false });
        requestAnimationFrame(() => moveGhost(g.x, g.y));
        navigator.vibrate?.(12);
      }, LONG_PRESS_MS);
    gesture.current = g;
  };
  const startMove = (e: React.PointerEvent, uid: number) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const it = insts.find((i) => i.uid === uid);
    if (!it) return;
    gesture.current = { mode: "move", item_id: it.item_id, uid, pointerId: e.pointerId, touch: e.pointerType !== "mouse", x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false, over: true, removing: false, timer: 0 };
  };

  // Delete / Backspace убирает выбранный стебель
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (selected == null) return;
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select")) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        removeInst(selected);
      } else if (e.key === "Escape") setSelected(null);
      else if (e.key === "f" || e.key === "а") flipInst(selected);
      else if (e.key === "[" || e.key === "]") rotateInst(selected, e.key === "[" ? -15 : 15);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, removeInst, flipInst, rotateInst]);

  if (loadErr) return <div className="notice red">Конструктор недоступен: {loadErr}</div>;
  if (!opts) return <div className="skeleton" style={{ height: 480 }} />;

  const speciesList = Array.from(new Set(opts.flowers.map((f) => f.species || f.category))).filter(Boolean);
  const flowerList = opts.flowers.filter((f) => !species || (f.species || f.category) === species);

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

  const need = Math.max(0, opts.min_stems - stems);
  const full = stems >= opts.max_stems;
  let status = "Оплата онлайн при оформлении";
  if (!stems) status = `От ${opts.min_stems} до ${opts.max_stems} цветков`;
  else if (need) status = `Добавьте ещё ${need} ${plural(need, "цветок", "цветка", "цветков")}`;
  else if (quoteErr) status = quoteErr;
  if (closed) status = "Приём заказов временно закрыт";

  const dragItem = drag?.mode === "new" ? catalog.get(drag.item_id) : undefined;
  const packItem = packaging ? catalog.get(packaging) : null;
  const ribbonItem = ribbon ? catalog.get(ribbon) : null;
  const canBuy = !!quote && !busy && !need && !closed;
  const isBox = wrapOf(packItem) === "box";
  const inVase = view === "vase" && !isBox;
  const vaseInCart = !!vaseItem && !!cart?.items.some((it) => it.product_id === vaseItem.id);
  async function addVase() {
    if (!vaseItem) return;
    setVaseBusy(true);
    try {
      await add(vaseItem.id, 1);
      toast("Ваза добавлена в корзину", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Не удалось добавить", "err");
    } finally {
      setVaseBusy(false);
    }
  }

  const lines = quote ? (
    <div className="bq-lines">
      {quote.lines.map((l) => (
        <div className="sum-row" key={l.item_id}>
          <span>
            {l.name} {l.quantity > 1 ? <span className="muted">× {l.quantity}</span> : null}
          </span>
          <span className="num nowrap">{money(l.total)}</span>
        </div>
      ))}
      <div className="sum-row">
        <span>Работа флориста</span>
        <span className="num">{money(quote.florist_fee)}</span>
      </div>
    </div>
  ) : null;

  const tabs: { id: Tab; label: string; n?: number }[] = [
    { id: "flowers", label: "Цветы", n: stems },
    { id: "greenery", label: "Зелень", n: greensN },
    { id: "wrap", label: "Упаковка" },
    { id: "card", label: "Открытка" },
  ];

  return (
    <div className={`bq ${drag ? "is-dragging" : ""}`}>
      <div className="bq-stage">
        <div className="bq-card">
          <div className="bq-tools">
            <span className="muted small">
              <span className="num">{stems}</span> из <span className="num">{opts.max_stems}</span> {plural(opts.max_stems, "цветка", "цветков", "цветков")}
              {greensN > 0 && <> · зелень <span className="num">{greensN}</span></>}
            </span>
            <span className="row" style={{ gap: 4 }}>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => setInsts(arrange(insts, catalog))} disabled={insts.length < 2} title="Расставить ровно">
                <ShuffleIcon /> <span className="hide-xs">Расставить</span>
              </button>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => { setInsts([]); setSelected(null); }} disabled={!insts.length} title="Убрать все цветы">
                <TrashIcon /> <span className="hide-xs">Очистить</span>
              </button>
            </span>
          </div>
          <div ref={canvasRef} className={`bq-canvas ${drag?.mode === "new" && drag.over ? "over" : ""}`} onPointerDown={() => setSelected(null)}>
            <BouquetCanvas
              catalog={catalog}
              insts={insts}
              packaging={packItem}
              ribbon={ribbonItem}
              card={card ? { text: cardText } : null}
              selected={selected}
              dragging={drag?.mode === "move" ? drag.uid : null}
              removing={drag?.mode === "move" && drag.removing}
              dropHint={drag?.mode === "new"}
              empty={coarse ? "Удерживайте цветок и перенесите сюда" : "Перетащите цветы сюда"}
              onInstDown={startMove}
              svgRef={svgRef}
              className="bq-svg"
              label={`${inVase ? "Букет в вазе" : "Эскиз букета"}: ${stems} ${plural(stems, "цветок", "цветка", "цветков")}`}
              vase={inVase ? vase : null}
            />
            <div className="bq-view" role="group" aria-label="Вид" onPointerDown={(e) => e.stopPropagation()}>
              <button type="button" aria-pressed={!inVase} className={!inVase ? "on" : ""} onClick={() => setView("sketch")}>Эскиз</button>
              <button
                type="button"
                aria-pressed={inVase}
                className={inVase ? "on" : ""}
                disabled={isBox}
                title={isBox ? "Букет в шляпной коробке стоит во флористической губке — ваза не нужна" : "Как букет будет смотреться в вазе"}
                onClick={() => setView("vase")}
              >
                В вазе
              </button>
            </div>
            {inVase && (
              <div className="bq-vases" role="radiogroup" aria-label="Форма вазы" onPointerDown={(e) => e.stopPropagation()}>
                {VASES.map((v) => (
                  <button key={v.id} type="button" role="radio" aria-checked={vase === v.id} className={vase === v.id ? "on" : ""} title={v.hint} onClick={() => setVase(v.id)}>
                    {v.label}
                  </button>
                ))}
              </div>
            )}
            {drag?.mode === "move" && <div className="bq-float-hint">{drag.removing ? "Отпустите, чтобы убрать" : "Вынесите за букет, чтобы убрать"}</div>}
            {selected != null && !drag && toolPos && (
              <div
                className={`bq-sel-bar ${toolPos.below ? "below" : ""}`}
                style={{ left: toolPos.left, top: toolPos.top }}
                role="toolbar"
                aria-label="Выбранный цветок"
                onPointerDown={(e) => e.stopPropagation()}
              >
                <button type="button" onClick={() => flipInst(selected)} title="Отразить (F)" aria-label="Отразить"><FlipIcon /><span>Отразить</span></button>
                <button type="button" onClick={() => rotateInst(selected, -15)} title="Повернуть влево на 15° ( [ )" aria-label="Повернуть влево"><RotateLeftIcon /></button>
                <button type="button" onClick={() => rotateInst(selected, 15)} title="Повернуть вправо на 15° ( ] )" aria-label="Повернуть вправо"><RotateRightIcon /></button>
                <span className="bq-sel-sep" aria-hidden />
                <button type="button" className="danger" onClick={() => removeInst(selected)} title="Убрать из букета (Delete)" aria-label="Убрать из букета"><TrashIcon /></button>
              </div>
            )}
            {selected != null && !drag && <div className="bq-float-hint">Перетащите, чтобы переставить</div>}
          </div>
          {inVase && (
            <div className="bq-vase-note">
              {vase === "cylinder" && vaseItem ? (
                <>
                  <span>
                    {vaseItem.name} — <span className="num nowrap">{money(vaseItem.price)}</span>
                    <span className="muted"> · упаковку перед тем, как поставить букет в воду, снимают</span>
                  </span>
                  {vaseInCart ? (
                    <span className="bq-vase-ok"><CheckIcon /> В корзине</span>
                  ) : (
                    <button type="button" className="btn btn-outline btn-sm" disabled={vaseBusy || !vaseItem.in_stock} onClick={addVase}>
                      {!vaseItem.in_stock ? "Нет в наличии" : vaseBusy ? "Добавляем…" : "Добавить вазу"}
                    </button>
                  )}
                </>
              ) : (
                <span className="muted">Примерка: так букет встанет в вазу похожей формы. Упаковку перед тем, как поставить букет в воду, снимают.</span>
              )}
            </div>
          )}
          <div className="bq-bar">
            <div className="bq-bar-sum">
              <div className="bq-total num">{quote ? money(quote.total) : money(0)}</div>
              <div className="tiny muted">{status}</div>
            </div>
            {added ? (
              <Link href="/cart" className="btn btn-outline">Открыть корзину</Link>
            ) : (
              <button className="btn" disabled={!canBuy} onClick={addToCart}>{busy ? "Добавляем…" : "В корзину"}</button>
            )}
          </div>
        </div>
      </div>

      <div className="bq-palette">
        <div className="seg bq-tabs" role="tablist">
          {tabs.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
              {t.label}
              {t.n ? <span className="seg-n num">{t.n}</span> : null}
            </button>
          ))}
        </div>

        {tab === "flowers" && (
          <section>
            {full && (
              <p className="notice amber bq-limit" role="status">
                В букете уже {opts.max_stems} {plural(opts.max_stems, "цветок", "цветка", "цветков")} — это максимум для конструктора. Нужен букет больше — выберите готовый в каталоге или позвоните нам.
              </p>
            )}
            <div className="chips scroll bq-chips">
              <button className={`chip ${!species ? "on" : ""}`} onClick={() => setSpecies("")}>Все</button>
              {speciesList.map((s) => (
                <button key={s} className={`chip ${species === s ? "on" : ""}`} onClick={() => setSpecies(s)}>{s}</button>
              ))}
            </div>
            <div className="bq-list">
              {flowerList.map((f) => (
                <Row key={f.id} p={f} count={counts.get(f.inventory_item_id) || 0} full={full} onStart={startNew} onAdd={() => addItem(f)} onRemove={() => removeOne(f.inventory_item_id)} dragging={dragItem?.id === f.inventory_item_id} />
              ))}
            </div>
          </section>
        )}

        {tab === "greenery" && (
          <section>
            <p className="muted small bq-note">Зелень ложится по краю букета и не входит в лимит цветков</p>
            <div className="bq-list">
              {opts.greenery.map((g) => (
                <Row key={g.id} p={g} count={counts.get(g.inventory_item_id) || 0} onStart={startNew} onAdd={() => addItem(g)} onRemove={() => removeOne(g.inventory_item_id)} dragging={dragItem?.id === g.inventory_item_id} />
              ))}
            </div>
          </section>
        )}

        {tab === "wrap" && (
          <section>
            <h3 className="bq-h">Упаковка</h3>
            <div className="bq-tiles">
              <NoneTile on={!packaging} label="Без упаковки" onPick={() => setPackaging(null)} />
              {opts.packaging.map((p) => (
                <Tile key={p.id} p={p} on={packaging === p.inventory_item_id} onPick={() => setPackaging(p.inventory_item_id)} />
              ))}
            </div>
            {!packaging && <p className="muted small bq-note">Стебли соберём в пучок и перевяжем выбранной лентой с бантом, а если ленту не выбрать — шпагатом</p>}
            <h3 className="bq-h">Лента</h3>
            <div className="bq-tiles">
              <NoneTile on={!ribbon} label="Без ленты" onPick={() => setRibbon(null)} />
              {opts.ribbons.map((p) => (
                <Tile key={p.id} p={p} on={ribbon === p.inventory_item_id} onPick={() => setRibbon(p.inventory_item_id)} />
              ))}
            </div>
          </section>
        )}

        {tab === "card" && (
          <section>
            <h3 className="bq-h">Открытка</h3>
            <div className="bq-tiles">
              <NoneTile on={!card} label="Без открытки" onPick={() => setCard(null)} />
              {opts.cards.map((p) => (
                <Tile key={p.id} p={p} on={card === p.inventory_item_id} onPick={() => setCard(p.inventory_item_id)} />
              ))}
            </div>
            <div className="stack" style={{ marginTop: 16 }}>
              {card && (
                <label className="field">
                  <span>Текст открытки</span>
                  <textarea className="textarea" maxLength={300} value={cardText} onChange={(e) => setCardText(e.target.value)} placeholder="С днём рождения, мама" />
                </label>
              )}
              <label className="field">
                <span>Пожелания флористу</span>
                <textarea className="textarea" maxLength={500} value={wishes} onChange={(e) => setWishes(e.target.value)} placeholder="Например: без резких запахов, повыше" />
              </label>
            </div>
          </section>
        )}

        {lines && (
          <div className="card card-tight bq-summary">
            <h3 className="bq-h">Расчёт стоимости</h3>
            {lines}
            <div className="sum-row total">
              <span>Итого</span>
              <span className="num">{money(quote!.total)}</span>
            </div>
          </div>
        )}
        <p className="tiny muted bq-foot">
          Индивидуальный букет оплачивается только онлайн. Цена фиксируется при оформлении, флорист подтвердит состав и при необходимости предложит замену.
        </p>
      </div>

      {dragItem && (
        <div className={`bq-ghost ${drag?.mode === "new" && drag.over ? "over" : ""}`} ref={ghostRef} aria-hidden>
          <div className="bq-ghost-in">
            {dragItem.constructor_image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={dragItem.constructor_image} alt="" width={72} height={72} className="bq-ghost-img" draggable={false} />
            ) : (
              <KindIcon kind={kindOf(dragItem)} color={dragItem.color_hex || "#d9a7b0"} size={64} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ p, count, full, onStart, onAdd, onRemove, dragging }: { p: Product; count: number; full?: boolean; onStart: (e: React.PointerEvent, p: Product) => void; onAdd: () => void; onRemove: () => void; dragging: boolean }) {
  const out = p.available <= 0;
  return (
    <div
      className={`bq-row ${count ? "sel" : ""} ${out ? "dis" : ""} ${dragging ? "lift" : ""}`}
      onPointerDown={(e) => onStart(e, p)}
      onContextMenu={(e) => e.preventDefault()}
      data-item={p.inventory_item_id}
    >
      <div className={`bq-thumb ${p.constructor_image ? "cut" : ""}`}>
        {p.constructor_image || p.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={p.constructor_image || p.image || ""} alt="" loading="lazy" draggable={false} />
        ) : (
          <KindIcon kind={kindOf({ species: p.species, name: p.name, type: p.type })} color={p.color_hex || "#d9a7b0"} size={40} />
        )}
      </div>
      <div className="bq-row-main">
        <div className="bq-row-name">{p.name}</div>
        <div className="bq-row-meta">
          <span className="num">{money(p.price)}</span>
          <span>{out ? "нет в наличии" : <>в наличии <span className="num">{p.available}</span></>}</span>
        </div>
      </div>
      <div className="stepper">
        <button type="button" className="icon-btn" onClick={onRemove} disabled={!count} aria-label={`Убрать: ${p.name}`}><MinusIcon /></button>
        <span className="num stepper-n">{count}</span>
        <button type="button" className="icon-btn" onClick={onAdd} disabled={out || count >= p.available || full} aria-label={`Добавить: ${p.name}`}><PlusIcon /></button>
      </div>
    </div>
  );
}

export function Tile({ p, on, onPick }: { p: Product; on: boolean; onPick: () => void }) {
  const out = p.available <= 0;
  return (
    <button type="button" className={`bq-tile ${on ? "on" : ""}`} onClick={onPick} disabled={out && !on} aria-pressed={on}>
      <span className="bq-tile-img">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {p.image ? <img src={p.image} alt="" loading="lazy" draggable={false} /> : <span className="swatch" style={{ background: p.color_hex || "#ddd" }} />}
        {on && <span className="bq-tile-check"><CheckIcon /></span>}
      </span>
      <span className="bq-tile-name">{p.name}</span>
      <span className="bq-tile-meta num">{out ? "нет в наличии" : money(p.price)}</span>
    </button>
  );
}

export function NoneTile({ on, label, onPick }: { on: boolean; label: string; onPick: () => void }) {
  return (
    <button type="button" className={`bq-tile none ${on ? "on" : ""}`} onClick={onPick} aria-pressed={on}>
      <span className="bq-tile-img"><span className="bq-none-mark" />{on && <span className="bq-tile-check"><CheckIcon /></span>}</span>
      <span className="bq-tile-name">{label}</span>
      <span className="bq-tile-meta">&nbsp;</span>
    </button>
  );
}
