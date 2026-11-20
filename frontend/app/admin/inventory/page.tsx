"use client";
import Link from "next/link";
import { PlusIcon, XIcon } from "@/components/Icons";
import { useEffect, useMemo, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { Field } from "@/components/Field";
import { useToast } from "@/components/Toast";
import { adminApi, toKopecks, toRub, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import * as V from "@/lib/validate";
import { dateLong, dateTime, money } from "@/lib/format";

type Item = {
  id: number; sku: string; name: string; category: string; category_label: string; unit: string; unit_label: string;
  purchase_price: number; sale_price: number | null; quantity: number; reserved: number; available: number; min_stock: number;
  low: boolean; is_active: boolean; product_id: number | null; image: string | null;
};
type Move = { id: number; at: string; item: string; item_id: number; type: string; type_label: string; delta: number; balance_after: number; reason: string; user: string; order_number: string | null; unit_cost: number | null };
type Demand = { date: string; item_id: number; item: string; planned: number; available_now: number };

const TABS: [string, string][] = [["stock", "Остатки"], ["supply", "Поставка"], ["writeoff", "Списание и корректировка"], ["count", "Инвентаризация"], ["moves", "Движения"], ["demand", "Потребность"]];
const CATS: [string, string][] = [["", "Все"], ["flower", "Цветы"], ["greenery", "Зелень"], ["packaging", "Упаковка"], ["ribbon", "Ленты"], ["card", "Открытки"], ["addon", "Доп. товары"], ["bouquet", "Готовые букеты"]];

const UNITS: [string, string][] = [["pcs", "шт"], ["stem", "стебель"], ["branch", "ветка"], ["sheet", "лист"], ["cut", "отрез"]];
const ITEM_CATS = CATS.slice(1).concat([["consumable", "Расходные материалы"]]);
const MOVE_TYPES: [string, string][] = [["", "Все операции"], ["supply", "Поставка"], ["write_off", "Списание"], ["store_sale", "Продажа в магазине"], ["order_fulfillment", "Отгрузка по заказу"], ["adjustment", "Корректировка"], ["inventory", "Инвентаризация"], ["assembly_consume", "Расход на сборку"], ["assembly_produce", "Сборка букета"], ["return", "Возврат на склад"]];

export default function InventoryPage() {
  const me = useStaff();
  const [tab, setTab] = useState("stock");
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t) setTab(t);
  }, []);
  const { data: items, error, reload } = useAdmin<Item[]>("/inventory");
  const active = useMemo(() => (items || []).filter((i) => i.is_active), [items]);
  const owner = me.role === "owner";
  return (
    <>
      <PageTop title="Склад" />
      <div className="tabs">
        {TABS.map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <ErrorBox text={error} />
      {!items ? <Loading /> : (
        <>
          {tab === "stock" && <Stock items={items} owner={owner} onChanged={reload} />}
          {tab === "supply" && <Supply items={active} owner={owner} onDone={reload} />}
          {tab === "writeoff" && <WriteOff items={active} onDone={reload} />}
          {tab === "count" && <Count items={active} onDone={reload} />}
          {tab === "moves" && <Moves items={items} owner={owner} />}
          {tab === "demand" && <DemandView />}
        </>
      )}
    </>
  );
}

