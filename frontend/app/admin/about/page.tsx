"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { Field } from "@/components/Field";
import { ExternalIcon, PlusIcon, XIcon } from "@/components/Icons";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import type { AboutPage } from "@/lib/types";
import * as V from "@/lib/validate";

const MAX_PHOTOS = 12;

export default function AboutAdminPage() {
  const user = useStaff();
  const toast = useToast();
  const { data, error, setData } = useAdmin<AboutPage>(user.role === "owner" ? "/about" : null);
  const [f, setF] = useState<{ title: string; lead: string; text: string } | null>(null);
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const [caption, setCaption] = useState("");
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (data && !f) setF({ title: data.title, lead: data.lead, text: data.text });
  }, [data, f]);

  if (user.role !== "owner") return <div className="notice">Страницу «О нас» меняет только владелец.</div>;

  const set = (k: "title" | "lead" | "text", v: string) => {
    setF((x) => ({ ...(x as { title: string; lead: string; text: string }), [k]: v }));
    setErrors((e) => ({ ...e, [k]: "" }));
  };

  async function save() {
    if (!f) return;
    const errs = V.collect({
      title: V.text(f.title, "Заголовок", { required: true, min: 2, max: 120 }),
      lead: V.text(f.lead, "Вступление", { max: 300 }),
      text: V.text(f.text, "Текст", { max: 10000 }),
    });
    setErrors(errs);
    if (V.hasErrors(errs)) return;
    setBusy(true);
    try {
      setData(await adminApi<AboutPage>("/about", { method: "PATCH", body: f }));
      toast("Страница сохранена", "ok");
    } catch (e) {
      toast(V.serverError(e, setErrors), "err");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    if (file.size > 8 * 1024 * 1024) return toast("Файл больше 8 МБ — уменьшите фото", "err");
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return toast("Нужен JPG, PNG или WebP", "err");
    const capErr = V.text(caption, "Подпись", { max: 140 });
    if (capErr) return setErrors((e) => ({ ...e, caption: capErr }));
    const fd = new FormData();
    fd.append("image", file);
    fd.append("caption", caption.trim());
    setUploading(true);
    try {
      setData(await adminApi<AboutPage>("/about/photos", { method: "POST", form: fd }));
      setCaption("");
      toast("Фото добавлено", "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка загрузки", "err");
    } finally {
      setUploading(false);
    }
  }

  async function photoCall(path: string, method: string, body?: unknown) {
    try {
      setData(await adminApi<AboutPage>(path, { method, body }));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    }
  }
  function move(i: number, d: -1 | 1) {
    if (!data) return;
    const ids = data.photos.map((p) => p.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    photoCall("/about/photos/order", "POST", { ids });
  }

  return (
    <>
      <PageTop title="Страница «О нас»">
        <Link className="btn btn-ghost btn-sm" href="/about" target="_blank">Открыть на сайте <ExternalIcon /></Link>
      </PageTop>
      <ErrorBox text={error} />
      {!data || !f ? <Loading /> : (
        <div className="stack" style={{ gap: 20 }}>
          <section className="card stack">
            <h3 style={{ margin: 0 }}>Фото для карусели</h3>
            <p className="muted small" style={{ margin: 0 }}>До {MAX_PHOTOS} фото, лучше горизонтальные. Первое — обложка.</p>
            <div className="about-adm-grid">
              {data.photos.map((p, i) => (
                <PhotoTile key={p.id} url={p.url} caption={p.caption} first={i === 0} last={i === data.photos.length - 1}
                  onLeft={() => move(i, -1)} onRight={() => move(i, 1)}
                  onCaption={(c) => photoCall(`/about/photos/${p.id}`, "PATCH", { caption: c })}
                  onDelete={() => confirm("Удалить фото из карусели?") && photoCall(`/about/photos/${p.id}`, "DELETE")} />
              ))}
              {data.photos.length < MAX_PHOTOS && (
                <div className="about-adm-add">
                  <Field label="Подпись к новому фото" error={errors.caption} hint="Необязательно, до 140 символов">
                    <input className="input" maxLength={140} value={caption} onChange={(e) => { setCaption(e.target.value); setErrors((x) => ({ ...x, caption: "" })); }} />
                  </Field>
                  <label className={`btn btn-ghost ${uploading ? "disabled" : ""}`}>
                    <PlusIcon /> {uploading ? "Загружаем…" : "Добавить фото"}
                    <input type="file" accept="image/png,image/webp,image/jpeg" hidden disabled={uploading} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) upload(file); }} />
                  </label>
                </div>
              )}
            </div>
          </section>
          <section className="card stack">
            <h3 style={{ margin: 0 }}>Текст</h3>
            <Field label="Заголовок" error={errors.title}><input className="input" maxLength={120} value={f.title} onChange={(e) => set("title", e.target.value)} /></Field>
            <Field label="Вступление" error={errors.lead} hint={`${f.lead.length}/300`}>
              <textarea className="textarea" rows={2} maxLength={300} value={f.lead} onChange={(e) => set("lead", e.target.value)} />
            </Field>
            <Field label="Описание" error={errors.text} hint={`Пустая строка — новый абзац · ${f.text.length}/10000`}>
              <textarea className="textarea" rows={10} maxLength={10000} value={f.text} onChange={(e) => set("text", e.target.value)} />
            </Field>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" disabled={busy} onClick={save}>{busy ? "Сохраняем…" : "Сохранить текст"}</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function PhotoTile({ url, caption, first, last, onLeft, onRight, onCaption, onDelete }: {
  url: string; caption: string; first: boolean; last: boolean; onLeft: () => void; onRight: () => void; onCaption: (c: string) => void; onDelete: () => void;
}) {
  const [c, setC] = useState(caption);
  useEffect(() => setC(caption), [caption]);
  return (
    <div className="about-adm-tile">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={caption} />
      <button className="icon-btn about-adm-del" onClick={onDelete} aria-label="Удалить фото"><XIcon /></button>
      {first && <span className="badge green about-adm-cover">обложка</span>}
      <input className="input" maxLength={140} value={c} placeholder="Подпись" onChange={(e) => setC(e.target.value)} onBlur={() => c.trim() !== caption && onCaption(c.trim())} />
      <div className="row" style={{ gap: 4, justifyContent: "space-between" }}>
        <button className="btn btn-quiet btn-xs" disabled={first} onClick={onLeft} aria-label="Левее">← Раньше</button>
        <button className="btn btn-quiet btn-xs" disabled={last} onClick={onRight} aria-label="Правее">Позже →</button>
      </div>
    </div>
  );
}
