"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { CropEditor } from "@/components/admin/CropEditor";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { ColorInput, Field } from "@/components/Field";
import { PlusIcon, XIcon } from "@/components/Icons";
import { useToast } from "@/components/Toast";
import { adminApi, toKopecks, toRub, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import type { AdminCategoryList, CropBox, Product } from "@/lib/types";
import * as V from "@/lib/validate";

type Row = Product & { is_active: boolean; sku: string };
type Comp = { item_id: number; name?: string; category?: string; quantity: number; available?: number };
type Full = Row & {
  description: string; height_cm: number | null; allow_made_to_order: boolean; constructor_enabled: boolean; sort_order: number;
  images: { id: number; url: string }[]; purchase_price?: number; min_stock: number; unit_code: string;
  constructor_image_note?: string; constructor_source?: string | null; constructor_crop?: CropBox | null;
  stock: { quantity: number; reserved: number; free: number };
  components?: Comp[]; recipe_id?: number | null; can_assemble?: number;
};
type Material = { id: number; name: string; category: string; category_label: string; available: number; unit_label: string; is_active: boolean };

const TYPES: [string, string][] = [["", "Все типы"], ["bouquet", "Букеты"], ["flower", "Цветы"], ["greenery", "Зелень"], ["packaging", "Упаковка"], ["ribbon", "Ленты"], ["card", "Открытки"], ["addon", "Дополнения"]];
const UNITS: [string, string][] = [["pcs", "шт"], ["stem", "стебель"], ["branch", "ветка"], ["sheet", "лист"], ["cut", "отрез"]];
/** Стиль материала: по нему конструктор рисует упаковку и ленту */
const STYLES: Record<string, string[]> = {
  packaging: ["Бумага", "Плёнка", "Фетр", "Коробка"],
  ribbon: ["Атлас", "Шёлк", "Шпагат", "Органза"],
};
const DEFAULT_UNIT: Record<string, string> = { flower: "stem", greenery: "branch", packaging: "sheet", ribbon: "cut" };
const kindOf = (t: string) => (t === "bouquet" ? "bouquet" : t === "flower" || t === "greenery" ? "flower" : null);

export default function ProductsPage() {
  const [type, setType] = useState("bouquet");
  const [q, setQ] = useState("");
  const { data, error, reload } = useAdmin<Row[]>(`/products${type ? `?type=${type}` : ""}`);
  const [edit, setEdit] = useState<number | null>(null);
  const [create, setCreate] = useState(false);
  const list = (data || []).filter((p) => !q || `${p.name} ${p.sku} ${p.category}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <PageTop title="Товары">
        <Link className="btn btn-ghost btn-sm" href="/admin/categories">Категории</Link>
        <button className="btn btn-sm" onClick={() => setCreate(true)}><PlusIcon /> Новый товар</button>
      </PageTop>
      <div className="filters">
        <div className="seg">
          {TYPES.map(([v, l]) => <button key={v} className={type === v ? "on" : ""} onClick={() => setType(v)}>{l}</button>)}
        </div>
        <input className="input" placeholder="Название, артикул или категория" value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} />
      </div>
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th></th><th>Название</th><th>Артикул</th><th>Тип</th><th className="num">Цена</th><th className="num">Доступно</th><th>Статус</th></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} className="click" onClick={() => setEdit(p.id)}>
                  <td style={{ width: 56 }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {p.image ? <img className="thumb" src={p.image} alt="" /> : p.constructor_image ? <img className="thumb" style={{ objectFit: "contain" }} src={p.constructor_image} alt="" /> : <div className="thumb" style={p.color_hex ? { background: p.color_hex } : undefined} />}
                  </td>
                  <td><span style={{ fontWeight: 500 }}>{p.name}</span><div className="tiny muted">{[p.category, p.species].filter(Boolean).join(" · ")}</div></td>
                  <td className="small muted">{p.sku}</td>
                  <td className="small">{p.type_label}</td>
                  <td className="num">{money(p.price)}</td>
                  <td className="num">{p.available}{p.made_to_order && <div className="tiny muted">под заказ</div>}</td>
                  <td>
                    {p.is_active ? <span className="badge green">на сайте</span> : <span className="badge gray">скрыт</span>}
                    {p.is_featured && <span className="badge lilac" style={{ marginLeft: 4 }}>хит</span>}
                  </td>
                </tr>
              ))}
              {list.length === 0 && <tr><td colSpan={7} className="muted small" style={{ padding: 24, textAlign: "center" }}>Ничего не найдено</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {edit && <EditModal id={edit} onClose={() => setEdit(null)} onSaved={reload} />}
      {create && <CreateModal defaultType={type || "bouquet"} onClose={() => setCreate(false)} onCreated={(id) => { reload(); setCreate(false); setEdit(id); }} />}
    </>
  );
}

function useMaterials(enabled: boolean) {
  const { data } = useAdmin<Material[]>(enabled ? "/inventory" : null);
  return useMemo(() => (data || []).filter((m) => m.category !== "bouquet" && m.is_active !== false), [data]);
}

function useCategoryNames(type: string) {
  const kind = kindOf(type);
  const { data } = useAdmin<AdminCategoryList>(kind ? `/categories?kind=${kind}` : null);
  return kind ? (data?.categories || []).map((c) => c.name) : null;
}

function CategorySelect({ type, value, onChange, error }: { type: string; value: string; onChange: (v: string) => void; error?: string }) {
  const names = useCategoryNames(type);
  if (!names) {
    return (
      <Field label="Подпись группы" error={error} hint="Для упаковки, лент и открыток — свободная подпись, например «Для роз»">
        <input className="input" value={value} maxLength={60} onChange={(e) => onChange(e.target.value)} />
      </Field>
    );
  }
  const list = value && !names.includes(value) ? [value, ...names] : names;
  return (
    <Field label="Категория на витрине" error={error} hint={<>Список правится в разделе <Link href="/admin/categories" target="_blank">«Категории»</Link></>}>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Без категории («Другое»)</option>
        {list.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
    </Field>
  );
}

function StyleSelect({ type, value, onChange, error }: { type: string; value: string; onChange: (v: string) => void; error?: string }) {
  const styles = STYLES[type];
  if (!styles) return null;
  return (
    <Field label={type === "packaging" ? "Материал упаковки" : "Тип ленты"} error={error} hint="По нему конструктор рисует эскиз букета">
      <select className="select" value={styles.includes(value) ? value : ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Определить по названию</option>
        {styles.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </Field>
  );
}

function RecipeEditor({ rows, onChange, materials, error }: { rows: Comp[]; onChange: (r: Comp[]) => void; materials: Material[]; error?: string }) {
  const byId = new Map(materials.map((m) => [m.id, m]));
  const groups = Array.from(new Set(materials.map((m) => m.category_label)));
  const used = new Set(rows.map((r) => r.item_id));
  return (
    <div className="stack">
      {rows.map((r, k) => (
        <div className="comp-row" key={k}>
          <select className="select" value={r.item_id || ""} onChange={(e) => onChange(rows.map((x, i) => (i === k ? { ...x, item_id: Number(e.target.value) } : x)))}>
            <option value="">Выберите материал</option>
            {groups.map((g) => (
              <optgroup key={g} label={g}>
                {materials.filter((m) => m.category_label === g).map((m) => (
                  <option key={m.id} value={m.id} disabled={m.id !== r.item_id && used.has(m.id)}>{m.name} · в наличии {m.available}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <input className="input" type="number" min={1} max={500} step={1} value={r.quantity} onChange={(e) => onChange(rows.map((x, i) => (i === k ? { ...x, quantity: Math.min(500, Math.max(1, Math.round(Number(e.target.value)) || 1)) } : x)))} aria-label="Количество" />
          <button type="button" className="icon-btn" onClick={() => onChange(rows.filter((_, i) => i !== k))} aria-label="Убрать строку"><XIcon /></button>
          {r.item_id && byId.get(r.item_id) && byId.get(r.item_id)!.available < r.quantity ? (
            <div className="hint" style={{ gridColumn: "1 / -1", color: "var(--amber)" }}>Сейчас в наличии только {byId.get(r.item_id)!.available}</div>
          ) : null}
        </div>
      ))}
      {error && <span className="field-err">{error}</span>}
      <div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange([...rows, { item_id: 0, quantity: 1 }])}><PlusIcon /> Добавить материал</button>
      </div>
    </div>
  );
}

type Form = Record<string, string | boolean>;

/** Проверка карточки товара до отправки — те же пределы, что на сервере */
function validateProduct(f: Form, type: string, opts: { canPrice: boolean; owner: boolean }): V.Errors {
  return V.collect({
    name: V.text(f.name as string, "Название", { required: true, min: 2, max: 160 }),
    short_description: V.text(f.short_description as string, "Краткое описание", { max: 255 }),
    description: V.text(f.description as string, "Описание", { max: 5000 }),
    price: opts.canPrice ? V.rub(f.price as string, "Цена продажи", { required: true, max: 1_000_000 }) : null,
    purchase_price: opts.owner ? V.rub(f.purchase_price as string, "Закупочная цена", { required: false }) : null,
    stock: V.int(f.stock as string, "Остаток", { required: false, min: 0, max: 100000 }),
    min_stock: V.int(f.min_stock as string, "Мин. остаток", { required: false, min: 0, max: 100000 }),
    height_cm: type === "bouquet" ? V.int(f.height_cm as string, "Высота", { required: false, min: 5, max: 300 }) : null,
    color: V.text(f.color as string, "Цвет", { max: 40 }),
    color_hex: V.hex(f.color_hex as string, "Оттенок"),
    species: V.text(f.species as string, "Вид", { max: 60 }),
  });
}

function EditModal({ id, onClose, onSaved }: { id: number; onClose: () => void; onSaved: () => void }) {
  const user = useStaff();
  const toast = useToast();
  const { data: p, error, setData } = useAdmin<Full>(`/products/${id}`);
  const [form, setForm] = useState<Form | null>(null);
  const [comps, setComps] = useState<Comp[] | null>(null);
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const owner = user.role === "owner";
  const canPrice = owner || user.role === "florist";
  const materials = useMaterials(p?.type === "bouquet");

  useEffect(() => {
    if (!p || form) return;
    setForm({
      name: p.name, category: p.category, species: p.species || "", short_description: p.short_description, description: p.description,
      height_cm: p.height_cm ? String(p.height_cm) : "", is_active: p.is_active, is_featured: p.is_featured,
      allow_made_to_order: p.allow_made_to_order, constructor_enabled: p.constructor_enabled,
      price: toRub(p.price), purchase_price: toRub(p.purchase_price ?? null), min_stock: String(p.min_stock), color: p.color, color_hex: p.color_hex,
      stock: String(p.stock?.quantity ?? 0), unit: p.unit_code || "pcs", sku: p.sku,
    });
    setComps((p.components || []).map((c) => ({ item_id: c.item_id, quantity: c.quantity })));
  }, [p, form]);
  const set = (k: string, v: string | boolean) => {
    setForm((f) => ({ ...(f || {}), [k]: v }));
    setErrors((e) => ({ ...e, [k]: "" }));
  };

  async function save() {
    if (!form || !p) return;
    const errs = V.collect({ ...validateProduct(form, p.type, { canPrice, owner }), sku: V.sku(form.sku as string) });
    setErrors(errs);
    if (V.hasErrors(errs)) {
      toast("Проверьте выделенные поля", "err");
      return;
    }
    setBusy(true);
    const body: Record<string, unknown> = {
      name: form.name, category: form.category, short_description: form.short_description, description: form.description,
      is_active: form.is_active, is_featured: form.is_featured, allow_made_to_order: form.allow_made_to_order,
      constructor_enabled: form.constructor_enabled, color: form.color, color_hex: form.color_hex, species: form.species,
      min_stock: Number(form.min_stock || 0), unit: form.unit,
    };
    if (p.type === "bouquet") body.height_cm = form.height_cm ? Number(form.height_cm) : "";
    if (form.sku && form.sku !== p.sku) body.sku = form.sku;
    const price = toKopecks(form.price as string);
    if (canPrice && price !== p.price) body.price = price;
    if (owner && toKopecks(form.purchase_price as string) !== (p.purchase_price ?? null)) body.purchase_price = toKopecks(form.purchase_price as string) || 0;
    const stock = Number(form.stock);
    if (form.stock !== "" && Number.isFinite(stock) && stock !== p.stock.quantity) body.stock = stock;
    if (p.type === "bouquet" && comps) {
      const clean = comps.filter((c) => c.item_id && c.quantity > 0).map((c) => ({ item_id: c.item_id, quantity: c.quantity }));
      const before = JSON.stringify((p.components || []).map((c) => ({ item_id: c.item_id, quantity: c.quantity })));
      if (JSON.stringify(clean) !== before) body.components = clean;
    }
    try {
      const r = await adminApi<Full>(`/products/${id}`, { method: "PATCH", body });
      setData(r);
      toast("Товар сохранён", "ok");
      onSaved();
      onClose();
    } catch (e) {
      toast(V.serverError(e, setErrors), "err");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!p) return;
    const ask = owner
      ? `Удалить «${p.name}» навсегда? Карточка и фото удалятся, товар пропадёт с сайта, из ботов и корзин. В прошлых заказах сохранятся название и цена. Отменить удаление нельзя.`
      : `Удалить «${p.name}»? Если товар уже продавался, он будет скрыт, а история сохранится.`;
    if (!confirm(ask)) return;
    try {
      const r = await adminApi<{ message: string }>(`/products/${id}`, { method: "DELETE" });
      toast(r.message, "ok");
      onSaved();
      onClose();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }

  async function upload(file: File) {
    const fd = new FormData();
    fd.append("image", file);
    try {
      await adminApi(`/products/${id}/images`, { method: "POST", form: fd });
      setData(await adminApi<Full>(`/products/${id}`));
      toast("Фото загружено", "ok");
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка загрузки", "err");
    }
  }

  const [removeBg, setRemoveBg] = useState(true);
  const [cutNote, setCutNote] = useState("");
  const [cutBusy, setCutBusy] = useState(false);
  async function uploadCut(file: File) {
    const fd = new FormData();
    fd.append("image", file);
    fd.append("remove_background", removeBg ? "true" : "false");
    setCutBusy(true);
    try {
      const r = await adminApi<Full>(`/products/${id}/constructor-image`, { method: "POST", form: fd });
      setData(r);
      setCutNote(r.constructor_image_note || "");
      toast("Фото для конструктора обновлено", "ok");
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка загрузки", "err");
    } finally {
      setCutBusy(false);
    }
  }
  async function saveCrop(c: CropBox) {
    setCutBusy(true);
    try {
      const r = await adminApi<Full>(`/products/${id}/constructor-image/crop`, { method: "POST", body: c });
      setData(r);
      setCutNote("");
      toast("Кадр бутона сохранён", "ok");
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    } finally {
      setCutBusy(false);
    }
  }
  async function removeCut() {
    try {
      setData(await adminApi<Full>(`/products/${id}/constructor-image`, { method: "DELETE" }));
      setCutNote("");
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }

  async function removeImage(imgId: number) {
    try {
      await adminApi(`/product-images/${imgId}`, { method: "DELETE" });
      setData(await adminApi<Full>(`/products/${id}`));
      onSaved();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }

  const bouquet = p?.type === "bouquet";
  const flowerLike = p?.type === "flower" || p?.type === "greenery";
  const texture = p?.type === "packaging";
  const material = p?.type === "packaging" || p?.type === "ribbon";
  const visibleReason = p && form ? availabilityNote(p, form) : null;

  return (
    <Modal title={p ? p.name : "Товар"} onClose={onClose} wide>
      <ErrorBox text={error} />
      {!p || !form ? <Loading /> : (
        <div className="stack">
          <div className="row" style={{ alignItems: "flex-start" }}>
            {p.images.map((im) => (
              <div key={im.id} style={{ position: "relative" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={im.url} alt="" style={{ width: 96, height: 120, objectFit: "cover", borderRadius: 12 }} />
                <button className="icon-btn" style={{ position: "absolute", top: 4, right: 4, width: 28, height: 28 }} onClick={() => removeImage(im.id)} aria-label="Удалить фото"><XIcon /></button>
              </div>
            ))}
            <label className="btn btn-ghost" style={{ height: 120, width: 96, borderRadius: 12, flexDirection: "column", whiteSpace: "normal", fontSize: 12 }}>
              <PlusIcon /> Фото для витрины
              <input type="file" accept="image/png,image/webp,image/jpeg" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
            </label>
          </div>
          <div className="form-grid">
            <Field label="Название" error={errors.name}><input className="input" maxLength={160} value={form.name as string} onChange={(e) => set("name", e.target.value)} /></Field>
            <CategorySelect type={p.type} value={form.category as string} onChange={(v) => set("category", v)} error={errors.category} />
            <Field label="Краткое описание" full error={errors.short_description} hint="Одна строка под названием в каталоге, до 255 символов">
              <input className="input" maxLength={255} value={form.short_description as string} onChange={(e) => set("short_description", e.target.value)} />
            </Field>
            <Field label="Описание" full error={errors.description}><textarea className="textarea" maxLength={5000} value={form.description as string} onChange={(e) => set("description", e.target.value)} /></Field>
            <Field label="Цена продажи, ₽" error={errors.price}>
              <input className="input" inputMode="decimal" disabled={!canPrice} value={form.price as string} onChange={(e) => set("price", e.target.value)} />
            </Field>
            {owner ? (
              <Field label="Закупочная цена, ₽" error={errors.purchase_price}>
                <input className="input" inputMode="decimal" value={form.purchase_price as string} onChange={(e) => set("purchase_price", e.target.value)} />
              </Field>
            ) : (
              <div className="field"><span>Закупочная цена</span><div className="hint" style={{ paddingTop: 12 }}>видит и меняет только владелец</div></div>
            )}
            <Field label={`Остаток на складе, ${UNITS.find(([u]) => u === form.unit)?.[1] || "шт"}`} error={errors.stock}
              hint={`Сейчас ${p.stock.quantity}, в резерве ${p.stock.reserved}. Изменение попадёт в журнал склада как пересчёт`}>
              <input className="input" type="number" min={0} max={100000} step={1} value={form.stock as string} onChange={(e) => set("stock", e.target.value)} />
            </Field>
            <Field label="Мин. остаток для уведомления" error={errors.min_stock}>
              <input className="input" type="number" min={0} max={100000} step={1} value={form.min_stock as string} onChange={(e) => set("min_stock", e.target.value)} />
            </Field>
            <Field label="Единица учёта" error={errors.unit}>
              <select className="select" value={form.unit as string} onChange={(e) => set("unit", e.target.value)}>
                {UNITS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Артикул" error={errors.sku} hint="Латиница, цифры и дефис">
              <input className="input" maxLength={32} value={form.sku as string} onChange={(e) => set("sku", e.target.value.toUpperCase())} />
            </Field>
            {bouquet ? (
              <Field label="Высота, см" error={errors.height_cm}><input className="input" type="number" min={5} max={300} value={form.height_cm as string} onChange={(e) => set("height_cm", e.target.value)} /></Field>
            ) : (
              <>
                <Field label="Цвет (название)" error={errors.color}>
                  <input className="input" maxLength={40} value={form.color as string} placeholder="Например: лиловый" onChange={(e) => set("color", e.target.value)} />
                </Field>
                <Field label="Оттенок на эскизе" error={errors.color_hex} hint={material ? "Им окрашивается упаковка или лента в конструкторе" : "Цвет точки на схеме, если нет фото"}>
                  <ColorInput value={form.color_hex as string} invalid={!!errors.color_hex} onChange={(v) => set("color_hex", v)} />
                </Field>
              </>
            )}
            {flowerLike && (
              <Field label="Вид для конструктора" error={errors.species} hint="Например: Роза, Пион, Эвкалипт">
                <input className="input" maxLength={60} value={form.species as string} onChange={(e) => set("species", e.target.value)} />
              </Field>
            )}
            {material && <StyleSelect type={p.type} value={form.species as string} onChange={(v) => set("species", v)} error={errors.species} />}
          </div>

          {(flowerLike || texture) && (
            <div className="card card-tight cut-card">
              {flowerLike && p.constructor_source ? (
                <div className="cut-editor-grid">
                  <CropEditor key={p.constructor_source + JSON.stringify(p.constructor_crop)} src={p.constructor_source} crop={p.constructor_crop || null} busy={cutBusy} onSave={saveCrop} />
                  <div className="cut-result">
                    <b style={{ fontWeight: 600 }}>В конструкторе</b>
                    <div className="cut-preview">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      {p.constructor_image ? <img src={p.constructor_image} alt="Вырезка для конструктора" /> : <span className="tiny muted">нет</span>}
                    </div>
                    {cutNote && <div className="notice small">{cutNote}</div>}
                    <CutButtons p={p} busy={cutBusy} removeBg={removeBg} setRemoveBg={setRemoveBg} onFile={uploadCut} onRemove={removeCut} texture={false} />
                  </div>
                </div>
              ) : (
                <>
                  <div className={`cut-preview ${texture ? "tex" : ""}`}>
                    {p.constructor_image ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={p.constructor_image} alt="Фото для конструктора" />
                    ) : (
                      <span className="tiny muted">нет фото</span>
                    )}
                  </div>
                  <div className="cut-body">
                    <b style={{ fontWeight: 600 }}>Фото для конструктора</b>
                    <span className="small muted">
                      {texture
                        ? "Фрагмент материала крупно, без складок — из него сайт «шьёт» упаковку на эскизе букета."
                        : "Любое фото цветка: фон уберёт нейросеть, бутон выделится автоматически, рамку можно поправить."}
                      {!p.constructor_image && " Пока фото нет, на эскизе рисуется схема цветом из карточки."}
                    </span>
                    {cutNote && <div className="notice small">{cutNote}</div>}
                    <CutButtons p={p} busy={cutBusy} removeBg={removeBg} setRemoveBg={setRemoveBg} onFile={uploadCut} onRemove={removeCut} texture={texture} />
                  </div>
                </>
              )}
            </div>
          )}

          {bouquet && comps && (
            <div className="card card-tight" style={{ background: "var(--sunk)" }}>
              <div className="row-between" style={{ marginBottom: 12 }}>
                <b style={{ fontWeight: 600 }}>Рецептура букета</b>
                <span className="small muted">Из текущих остатков можно собрать: <b className="num" style={{ color: "var(--ink)" }}>{p.can_assemble ?? 0}</b></span>
              </div>
              <RecipeEditor rows={comps} onChange={setComps} materials={materials} error={errors.components} />
              <label className="checkbox" style={{ marginTop: 12 }}>
                <input type="checkbox" checked={form.allow_made_to_order as boolean} onChange={(e) => set("allow_made_to_order", e.target.checked)} /> Собирать под заказ по рецептуре, когда готовых нет
              </label>
            </div>
          )}

          <div className="row">
            <label className="checkbox"><input type="checkbox" checked={form.is_active as boolean} onChange={(e) => set("is_active", e.target.checked)} /> Показывать на сайте и в ботах</label>
            <label className="checkbox"><input type="checkbox" checked={form.is_featured as boolean} onChange={(e) => set("is_featured", e.target.checked)} /> Хит, показывать на главной</label>
            {!bouquet && p.type !== "addon" && p.type !== "card" && <label className="checkbox"><input type="checkbox" checked={form.constructor_enabled as boolean} onChange={(e) => set("constructor_enabled", e.target.checked)} /> Доступно в конструкторе</label>}
            {p.type === "card" && <label className="checkbox"><input type="checkbox" checked={form.constructor_enabled as boolean} onChange={(e) => set("constructor_enabled", e.target.checked)} /> Предлагать в конструкторе</label>}
          </div>
          {visibleReason && <div className="notice amber small">{visibleReason}</div>}
          <div className="row-between">
            <span className="row" style={{ gap: 16 }}>
              <span className="muted small">Доступно покупателям {p.available}</span>
              <button type="button" className="danger-link" onClick={remove}>{owner ? "Удалить навсегда" : "Удалить товар"}</button>
            </span>
            <div className="row">
              <button className="btn btn-ghost" onClick={onClose}>Закрыть</button>
              <button className="btn" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : "Сохранить"}</button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function CutButtons({ p, busy, removeBg, setRemoveBg, onFile, onRemove, texture }: {
  p: Full; busy: boolean; removeBg: boolean; setRemoveBg: (v: boolean) => void; onFile: (f: File) => void; onRemove: () => void; texture: boolean;
}) {
  return (
    <>
      {!texture && (
        <label className="checkbox small"><input type="checkbox" checked={removeBg} onChange={(e) => setRemoveBg(e.target.checked)} /> Убрать фон автоматически</label>
      )}
      <div className="row" style={{ gap: 8 }}>
        <label className={`btn btn-ghost btn-sm ${busy ? "disabled" : ""}`}>
          {busy ? "Обрабатываем…" : p.constructor_image ? "Заменить фото" : "Загрузить фото"}
          <input type="file" accept="image/png,image/webp,image/jpeg" hidden disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onFile(f); }} />
        </label>
        {p.constructor_image && <button className="btn btn-quiet btn-sm" onClick={onRemove}>Удалить</button>}
      </div>
    </>
  );
}

/** Почему покупатель увидит «Нет в наличии» — подсказка для флориста */
function availabilityNote(p: Full, form: Form): string | null {
  if (!form.is_active) return "Товар скрыт: покупатели его не видят";
  const stock = Number(form.stock || 0) - p.stock.reserved;
  if (stock > 0) return null;
  if (p.type === "bouquet") {
    if (form.allow_made_to_order && (p.can_assemble ?? 0) > 0) return null;
    if (form.allow_made_to_order) return "Покупатели увидят «Нет в наличии»: по рецептуре не хватает материалов. Пополните склад или поправьте состав";
    return "Покупатели увидят «Нет в наличии»: укажите остаток готовых букетов или включите сборку под заказ по рецептуре";
  }
  return "Покупатели увидят «Нет в наличии»: укажите остаток на складе";
}

function CreateModal({ defaultType, onClose, onCreated }: { defaultType: string; onClose: () => void; onCreated: (id: number) => void }) {
  const user = useStaff();
  const toast = useToast();
  const [f, setF] = useState<Record<string, string | boolean>>({
    type: defaultType, name: "", category: "", species: "", short_description: "", price: "", purchase_price: "", stock: "",
    unit: DEFAULT_UNIT[defaultType] || "pcs", is_active: true, allow_made_to_order: defaultType === "bouquet", color: "", color_hex: "",
    auto_cut: true,
  });
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState("");
  const owner = user.role === "owner";
  const type = f.type as string;
  const flowerLike = type === "flower" || type === "greenery";
  const material = type === "packaging" || type === "ribbon";
  const set = (k: string, v: string | boolean) => {
    setF((x) => ({ ...x, [k]: v }));
    setErrors((e) => ({ ...e, [k]: "" }));
  };
  useEffect(() => {
    if (!photo) return setPreview("");
    const u = URL.createObjectURL(photo);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [photo]);

  function pickPhoto(file: File | undefined) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) return setErrors((e) => ({ ...e, photo: "Файл больше 8 МБ — уменьшите фото" }));
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return setErrors((e) => ({ ...e, photo: "Нужен JPG, PNG или WebP" }));
    setErrors((e) => ({ ...e, photo: "" }));
    setPhoto(file);
  }

  async function submit() {
    const errs = validateProduct({ ...f, min_stock: "" }, type, { canPrice: true, owner });
    setErrors(errs);
    if (V.hasErrors(errs)) return;
    setBusy("Создаём товар…");
    let id: number | null = null;
    try {
      const body: Record<string, unknown> = {
        type, name: (f.name as string).trim(), category: f.category, short_description: f.short_description, unit: f.unit,
        price: toKopecks(f.price as string), is_active: f.is_active, allow_made_to_order: type === "bouquet" ? f.allow_made_to_order : false,
        stock: f.stock === "" ? undefined : Number(f.stock),
      };
      if ((flowerLike || material) && f.species) body.species = f.species;
      if (type !== "bouquet") Object.assign(body, { color: f.color, color_hex: f.color_hex });
      if (owner && f.purchase_price) body.purchase_price = toKopecks(f.purchase_price as string);
      const r = await adminApi<{ id: number }>("/products", { body });
      id = r.id;
      if (photo) {
        // фото витрины — для всего, кроме упаковки (у неё фото = текстура для эскиза)
        if (type !== "packaging") {
          const fd = new FormData();
          fd.append("image", photo);
          setBusy("Загружаем фото…");
          await adminApi(`/products/${id}/images`, { method: "POST", form: fd });
        }
        if ((flowerLike && f.auto_cut) || type === "packaging") {
          const fd = new FormData();
          fd.append("image", photo);
          fd.append("remove_background", "true");
          setBusy(flowerLike ? "Вырезаем цветок из фото…" : "Готовим текстуру…");
          await adminApi(`/products/${id}/constructor-image`, { method: "POST", form: fd });
        }
      }
      toast(flowerLike && photo && f.auto_cut ? "Товар создан, вырезка для конструктора готова — проверьте рамку" : "Товар создан", "ok");
      onCreated(id);
    } catch (e) {
      if (id) {
        toast(`Товар создан, но фото не обработано: ${e instanceof ApiError ? e.message : "ошибка"}`, "err");
        onCreated(id);
      } else {
        toast(V.serverError(e, setErrors), "err");
        setBusy("");
      }
    }
  }

  return (
    <Modal title="Новый товар" onClose={onClose} wide>
      <div className="form-grid">
        <Field label="Тип">
          <select className="select" value={type} onChange={(e) => setF({ ...f, type: e.target.value, category: "", species: "", unit: DEFAULT_UNIT[e.target.value] || "pcs", allow_made_to_order: e.target.value === "bouquet" })}>
            {TYPES.slice(1).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field label="Название *" error={errors.name}><input className="input" maxLength={160} value={f.name as string} onChange={(e) => set("name", e.target.value)} autoFocus /></Field>
        <CategorySelect type={type} value={f.category as string} onChange={(v) => set("category", v)} error={errors.category} />
        <Field label="Единица учёта">
          <select className="select" value={f.unit as string} onChange={(e) => set("unit", e.target.value)}>
            {UNITS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        {flowerLike && (
          <Field label="Вид для конструктора" error={errors.species} hint="Например: Роза, Тюльпан, Эвкалипт">
            <input className="input" maxLength={60} value={f.species as string} onChange={(e) => set("species", e.target.value)} />
          </Field>
        )}
        {material && <StyleSelect type={type} value={f.species as string} onChange={(v) => set("species", v)} />}
        {type !== "bouquet" && (
          <>
            <Field label="Цвет (название)" error={errors.color}><input className="input" maxLength={40} value={f.color as string} placeholder="Например: пудровый" onChange={(e) => set("color", e.target.value)} /></Field>
            <Field label="Оттенок на эскизе" error={errors.color_hex}><ColorInput value={f.color_hex as string} invalid={!!errors.color_hex} onChange={(v) => set("color_hex", v)} /></Field>
          </>
        )}
        <Field label="Краткое описание" full error={errors.short_description}><input className="input" maxLength={255} value={f.short_description as string} onChange={(e) => set("short_description", e.target.value)} /></Field>
        <Field label="Цена продажи, ₽ *" error={errors.price}><input className="input" inputMode="decimal" value={f.price as string} onChange={(e) => set("price", e.target.value)} /></Field>
        {owner ? (
          <Field label="Закупка, ₽" error={errors.purchase_price}><input className="input" inputMode="decimal" value={f.purchase_price as string} onChange={(e) => set("purchase_price", e.target.value)} /></Field>
        ) : (
          <div className="field"><span>Закупка</span><div className="hint" style={{ paddingTop: 12 }}>заполняет владелец</div></div>
        )}
        <Field label="Остаток на складе" error={errors.stock}><input className="input" type="number" min={0} max={100000} step={1} value={f.stock as string} placeholder="0" onChange={(e) => set("stock", e.target.value)} /></Field>
        <Field label={type === "packaging" ? "Фото материала" : "Фото"} error={errors.photo} full
          hint={flowerLike ? "Цветок целиком на любом фоне: сайт сам уберёт фон и выделит бутон для конструктора" : type === "packaging" ? "Крупный план бумаги или плёнки — станет текстурой упаковки на эскизе" : "Появится на витрине; позже можно добавить ещё"}>
          <span className="drop-photo">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {preview ? <img src={preview} alt="" /> : <PlusIcon />}
            <span className="small">{photo ? photo.name : "Выбрать файл JPG, PNG или WebP до 8 МБ"}</span>
            <input type="file" accept="image/png,image/webp,image/jpeg" hidden onChange={(e) => { pickPhoto(e.target.files?.[0]); e.target.value = ""; }} />
          </span>
        </Field>
      </div>
      <div className="stack" style={{ margin: "16px 0" }}>
        {flowerLike && (
          <label className="checkbox"><input type="checkbox" checked={f.auto_cut as boolean} onChange={(e) => set("auto_cut", e.target.checked)} /> Сделать из фото вырезку для конструктора</label>
        )}
        <label className="checkbox"><input type="checkbox" checked={f.is_active as boolean} onChange={(e) => set("is_active", e.target.checked)} /> Показывать на сайте и в ботах</label>
        {type === "bouquet" && (
          <label className="checkbox"><input type="checkbox" checked={f.allow_made_to_order as boolean} onChange={(e) => set("allow_made_to_order", e.target.checked)} /> Собирать под заказ по рецептуре</label>
        )}
        <p className="hint" style={{ margin: 0 }}>
          {type === "bouquet"
            ? "После создания откроется карточка: добавьте рецептуру. Букет доступен покупателям, если есть готовые или хватает материалов по рецептуре"
            : flowerLike || material ? "Цветы, зелень, упаковка и ленты сразу появляются в конструкторе букета" : "После создания откроется карточка товара"}
        </p>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-ghost" onClick={onClose} disabled={!!busy}>Отмена</button>
        <button className="btn" disabled={!!busy} onClick={submit}>{busy || "Создать"}</button>
      </div>
    </Modal>
  );
}
