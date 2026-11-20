"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { RichText } from "@/components/Faq";
import { Field } from "@/components/Field";
import { ExternalIcon, PlusIcon, XIcon } from "@/components/Icons";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import type { FaqBlock } from "@/lib/types";
import * as V from "@/lib/validate";

/* «Частые вопросы» на главной странице: блоки (темы) с вопросами и ответами.
 * Пока владелец ничего не сохранял, на сайте стандартные ответы из настроек магазина (сроки, доставка, оплата). */

type Data = { blocks: FaqBlock[]; custom: boolean };

const move = <T,>(list: T[], i: number, d: number): T[] => {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const copy = [...list];
  [copy[i], copy[j]] = [copy[j], copy[i]];
  return copy;
};

/** Проверка перед сохранением — те же правила, что на сервере (поля faq.<блок>.<вопрос>.q|a) */
function check(blocks: FaqBlock[]): V.Errors {
  const e: Record<string, string | null> = {};
  blocks.forEach((b, bi) => {
    e[`faq.${bi}.title`] = V.text(b.title, "Название блока", { max: 120 });
    b.items.forEach((it, ii) => {
      const q = it.q.trim(), a = it.a.trim();
      if (!q && !a) return;
      e[`faq.${bi}.${ii}.q`] = !q ? "Впишите вопрос" : V.text(q, "Вопрос", { max: 200 });
      e[`faq.${bi}.${ii}.a`] = !a ? "Впишите ответ" : V.text(a, "Ответ", { max: 5000 });
    });
  });
  return V.collect(e);
}