function Stock({ items, owner, onChanged }: { items: Item[]; owner: boolean; onChanged: () => void }) {
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [low, setLow] = useState(false);
  const [archived, setArchived] = useState(false);
  const [edit, setEdit] = useState<Item | "new" | null>(null);
  const list = items.filter((i) => (archived ? !i.is_active : i.is_active) && (!cat || i.category === cat) && (!low || i.low) && (!q || `${i.name} ${i.sku}`.toLowerCase().includes(q.toLowerCase())));
  const archivedCount = items.filter((i) => !i.is_active).length;
  return (
    <>
      <div className="filters">
        <select className="select" value={cat} onChange={(e) => setCat(e.target.value)}>{[["", "Все"] as [string, string], ...ITEM_CATS].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <input className="input" placeholder="Название или артикул" maxLength={80} value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="checkbox small"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Только заканчивающиеся</label>
        {archivedCount > 0 && <label className="checkbox small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Архив и скрытые ({archivedCount})</label>}
        {owner && <button className="btn btn-sm" style={{ marginLeft: "auto" }} onClick={() => setEdit("new")}><PlusIcon /> Новая позиция</button>}
      </div>
      <div className="table-wrap">
        <table className="t">
          <thead><tr><th>Позиция</th><th>Категория</th><th className="num">На складе</th><th className="num">В резерве</th><th className="num">Доступно</th><th className="num">Мин.</th>{owner && <th className="num">Закупка</th>}<th className="num">Продажа</th></tr></thead>
          <tbody>
            {list.map((i) => (
              <tr key={i.id} className={owner ? "click" : ""} onClick={() => owner && setEdit(i)}>
                <td><b>{i.name}</b><div className="tiny muted">{i.sku}{!i.is_active && " · в архиве"}</div></td>
                <td className="small">{i.category_label}</td>
                <td className="num">{i.quantity} <span className="tiny muted">{i.unit_label}</span></td>
                <td className="num">{i.reserved || "—"}</td>
                <td className="num"><span className={`badge ${i.available <= 0 ? "red" : i.low ? "amber" : "green"}`}>{i.available}</span></td>
                <td className="num muted">{i.min_stock}</td>
                {owner && <td className="num small">{money(i.purchase_price)}</td>}
                <td className="num small">{money(i.sale_price)}</td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={8} className="empty">Ничего не найдено</td></tr>}
          </tbody>
        </table>
      </div>
      {edit && <ItemModal item={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onChanged(); }} />}
    </>
  );
}

function ItemModal({ item, onClose, onSaved }: { item: Item | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({
    name: item?.name || "", category: item?.category || "consumable", unit: item?.unit || "pcs", sku: item?.sku || "",
    purchase_price: toRub(item?.purchase_price ?? null), sale_price: toRub(item?.sale_price ?? null), min_stock: String(item?.min_stock ?? 0),
    quantity: "", is_active: item?.is_active ?? true,
  });
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const linked = Boolean(item?.product_id);
  const set = (k: string, v: string | boolean) => { setF((x) => ({ ...x, [k]: v })); setErrors((e) => ({ ...e, [k]: "" })); };

  async function save() {
    const errs = V.collect({
      name: V.text(f.name, "Название", { required: true, min: 2, max: 160 }),
      sku: V.sku(f.sku),
      purchase_price: V.rub(f.purchase_price, "Закупочная цена", { required: false }),
      sale_price: V.rub(f.sale_price, "Цена продажи", { required: false }),
      min_stock: V.int(f.min_stock, "Мин. остаток", { required: false, min: 0, max: 100000 }),
      quantity: item ? null : V.int(f.quantity, "Начальный остаток", { required: false, min: 0, max: 100000 }),
    });
    setErrors(errs);
    if (V.hasErrors(errs)) return;
    setBusy(true);
    const body: Record<string, unknown> = {
      name: f.name.trim(), unit: f.unit, purchase_price: toKopecks(f.purchase_price) || 0, sale_price: toKopecks(f.sale_price),
      min_stock: Number(f.min_stock || 0), is_active: f.is_active,
    };
    if (f.sku.trim()) body.sku = f.sku.trim();
    if (!linked) body.category = f.category;
    if (!item && f.quantity) body.quantity = Number(f.quantity);
    try {
      if (item) await adminApi(`/inventory/${item.id}`, { method: "PATCH", body });
      else await adminApi("/inventory", { body });
      toast(item ? "Позиция сохранена" : "Позиция добавлена", "ok");
      onSaved();
    } catch (e) {
      toast(V.serverError(e, setErrors), "err");
      setBusy(false);
    }
  }
  async function remove() {
    if (!item) return;
    const ask = linked
      ? `Удалить «${item.name}» вместе с товаром витрины навсегда? Товар пропадёт с сайта, из ботов и корзин. Если по позиции были операции, складская история останется в архиве.`
      : `Удалить «${item.name}»? Если по позиции были операции, она уйдёт в архив, история сохранится.`;
    if (!confirm(ask)) return;
    try {
      const r = await adminApi<{ message: string }>(`/inventory/${item.id}`, { method: "DELETE" });
      toast(r.message, "ok");
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }

  return (
    <Modal title={item ? item.name : "Новая складская позиция"} onClose={onClose}>
      <div className="stack">
        {linked && <div className="notice small">Позиция связана с товаром витрины. Фото, описание и категория на сайте — в разделе <Link href="/admin/products">«Товары»</Link>.</div>}
        <div className="form-grid">
          <Field label="Название *" error={errors.name} full><input className="input" maxLength={160} value={f.name} onChange={(e) => set("name", e.target.value)} autoFocus={!item} /></Field>
          <Field label="Группа" hint={linked ? "У товара витрины группа не меняется" : undefined}>
            <select className="select" value={f.category} disabled={linked} onChange={(e) => set("category", e.target.value)}>
              {ITEM_CATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Единица учёта"><select className="select" value={f.unit} onChange={(e) => set("unit", e.target.value)}>{UNITS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <Field label="Артикул" error={errors.sku} hint={item ? undefined : "Пусто — присвоим автоматически"}><input className="input" maxLength={32} value={f.sku} onChange={(e) => set("sku", e.target.value.toUpperCase())} /></Field>
          <Field label="Мин. остаток" error={errors.min_stock} hint="Ниже — позиция подсвечивается как заканчивающаяся"><input className="input" type="number" min={0} max={100000} value={f.min_stock} onChange={(e) => set("min_stock", e.target.value)} /></Field>
          <Field label="Закупочная цена, ₽" error={errors.purchase_price}><input className="input" inputMode="decimal" value={f.purchase_price} onChange={(e) => set("purchase_price", e.target.value)} /></Field>
          <Field label="Цена продажи, ₽" error={errors.sale_price} hint="Для материалов конструктора и товаров витрины"><input className="input" inputMode="decimal" value={f.sale_price} onChange={(e) => set("sale_price", e.target.value)} /></Field>
          {!item && <Field label="Начальный остаток" error={errors.quantity}><input className="input" type="number" min={0} max={100000} placeholder="0" value={f.quantity} onChange={(e) => set("quantity", e.target.value)} /></Field>}
        </div>
        {item && <label className="checkbox"><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> Активна (видна в поставках, списаниях и рецептурах)</label>}
        <div className="row-between">
          {item ? <button type="button" className="danger-link" onClick={remove}>Удалить позицию</button> : <span />}
          <div className="row">
            <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
            <button className="btn" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : item ? "Сохранить" : "Добавить"}</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function ItemSelect({ items, value, onChange, filter, invalid }: { items: Item[]; value: string; onChange: (v: string) => void; filter?: (i: Item) => boolean; invalid?: boolean }) {
  const groups = useMemo(() => {
    const m = new Map<string, Item[]>();
    items.filter(filter || (() => true)).forEach((i) => m.set(i.category_label, [...(m.get(i.category_label) || []), i]));
    return Array.from(m.entries());
  }, [items, filter]);
  return (
    <select className={`select ${invalid ? "input invalid" : ""}`} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Выберите позицию</option>
      {groups.map(([g, l]) => (
        <optgroup key={g} label={g}>
          {l.map((i) => <option key={i.id} value={i.id}>{i.name} (ост. {i.quantity})</option>)}
        </optgroup>
      ))}
    </select>
  );
}

type Line = { item_id: string; quantity: string; unit_cost: string };
const emptyLine = (): Line => ({ item_id: "", quantity: "", unit_cost: "" });

function Supply({ items, owner, onDone }: { items: Item[]; owner: boolean; onDone: () => void }) {
  const toast = useToast();
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [errs, setErrs] = useState<Record<number, V.Errors>>({});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const notBouquet = (i: Item) => i.category !== "bouquet";
  const total = lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (toKopecks(l.unit_cost) || 0), 0);
  const upd = (k: number, key: keyof Line, v: string) => {
    setLines(lines.map((x, i) => (i === k ? { ...x, [key]: v } : x)));
    setErrs((e) => ({ ...e, [k]: { ...(e[k] || {}), [key]: "" } }));
  };
  async function submit() {
    const filled = lines.map((l, k) => [l, k] as const).filter(([l]) => l.item_id || l.quantity || l.unit_cost);
    const found: Record<number, V.Errors> = {};
    const seen = new Set<string>();
    filled.forEach(([l, k]) => {
      const e = V.collect({
        item_id: !l.item_id ? "Выберите позицию" : seen.has(l.item_id) ? "Позиция уже есть в поставке" : null,
        quantity: V.int(l.quantity, "Количество", { min: 1, max: 100000 }),
        unit_cost: owner ? V.rub(l.unit_cost, "Цена закупки", { required: false }) : null,
      });
      seen.add(l.item_id);
      if (V.hasErrors(e)) found[k] = e;
    });
    setErrs(found);
    if (!filled.length) return toast("Добавьте хотя бы одну позицию", "err");
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await adminApi("/inventory/supply", { body: { comment: comment.trim(), lines: filled.map(([l]) => ({ item_id: Number(l.item_id), quantity: Number(l.quantity), unit_cost: owner ? toKopecks(l.unit_cost) : null })) } });
      toast(`Поставка принята: ${filled.length} поз.`, "ok");
      setLines([emptyLine()]);
      setComment("");
      onDone();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <div className="panel-title">Приёмка поставки</div>
      {!owner && <p className="muted small">Цены закупки вносит владелец.</p>}
      {lines.map((l, k) => {
        const e = errs[k] || {};
        return (
          <div key={k} style={{ marginBottom: 8 }}>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <div style={{ flex: 3 }}><ItemSelect items={items} value={l.item_id} filter={notBouquet} invalid={!!e.item_id} onChange={(v) => upd(k, "item_id", v)} /></div>
              <input className={`input ${e.quantity ? "invalid" : ""}`} style={{ flex: 1 }} type="number" min={1} max={100000} step={1} placeholder="Кол-во" value={l.quantity} onChange={(ev) => upd(k, "quantity", ev.target.value)} />
              {owner && <input className={`input ${e.unit_cost ? "invalid" : ""}`} style={{ flex: 1 }} inputMode="decimal" placeholder="Цена закупки, ₽" value={l.unit_cost} onChange={(ev) => upd(k, "unit_cost", ev.target.value)} />}
              <button className="icon-btn" onClick={() => setLines(lines.filter((_, i) => i !== k))} disabled={lines.length === 1} aria-label="Удалить строку"><XIcon /></button>
            </div>
            {V.hasErrors(e) && <div className="field-err">{Object.values(e).filter(Boolean).join(" · ")}</div>}
          </div>
        );
      })}
      <button className="btn btn-sm btn-ghost" onClick={() => setLines([...lines, emptyLine()])}>+ Строка</button>
      <Field label="Комментарий" hint="До 200 символов" className="mt-12"><input className="input" maxLength={200} placeholder="Поставщик, накладная №…" value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      <div className="row-between" style={{ marginTop: 14 }}>
        {owner ? <span className="muted">Сумма поставки: <b>{money(total)}</b></span> : <span />}
        <button className="btn" disabled={busy} onClick={submit}>Принять поставку</button>
      </div>
    </div>
  );
}

function WriteOff({ items, onDone }: { items: Item[]; onDone: () => void }) {
  const toast = useToast();
  const [mode, setMode] = useState<"write-off" | "adjust">("write-off");
  const [itemId, setItemId] = useState("");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("Увядание");
  const [other, setOther] = useState("");
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const item = items.find((i) => String(i.id) === itemId);
  const finalReason = mode === "write-off" && reason === "Другое" ? other.trim() : reason.trim();
  async function submit() {
    const e = V.collect({
      item_id: itemId ? null : "Выберите позицию",
      qty: mode === "write-off"
        ? V.int(qty, "Количество", { min: 1, max: item ? Math.max(item.available, 1) : 100000 }) || (item && item.available <= 0 ? "Свободного остатка нет — списывать нечего" : null)
        : V.int(qty, "Изменение", { min: -100000, max: 100000 }) || (Number(qty) === 0 ? "Изменение не может быть нулевым" : null) || (item && item.quantity + Number(qty) < item.reserved ? `Остаток станет меньше резерва (${item.reserved})` : null),
      reason: V.text(finalReason, "Причина", { required: true, min: 3, max: 200 }),
    });
    setErrors(e);
    if (V.hasErrors(e)) return;
    setBusy(true);
    try {
      if (mode === "write-off") await adminApi("/inventory/write-off", { body: { item_id: Number(itemId), quantity: Number(qty), reason: finalReason } });
      else await adminApi("/inventory/adjust", { body: { item_id: Number(itemId), delta: Number(qty), reason: finalReason } });
      toast(mode === "write-off" ? "Списано" : "Остаток скорректирован", "ok");
      setQty("");
      onDone();
    } catch (x) {
      toast(x instanceof ApiError ? x.message : "Ошибка", "err");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card" style={{ maxWidth: 640 }}>
      <div className="seg" style={{ marginBottom: 14 }}>
        <button className={mode === "write-off" ? "on" : ""} onClick={() => { setMode("write-off"); setReason("Увядание"); setErrors({}); }}>Списание</button>
        <button className={mode === "adjust" ? "on" : ""} onClick={() => { setMode("adjust"); setReason(""); setErrors({}); }}>Корректировка ±</button>
      </div>
      <div className="stack">
        <Field label="Позиция" error={errors.item_id}><ItemSelect items={items} value={itemId} invalid={!!errors.item_id} onChange={(v) => { setItemId(v); setErrors({}); }} /></Field>
        {item && <div className="hint">На складе {item.quantity}, в резерве {item.reserved}, доступно {item.available}. Нельзя списать зарезервированное под заказы.</div>}
        <Field label={mode === "write-off" ? "Количество к списанию" : "Изменение (например, -2 или 3)"} error={errors.qty}>
          <input className="input" type="number" step={1} min={mode === "write-off" ? 1 : undefined} value={qty} onChange={(e) => { setQty(e.target.value); setErrors((x) => ({ ...x, qty: "" })); }} />
        </Field>
        <Field label="Причина" error={errors.reason}>
          {mode === "write-off" ? (
            <select className="select" value={reason} onChange={(e) => setReason(e.target.value)}>
              {["Увядание", "Брак поставщика", "Повреждение", "Использовано для витрины", "Другое"].map((r) => <option key={r}>{r}</option>)}
            </select>
          ) : (
            <input className="input" maxLength={200} placeholder="Пересорт, ошибка приёмки…" value={reason} onChange={(e) => { setReason(e.target.value); setErrors((x) => ({ ...x, reason: "" })); }} />
          )}
        </Field>
        {mode === "write-off" && reason === "Другое" && (
          <Field label="Опишите причину" error={errors.reason}><input className="input" maxLength={200} value={other} onChange={(e) => { setOther(e.target.value); setErrors((x) => ({ ...x, reason: "" })); }} /></Field>
        )}
        <button className={`btn ${mode === "write-off" ? "btn-danger" : ""}`} disabled={busy} onClick={submit}>
          {mode === "write-off" ? "Списать" : "Применить корректировку"}
        </button>
      </div>
    </div>
  );
}

function Count({ items, onDone }: { items: Item[]; onDone: () => void }) {
  const toast = useToast();
  const [cat, setCat] = useState("flower");
  const [counts, setCounts] = useState<Record<number, string>>({});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ item_id: number; name?: string; delta: number; before?: number; after?: number }[] | null>(null);
  const list = items.filter((i) => !cat || i.category === cat);
  const filled = Object.entries(counts).filter(([, v]) => v !== "");
  const bad = filled.filter(([id, v]) => {
    const it = items.find((i) => i.id === Number(id));
    return V.int(v, "Факт", { min: 0, max: 100000 }) || (it && Number(v) < it.reserved);
  });
  return (
    <div className="stack">
      <div className="filters">
        <select className="select" value={cat} onChange={(e) => setCat(e.target.value)}>{[["", "Все"] as [string, string], ...ITEM_CATS].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <span className="muted small">Введите фактическое количество только по пересчитанным позициям. Расхождения будут проведены как корректировки.</span>
      </div>
      <div className="table-wrap">
        <table className="t">
          <thead><tr><th>Позиция</th><th className="num">По учёту</th><th className="num">В резерве</th><th className="num">Факт</th><th className="num">Разница</th></tr></thead>
          <tbody>
            {list.map((i) => {
              const v = counts[i.id];
              const err = v !== undefined && v !== "" ? V.int(v, "Факт", { min: 0, max: 100000 }) || (Number(v) < i.reserved ? `меньше резерва ${i.reserved}` : null) : null;
              const diff = v !== undefined && v !== "" && !err ? Number(v) - i.quantity : null;
              return (
                <tr key={i.id}>
                  <td><b>{i.name}</b><div className="tiny muted">{i.sku}</div></td>
                  <td className="num">{i.quantity}</td>
                  <td className="num">{i.reserved || "—"}</td>
                  <td className="num" style={{ width: 140 }}>
                    <input className={`input input-sm ${err ? "invalid" : ""}`} type="number" min={0} max={100000} step={1} value={v ?? ""} onChange={(e) => setCounts({ ...counts, [i.id]: e.target.value })} />
                    {err && <div className="field-err">{err}</div>}
                  </td>
                  <td className="num">{diff === null ? "" : <span className={`badge ${diff === 0 ? "gray" : diff > 0 ? "green" : "red"}`}>{diff > 0 ? `+${diff}` : diff}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Field label="Комментарий"><input className="input" maxLength={200} placeholder="Например: плановая инвентаризация, пятница" value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      <div className="row-between">
        <span className="muted small">Заполнено: {filled.length}{bad.length ? ` · с ошибкой: ${bad.length}` : ""}</span>
        <button
          className="btn"
          disabled={busy || !filled.length || bad.length > 0}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await adminApi<{ result: { item_id: number; delta: number }[] }>("/inventory/count", { body: { comment: comment.trim(), counts: filled.map(([id, v]) => ({ item_id: Number(id), counted: Number(v) })) } });
              setResult(r.result);
              toast(`Инвентаризация проведена: изменено ${r.result.filter((x) => x.delta).length} поз.`, "ok");
              setCounts({});
              onDone();
            } catch (e) {
              toast(e instanceof ApiError ? e.message : "Ошибка", "err");
            } finally {
              setBusy(false);
            }
          }}
        >
          Провести инвентаризацию
        </button>
      </div>
      {result && <div className="notice green small">Готово. Позиций проверено: {result.length}, с расхождением: {result.filter((x) => x.delta).length}.</div>}
    </div>
  );
}

function Moves({ items, owner }: { items: Item[]; owner: boolean }) {
  const toast = useToast();
  const [flt, setFlt] = useState({ item_id: "", type: "", date_from: "", date_to: "", q: "" });
  const [applied, setApplied] = useState(flt);
  const [exporting, setExporting] = useState(false);
  const qs = useMemo(() => {
    const p = new URLSearchParams({ limit: "300" });
    Object.entries(applied).forEach(([k, v]) => v && p.set(k, v.trim()));
    return p.toString();
  }, [applied]);
  const { data, error } = useAdmin<Move[]>(`/inventory/movements?${qs}`);
  const dateErr = flt.date_from && flt.date_to && flt.date_from > flt.date_to ? "Дата «по» раньше даты «с»" : "";
  async function exportCsv() {
    setExporting(true);
    try {
      const p = new URLSearchParams(qs);
      p.delete("limit");
      p.set("export", "csv");
      const res = await fetch(`/api/v1/admin/inventory/movements?${p}`, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } });
      if (!res.ok) throw new Error(`Ошибка ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `движения-склада-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Не удалось выгрузить", "err");
    } finally {
      setExporting(false);
    }
  }
  return (
    <>
      <div className="filters moves-filters">
        <select className="select" value={flt.item_id} onChange={(e) => setFlt({ ...flt, item_id: e.target.value })}>
          <option value="">Все позиции</option>
          {items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
        <select className="select" value={flt.type} onChange={(e) => setFlt({ ...flt, type: e.target.value })}>{MOVE_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <label className="row small" style={{ gap: 6, flexWrap: "nowrap" }}>с <input className={`input input-sm ${dateErr ? "invalid" : ""}`} type="date" value={flt.date_from} max={flt.date_to || undefined} onChange={(e) => setFlt({ ...flt, date_from: e.target.value })} /></label>
        <label className="row small" style={{ gap: 6, flexWrap: "nowrap" }}>по <input className={`input input-sm ${dateErr ? "invalid" : ""}`} type="date" value={flt.date_to} min={flt.date_from || undefined} onChange={(e) => setFlt({ ...flt, date_to: e.target.value })} /></label>
        <input className="input input-sm" placeholder="Причина или название" maxLength={80} value={flt.q} onChange={(e) => setFlt({ ...flt, q: e.target.value })} onKeyDown={(e) => e.key === "Enter" && !dateErr && setApplied(flt)} />
        <button className="btn btn-sm" disabled={!!dateErr} onClick={() => setApplied(flt)}>Показать</button>
        <button className="btn btn-sm btn-quiet" onClick={() => { const z = { item_id: "", type: "", date_from: "", date_to: "", q: "" }; setFlt(z); setApplied(z); }}>Сбросить</button>
        <button className="btn btn-sm btn-ghost" style={{ marginLeft: "auto" }} disabled={exporting} onClick={exportCsv}>{exporting ? "Готовим…" : "Скачать CSV"}</button>
      </div>
      {dateErr && <div className="field-err" style={{ marginBottom: 8 }}>{dateErr}</div>}
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Время</th><th>Позиция</th><th>Операция</th><th className="num">Изменение</th><th className="num">Остаток</th><th>Основание</th><th>Сотрудник</th>{owner && <th className="num">Цена</th>}</tr></thead>
            <tbody>
              {data.map((m) => (
                <tr key={m.id}>
                  <td className="small nowrap">{dateTime(m.at)}</td>
                  <td>{m.item}</td>
                  <td className="small">{m.type_label}</td>
                  <td className="num"><b style={{ color: m.delta > 0 ? "var(--green)" : "var(--red)" }}>{m.delta > 0 ? `+${m.delta}` : m.delta}</b></td>
                  <td className="num">{m.balance_after}</td>
                  <td className="small">{m.reason}{m.order_number ? ` · №${m.order_number}` : ""}</td>
                  <td className="small muted">{m.user}</td>
                  {owner && <td className="num small">{m.unit_cost != null ? money(m.unit_cost) : ""}</td>}
                </tr>
              ))}
              {!data.length && <tr><td colSpan={8} className="empty">Операций по фильтру нет</td></tr>}
            </tbody>
          </table>
          {data.length >= 300 && <p className="hint" style={{ padding: "8px 14px" }}>Показаны последние 300 операций — сузьте фильтр или скачайте CSV</p>}
        </div>
      )}
    </>
  );
}

function DemandView() {
  const { data, error } = useAdmin<Demand[]>("/inventory/demand");
  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <p className="muted small">Сколько материалов и букетов понадобится под подтверждённые заказы и предзаказы на будущие даты — для планирования закупок.</p>
      <div className="table-wrap">
        <table className="t">
          <thead><tr><th>Дата</th><th>Позиция</th><th className="num">Нужно</th><th className="num">Доступно сейчас</th><th></th></tr></thead>
          <tbody>
            {data.map((d, k) => (
              <tr key={k}>
                <td className="small">{dateLong(d.date)}</td>
                <td>{d.item}</td>
                <td className="num"><b>{d.planned}</b></td>
                <td className="num">{d.available_now}</td>
                <td>{d.available_now < d.planned ? <span className="badge amber">докупить</span> : <span className="badge green">хватает</span>}</td>
              </tr>
            ))}
            {!data.length && <tr><td colSpan={5} className="empty">Нет запланированной потребности</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
