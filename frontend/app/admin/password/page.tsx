"use client";
import { useEffect, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { PageTop } from "@/components/admin/ui";
import { Field } from "@/components/Field";
import { useToast } from "@/components/Toast";
import { adminApi } from "@/lib/admin";
import * as V from "@/lib/validate";

function strength(p: string) {
  let s = 0;
  if (p.length >= 10) s++;
  if (p.length >= 14) s++;
  if (/[a-zа-яё]/.test(p) && /[A-ZА-ЯЁ]/.test(p)) s++;
  if (/\d/.test(p)) s++;
  if (/[^\wа-яё]/i.test(p)) s++;
  return Math.min(s, 4);
}
const LABELS = ["очень слабый", "слабый", "средний", "хороший", "надёжный"];

export default function PasswordPage() {
  const me = useStaff();
  const toast = useToast();
  const [weak, setWeak] = useState(false);
  const [f, setF] = useState({ old_password: "", new_password: "", repeat: "" });
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  useEffect(() => setWeak(window.location.search.includes("weak=1") || !!me.weak_password), [me.weak_password]);
  const set = (k: keyof typeof f, v: string) => { setF((x) => ({ ...x, [k]: v })); setErrors((e) => ({ ...e, [k]: "" })); };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const p = f.new_password;
    const errs = V.collect({
      old_password: f.old_password ? null : "Введите текущий пароль",
      new_password: p.length < 10 || p.length > 128 ? "От 10 до 128 символов" : /^\d+$/.test(p) ? "Пароль не может состоять только из цифр"
        : p.toLowerCase().includes(me.username.toLowerCase()) ? "Пароль не должен содержать логин" : null,
      repeat: f.repeat !== p ? "Пароли не совпадают" : null,
    });
    setErrors(errs);
    if (V.hasErrors(errs)) return;
    setBusy(true);
    try {
      // новый вход сервер сам кладёт в HttpOnly-cookie
      await adminApi("/auth/password", { body: { old_password: f.old_password, new_password: p } });
      setDone(true);
      setWeak(false);
      setF({ old_password: "", new_password: "", repeat: "" });
      toast("Пароль изменён. На других устройствах нужно войти заново.", "ok");
      setTimeout(() => window.location.assign("/admin"), 1200);
    } catch (x) {
      toast(V.serverError(x, setErrors), "err");
    } finally {
      setBusy(false);
    }
  }

  const s = strength(f.new_password);
  return (
    <>
      <PageTop title="Сменить пароль" />
      {weak && !done && (
        <div className="notice red" style={{ marginBottom: 14 }}>
          <b>Сейчас у вас демо-пароль, который знают все, кто видел проект.</b> Придумайте новый — иначе любой сможет войти в админку.
        </div>
      )}
      <form className="card stack" style={{ maxWidth: 520 }} onSubmit={save}>
        <input type="text" name="username" autoComplete="username" value={me.username} readOnly hidden />
        <Field label="Текущий пароль" error={errors.old_password}>
          <input className="input" type="password" autoComplete="current-password" maxLength={128} value={f.old_password} onChange={(e) => set("old_password", e.target.value)} />
        </Field>
        <Field label="Новый пароль" error={errors.new_password} hint="Минимум 10 символов. Лучше 3–4 случайных слова или буквы, цифры и знаки вперемешку.">
          <input className="input" type="password" autoComplete="new-password" maxLength={128} value={f.new_password} onChange={(e) => set("new_password", e.target.value)} />
        </Field>
        {f.new_password && (
          <div className="pw-meter" aria-live="polite">
            <div className={`pw-bar s${s}`}><span style={{ width: `${(s + 1) * 20}%` }} /></div>
            <span className="tiny muted">Надёжность: {LABELS[s]}</span>
          </div>
        )}
        <Field label="Повторите новый пароль" error={errors.repeat}>
          <input className="input" type="password" autoComplete="new-password" maxLength={128} value={f.repeat} onChange={(e) => set("repeat", e.target.value)} />
        </Field>
        <button className="btn" disabled={busy}>{busy ? "Сохраняем…" : "Сменить пароль"}</button>
        <div className="tiny muted">После смены пароля все остальные входы в админку (другие телефоны и компьютеры) завершатся.</div>
      </form>
    </>
  );
}
