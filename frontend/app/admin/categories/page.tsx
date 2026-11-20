"use client";
import { useMemo, useState } from "react";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { Field } from "@/components/Field";
import { PlusIcon } from "@/components/Icons";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import type { AdminCategory, AdminCategoryList, Product } from "@/lib/types";
import * as V from "@/lib/validate";

type Kind = "bouquet" | "flower";
const KINDS: [Kind, string, string][] = [
  ["bouquet", "Готовые букеты", "Разделы на странице «Букеты»"],
  ["flower", "Цветы поштучно", "Разделы на странице «Цветы поштучно», зелень — тоже здесь"],
];

export default function CategoriesPage() {
  const [kind, setKind] = useState<Kind>("bouquet");
  const { data, error, setData, reload } = useAdmin<AdminCategoryList>(`/categories?kind=${kind}`);
  const toast = useToast();
  const [name, setName] = useState("");
  const [nameErr, setNameErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState<AdminCategory | null>(null);
  const [addTo, setAddTo] = useState<AdminCategory | null>(null);
  const cats = data?.categories || [];

  async function call(path: string, method: string, body?: unknown, okText?: string) {
    setBusy(true);
    try {
      const r = await adminApi<AdminCategoryList>(path, { method, body });
      setData(r);
      if (okText) toast(okText, "ok");
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    const err = V.text(name, "Название категории", { required: true, min: 2, max: 60 })
      || (cats.some((c) => c.name.toLowerCase() === name.trim().toLowerCase()) ? "Такая категория уже есть" : null);
    setNameErr(err || "");
    if (err) return;
    setBusy(true);
    try {
      setData(await adminApi<AdminCategoryList>("/categories", { body: { kind, name: name.trim() } }));
      setName("");
      toast("Категория добавлена", "ok");
    } catch (e) {
      setNameErr(V.serverError(e));
    } finally {
      setBusy(false);
    }
  }

  function move(i: number, d: -1 | 1) {
    const ids = cats.map((c) => c.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setData({ ...data!, categories: ids.map((id) => cats.find((c) => c.id === id)!) }); // сразу показываем новый порядок
    call("/categories/order", "POST", { kind, ids });
  }

  const tab = KINDS.find(([k]) => k === kind)!;
  return (
    <>
      <PageTop title="Категории витрины" />
      <div className="filters">
        <div className="seg">
          {KINDS.map(([k, l]) => <button key={k} className={kind === k ? "on" : ""} onClick={() => { setKind(k); setName(""); setNameErr(""); }}>{l}</button>)}
        </div>
      </div>
      <p className="muted small" style={{ marginTop: 0 }}>Порядок здесь — порядок вкладок на сайте.</p>
      <ErrorBox text={error} />
      <div className="card card-tight" style={{ marginBottom: 16 }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
          <Field label="Новая категория" error={nameErr} className="grow">
            <input className="input" maxLength={60} value={name} placeholder={kind === "bouquet" ? "Например: Весенние" : "Например: Гвоздика"}
              onChange={(e) => { setName(e.target.value); setNameErr(""); }} onKeyDown={(e) => e.key === "Enter" && create()} />
          </Field>
          <button className="btn" style={{ marginTop: 25 }} disabled={busy} onClick={create}><PlusIcon /> Добавить</button>
        </div>
      </div>
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th style={{ width: 90 }}>Порядок</th><th>Название</th><th className="num">Товаров</th><th></th></tr></thead>
            <tbody>
              {cats.map((c, i) => (
                <CategoryRow key={c.id} c={c} first={i === 0} last={i === cats.length - 1} busy={busy}
                  onUp={() => move(i, -1)} onDown={() => move(i, 1)}
                  onRename={(n) => call(`/categories/${c.id}`, "PATCH", { name: n }, "Категория переименована")}
                  onDelete={() => setDel(c)} onAdd={() => setAddTo(c)} taken={cats.filter((x) => x.id !== c.id).map((x) => x.name.toLowerCase())} />
              ))}
              {cats.length === 0 && <tr><td colSpan={4} className="muted small" style={{ padding: 24, textAlign: "center" }}>Категорий пока нет</td></tr>}
            </tbody>
          </table>
          {data.without_category > 0 && <p className="hint" style={{ padding: "10px 14px", margin: 0 }}>Без категории: {data.without_category} — на сайте они в разделе «Другое»</p>}
        </div>
      )}
      {del && <DeleteModal c={del} others={cats.filter((x) => x.id !== del.id)} onClose={() => setDel(null)}
        onDone={async (moveTo) => { if (await call(`/categories/${del.id}${moveTo ? `?move_to=${moveTo}` : ""}`, "DELETE", undefined, "Категория удалена")) setDel(null); }} />}
      {addTo && <AddProductsModal c={addTo} onClose={() => setAddTo(null)} onDone={() => { setAddTo(null); reload(); }} />}
    </>
  );
}

function CategoryRow({ c, first, last, busy, onUp, onDown, onRename, onDelete, onAdd, taken }: {
  c: AdminCategory; first: boolean; last: boolean; busy: boolean; taken: string[];
  onUp: () => void; onDown: () => void; onRename: (n: string) => Promise<boolean>; onDelete: () => void; onAdd: () => void;
}) {
  const [edit, setEdit] = useState<string | null>(null);
  const [err, setErr] = useState("");
  async function save() {
    if (edit === null) return;
    const e = V.text(edit, "Название", { required: true, min: 2, max: 60 }) || (taken.includes(edit.trim().toLowerCase()) ? "Такая категория уже есть" : null);
    setErr(e || "");
    if (e) return;
    if (edit.trim() === c.name || (await onRename(edit.trim()))) setEdit(null);
  }
  return (
    <tr>
      <td>
        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          <button className="btn btn-quiet btn-xs" disabled={first || busy} onClick={onUp} aria-label="Выше">↑</button>
          <button className="btn btn-quiet btn-xs" disabled={last || busy} onClick={onDown} aria-label="Ниже">↓</button>
        </div>
      </td>
      <td>
        {edit === null ? <span style={{ fontWeight: 500 }}>{c.name}</span> : (
          <div className="stack" style={{ gap: 4 }}>
            <input className={`input ${err ? "invalid" : ""}`} autoFocus maxLength={60} value={edit} onChange={(e) => { setEdit(e.target.value); setErr(""); }}
              onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEdit(null); }} />
            {err && <span className="field-err">{err}</span>}
          </div>
        )}
      </td>
      <td className="num">{c.products}</td>
      <td>
        <div className="row" style={{ gap: 6, justifyContent: "flex-end", flexWrap: "nowrap" }}>
          {edit === null ? (
            <>
              <button className="btn btn-ghost btn-xs" onClick={onAdd}>Добавить товары</button>
              <button className="btn btn-quiet btn-xs" onClick={() => setEdit(c.name)}>Переименовать</button>
              <button className="btn btn-quiet btn-xs" style={{ color: "var(--red)" }} onClick={onDelete}>Удалить</button>
            </>
          ) : (
            <>
              <button className="btn btn-xs" disabled={busy} onClick={save}>Сохранить</button>
              <button className="btn btn-quiet btn-xs" onClick={() => { setEdit(null); setErr(""); }}>Отмена</button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

function DeleteModal({ c, others, onClose, onDone }: { c: AdminCategory; others: AdminCategory[]; onClose: () => void; onDone: (moveTo: number | null) => void }) {
  const [to, setTo] = useState("");
  return (
    <Modal title={`Удалить «${c.name}»`} onClose={onClose}>
      <div className="stack">
        {c.products > 0 ? (
          <Field label={`Куда перенести товары (${c.products})`}>
            <select className="select" value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="">Оставить без категории («Другое»)</option>
              {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </Field>
        ) : <p className="muted" style={{ margin: 0 }}>В категории нет товаров.</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
          <button className="btn btn-danger" onClick={() => onDone(to ? Number(to) : null)}>Удалить категорию</button>
        </div>
      </div>
    </Modal>
  );
}

type Row = Product & { is_active: boolean; sku: string };

function AddProductsModal({ c, onClose, onDone }: { c: AdminCategory; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { data } = useAdmin<Row[]>(`/products?type=${c.kind === "bouquet" ? "bouquet" : "flower,greenery"}`);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const list = useMemo(() => (data || []).filter((p) => p.category !== c.name && (!q || p.name.toLowerCase().includes(q.toLowerCase()))), [data, q, c.name]);
  const toggle = (id: number) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  async function save() {
    setBusy(true);
    try {
      await adminApi(`/categories/${c.id}/products`, { body: { product_ids: Array.from(sel) } });
      toast(`Добавлено в «${c.name}»: ${sel.size}`, "ok");
      onDone();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
      setBusy(false);
    }
  }
  return (
    <Modal title={`Добавить в «${c.name}»`} onClose={onClose} wide>
      <div className="stack">
        <input className="input" placeholder="Найти товар" value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} />
        {!data ? <Loading /> : (
          <div className="pick-list">
            {list.map((p) => (
              <label key={p.id} className="pick-row">
                <input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} />
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {p.image ? <img className="thumb" src={p.image} alt="" /> : <span className="thumb" />}
                <span className="grow"><b style={{ fontWeight: 500 }}>{p.name}</b><span className="tiny muted" style={{ display: "block" }}>{p.category ? `сейчас: ${p.category}` : "без категории"}{!p.is_active && " · скрыт"}</span></span>
              </label>
            ))}
            {list.length === 0 && <p className="muted small">Все товары этого раздела уже в категории</p>}
          </div>
        )}
        <div className="row-between">
          <span className="small muted">Выбрано: {sel.size}. Товар может быть только в одной категории — он переедет сюда</span>
          <div className="row">
            <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
            <button className="btn" disabled={busy || sel.size === 0} onClick={save}>Добавить</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