export default function FaqAdminPage() {
  const user = useStaff();
  const toast = useToast();
  const { data, error, setData } = useAdmin<Data>(user.role === "owner" ? "/faq" : null);
  const [blocks, setBlocks] = useState<FaqBlock[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string>("");

  useEffect(() => {
    if (data) {
      setBlocks(data.blocks.map((b) => ({ title: b.title, items: b.items.map((i) => ({ q: i.q, a: i.a })) })));
      setDirty(false);
    }
  }, [data]);

  // не потерять правки при закрытии вкладки
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (user.role !== "owner") return <div className="notice">Частые вопросы меняет только владелец.</div>;

  const edit = (fn: (b: FaqBlock[]) => FaqBlock[]) => {
    setBlocks((x) => (x ? fn(x) : x));
    setDirty(true);
  };
  const setItem = (bi: number, ii: number, k: "q" | "a", v: string) => {
    edit((bs) => bs.map((b, i) => (i !== bi ? b : { ...b, items: b.items.map((it, j) => (j !== ii ? it : { ...it, [k]: v })) })));
    setErrors((e) => ({ ...e, [`faq.${bi}.${ii}.${k}`]: "" }));
  };
  const setTitle = (bi: number, v: string) => {
    edit((bs) => bs.map((b, i) => (i !== bi ? b : { ...b, title: v })));
    setErrors((e) => ({ ...e, [`faq.${bi}.title`]: "" }));
  };
  // при перестановке номера полей меняются — старые подсветки ошибок сбрасываем
  const reorder = (fn: (b: FaqBlock[]) => FaqBlock[]) => {
    edit(fn);
    setErrors({});
  };

  async function save() {
    if (!blocks) return;
    const errs = check(blocks);
    setErrors(errs);
    if (V.hasErrors(errs)) {
      toast("Проверьте выделенные поля", "err");
      const first = Object.keys(errs).find((k) => errs[k]);
      if (first) document.querySelector<HTMLElement>(`[data-field="${first}"]`)?.focus();
      return;
    }
    setBusy(true);
    try {
      const r = await adminApi<Data>("/faq", { method: "PUT", body: { blocks } });
      setData(r);
      setErrors({});
      toast("Частые вопросы сохранены", "ok");
    } catch (e) {
      const msg = V.serverError(e, setErrors);
      const field = e instanceof ApiError ? (e.details?.field as string | undefined) : undefined;
      if (field) document.querySelector<HTMLElement>(`[data-field="${field}"]`)?.focus();
      toast(msg, "err");
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Вернуть стандартные вопросы? Ваши блоки и ответы будут удалены.")) return;
    setBusy(true);
    try {
      setData(await adminApi<Data>("/faq", { method: "DELETE" }));
      setErrors({});
      toast("Вернули стандартные вопросы", "ok");
    } catch (e) {
      toast(V.serverError(e), "err");
    } finally {
      setBusy(false);
    }
  }

  const count = blocks?.reduce((n, b) => n + b.items.filter((i) => i.q.trim()).length, 0) || 0;

  return (
    <>
      <PageTop title="Частые вопросы">
        <Link href="/#faq" target="_blank" className="btn btn-sm btn-ghost">На сайте <ExternalIcon /></Link>
        <button className="btn btn-sm" disabled={busy || !blocks || !dirty} onClick={save}>{busy ? "Сохраняем…" : dirty ? "Сохранить" : "Сохранено"}</button>
      </PageTop>
      <ErrorBox text={error} />
      {!blocks ? <Loading /> : (
        <div className="stack">
          <div className="notice small faq-help">
            {data?.custom
              ? <>На главной странице — ваши вопросы ({count}). Блоки показываются в этом порядке; пустой вопрос без ответа не сохранится.</>
              : <>Сейчас на сайте <b>стандартные вопросы</b> — они собраны из настроек магазина (сроки, зоны доставки, оплата). Поменяйте текст или добавьте свои и нажмите «Сохранить».</>}
            <div style={{ marginTop: 8 }}><b>Оформление ответа:</b></div>
            <ul>
              <li>пустая строка — новый абзац;</li>
              <li><code>- </code> в начале строки — пункт списка;</li>
              <li><code>**текст**</code> — <b>жирный</b>;</li>
              <li><code>[Доставка и оплата](/delivery)</code> — ссылка на страницу сайта, <code>[позвоните](tel:+73420000000)</code> — на телефон.</li>
            </ul>
          </div>

          {blocks.map((b, bi) => (
            <div className="card faq-ed-block" key={bi} data-testid="faq-block">
              <div className="faq-ed-head">
                <Field label={`Блок ${bi + 1} — название (необязательно)`} error={errors[`faq.${bi}.title`]}>
                  <input className="input" data-field={`faq.${bi}.title`} maxLength={120} placeholder="Например: Доставка и самовывоз" value={b.title} onChange={(e) => setTitle(bi, e.target.value)} />
                </Field>
                <div className="faq-ed-tools" style={{ paddingBottom: errors[`faq.${bi}.title`] ? 22 : 0 }}>
                  <button type="button" className="icon-btn" title="Блок выше" aria-label="Блок выше" disabled={bi === 0} onClick={() => reorder((bs) => move(bs, bi, -1))}>↑</button>
                  <button type="button" className="icon-btn" title="Блок ниже" aria-label="Блок ниже" disabled={bi === blocks.length - 1} onClick={() => reorder((bs) => move(bs, bi, 1))}>↓</button>
                  <button type="button" className="icon-btn" title="Удалить блок" aria-label="Удалить блок" onClick={() => {
                    if (b.items.some((i) => i.q.trim() || i.a.trim()) && !window.confirm(`Удалить блок${b.title ? ` «${b.title}»` : ""} со всеми вопросами?`)) return;
                    reorder((bs) => bs.filter((_, i) => i !== bi));
                  }}><XIcon /></button>
                </div>
              </div>

              {b.items.map((it, ii) => {
                const key = `${bi}.${ii}`;
                const bad = !!(errors[`faq.${key}.q`] || errors[`faq.${key}.a`]);
                return (
                  <div className={`faq-ed-item ${bad ? "has-err" : ""}`} key={ii}>
                    <div className="faq-ed-item-head">
                      <b>Вопрос {ii + 1}</b>
                      <div className="faq-ed-tools">
                        <button type="button" className="btn btn-sm btn-quiet" onClick={() => setPreview(preview === key ? "" : key)}>{preview === key ? "Скрыть" : "Как на сайте"}</button>
                        <button type="button" className="icon-btn" title="Выше" aria-label="Вопрос выше" disabled={ii === 0} onClick={() => reorder((bs) => bs.map((x, i) => (i !== bi ? x : { ...x, items: move(x.items, ii, -1) })))}>↑</button>
                        <button type="button" className="icon-btn" title="Ниже" aria-label="Вопрос ниже" disabled={ii === b.items.length - 1} onClick={() => reorder((bs) => bs.map((x, i) => (i !== bi ? x : { ...x, items: move(x.items, ii, 1) })))}>↓</button>
                        <button type="button" className="icon-btn" title="Удалить вопрос" aria-label="Удалить вопрос" onClick={() => reorder((bs) => bs.map((x, i) => (i !== bi ? x : { ...x, items: x.items.filter((_, j) => j !== ii) })))}><XIcon /></button>
                      </div>
                    </div>
                    <Field label="Вопрос" error={errors[`faq.${key}.q`]}>
                      <input className="input" data-field={`faq.${key}.q`} maxLength={200} placeholder="Например: Можно ли заказать букет к точному времени?" value={it.q} onChange={(e) => setItem(bi, ii, "q", e.target.value)} />
                    </Field>
                    <Field label="Ответ" error={errors[`faq.${key}.a`]}>
                      <textarea className="textarea" data-field={`faq.${key}.a`} rows={3} maxLength={5000} value={it.a} onChange={(e) => setItem(bi, ii, "a", e.target.value)} />
                    </Field>
                    {preview === key && (
                      <div className="faq-ed-preview">
                        <b>{it.q || "Вопрос"}</b>
                        <div style={{ marginTop: 6 }}>{it.a.trim() ? <RichText text={it.a} /> : <span className="muted">Ответ пока пустой</span>}</div>
                      </div>
                    )}
                  </div>
                );
              })}
              <div>
                <button type="button" className="btn btn-sm btn-outline" onClick={() => edit((bs) => bs.map((x, i) => (i !== bi ? x : { ...x, items: [...x.items, { q: "", a: "" }] })))}>
                  <PlusIcon /> Вопрос
                </button>
              </div>
            </div>
          ))}

          <div className="row-between">
            <button type="button" className="btn btn-outline" onClick={() => edit((bs) => [...bs, { title: "", items: [{ q: "", a: "" }] }])}>
              <PlusIcon /> Новый блок
            </button>
            <div className="row">
              {data?.custom && <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={reset}>Вернуть стандартные</button>}
              <button className="btn" disabled={busy || !dirty} onClick={save}>{busy ? "Сохраняем…" : "Сохранить"}</button>
            </div>
          </div>
          {!blocks.length && <div className="notice amber small">Блоков нет — после сохранения раздел «Частые вопросы» на главной не будет показан.</div>}
        </div>
      )}
    </>
  );
}
