"use client";
import { useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, NOTIFY_MODES, useAdmin, type MessengerLinks, type NotifyMode, type StaffUser } from "@/lib/admin";
import { MessengerLinkBox } from "@/components/admin/MessengerLinks";
import { Field } from "@/components/Field";
import * as V from "@/lib/validate";
import { ApiError } from "@/lib/api";

const ROLES: [string, string][] = [["owner", "Владелец"], ["florist", "Флорист / администратор"], ["courier", "Курьер"]];

export default function StaffPage() {
  const me = useStaff();
  const { data, error, reload } = useAdmin<StaffUser[]>("/staff");
  const [edit, setEdit] = useState<StaffUser | "new" | null>(null);
  if (me.role !== "owner") return <ErrorBox text="Раздел доступен только владельцу" />;
  return (
    <>
      <PageTop title="Сотрудники"><button className="btn btn-sm" onClick={() => setEdit("new")}>+ Сотрудник</button></PageTop>
      <p className="hint" style={{ marginTop: -10 }}>
        <b>Флорист</b> — заказы, склад, товары (без цен). <b>Курьер</b> — только свои доставки. Уведомления в Telegram/ВК — в карточке сотрудника.
      </p>
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Сотрудник</th><th>Логин</th><th>Роль</th><th>Телефон</th><th>Уведомления</th><th>Статус</th></tr></thead>
            <tbody>
              {data.map((u) => (
                <tr key={u.id} className="click" onClick={() => setEdit(u)}>
                  <td><b>{u.name}</b> {u.is_demo && u.role !== "owner" && <span className="badge gray">демо</span>}</td>
                  <td className="small">{u.username}</td>
                  <td><span className="badge lilac">{u.role_label}</span></td>
                  <td className="small">{u.phone}</td>
                  <td className="small">
                    {u.on_shift && <span className="badge green" style={{ marginRight: 4 }}>на смене</span>}
                    {u.notify_mode_label}
                    {(u.telegram_linked || u.vk_linked) ? <span className="muted"> · {[u.telegram_linked && "Telegram", u.vk_linked && "ВК"].filter(Boolean).join(", ")}</span>
                      : u.notify_mode !== "off" && <span className="red-text"> · мессенджер не привязан</span>}
                  </td>
                  <td>{u.is_active ? <span className="badge green">активен</span> : <span className="badge red">отключён</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && <StaffModal u={edit === "new" ? null : edit} onClose={() => setEdit(null)} onDone={() => { reload(); setEdit(null); }} />}
    </>
  );
}

function StaffModal({ u, onClose, onDone }: { u: StaffUser | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const me = useStaff();
  const [f, setF] = useState({ username: u?.username || "", first_name: u?.first_name || "", last_name: u?.last_name || "", phone: u?.phone || "", role: u?.role || "florist", is_active: u?.is_active ?? true, password: "", notify_mode: (u?.notify_mode || "shift") as NotifyMode, on_shift: u?.on_shift ?? false });
  const [linked, setLinked] = useState({ telegram: !!u?.telegram_linked, vk: !!u?.vk_linked });
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string | boolean) => { setF((x) => ({ ...x, [k]: v })); setErrors((e) => ({ ...e, [k]: "" })); };
  async function save() {
    const e = V.collect({
      first_name: V.personName(f.first_name, "Имя", false),
      last_name: V.personName(f.last_name, "Фамилия", false),
      username: u ? null : !/^[A-Za-z0-9_.-]{3,30}$/.test(f.username.trim()) ? "3–30 символов: латиница, цифры, точка, дефис или _" : null,
      phone: V.phone(f.phone, "Телефон", false),
      password: (!u || f.password) && (f.password.length < 10 || f.password.length > 128) ? "От 10 до 128 символов" : (!u || f.password) && /^\d+$/.test(f.password) ? "Пароль не может состоять только из цифр" : null,
    });
    setErrors(e);
    if (V.hasErrors(e)) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = { ...f, username: f.username.trim(), first_name: f.first_name.trim(), last_name: f.last_name.trim() };
      if (!f.password) delete body.password;
      if (u) delete body.username;
      if (!u || f.notify_mode === u.notify_mode) delete body.notify_mode;
      if (!u || f.on_shift === u.on_shift) delete body.on_shift; // не перетирать смену, начатую в боте, пока открыта карточка
      await adminApi(u ? `/staff/${u.id}` : "/staff", { method: u ? "PATCH" : "POST", body });
      toast("Сохранено", "ok");
      onDone();
    } catch (x) {
      toast(V.serverError(x, setErrors), "err");
      setBusy(false);
    }
  }
  async function unlink(channel: "telegram" | "vk") {
    if (!u) return;
    setBusy(true);
    try {
      await adminApi(`/staff/${u.id}`, { method: "PATCH", body: { unlink: channel } });
      setLinked((x) => ({ ...x, [channel]: false }));
      toast("Отвязано", "ok");
    } catch (x) {
      toast(V.serverError(x), "err");
    }
    setBusy(false);
  }
  async function remove() {
    if (!u || !window.confirm(`Удалить учётную запись «${u.username}»? Войти под ней больше будет нельзя. История заказов сохранится.`)) return;
    setBusy(true);
    try {
      await adminApi(`/staff/${u.id}`, { method: "DELETE" });
      toast("Учётная запись удалена", "ok");
      onDone();
    } catch (x) {
      toast(V.serverError(x), "err");
      setBusy(false);
    }
  }
  return (
    <Modal title={u ? u.name : "Новый сотрудник"} onClose={onClose}>
      <div className="form-grid">
        <Field label="Имя" error={errors.first_name}><input className="input" maxLength={60} value={f.first_name} onChange={(e) => set("first_name", e.target.value)} /></Field>
        <Field label="Фамилия" error={errors.last_name}><input className="input" maxLength={60} value={f.last_name} onChange={(e) => set("last_name", e.target.value)} /></Field>
        <Field label="Логин" error={errors.username} hint={u ? undefined : "Латиница и цифры, для входа в админку"}><input className="input" maxLength={30} disabled={!!u} value={f.username} autoComplete="off" onChange={(e) => set("username", e.target.value)} /></Field>
        <Field label="Телефон" error={errors.phone}><input className="input" type="tel" maxLength={20} placeholder="+7 900 000-00-00" value={f.phone} onChange={(e) => set("phone", e.target.value)} /></Field>
        <Field label="Роль">
          <select className="select" value={f.role} onChange={(e) => set("role", e.target.value)}>{ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </Field>
        <Field label={u ? "Новый пароль" : "Пароль"} error={errors.password} hint="Минимум 10 символов, не только цифры. Сообщите пароль сотруднику лично, не в общем чате">
          <input className="input" type="password" autoComplete="new-password" maxLength={128} value={f.password} onChange={(e) => set("password", e.target.value)} placeholder={u ? "не менять" : ""} />
        </Field>
        {u && <label className="checkbox full"><input type="checkbox" checked={f.is_active} onChange={(e) => set("is_active", e.target.checked)} /> Доступ активен</label>}
      </div>
      {u && (
        <div style={{ marginTop: 16, borderTop: "1px solid var(--line, #eee)", paddingTop: 12 }}>
          <b>Уведомления о заказах</b>
          <div className="form-grid" style={{ marginTop: 8 }}>
            <Field label="Когда присылать">
              <select className="select" value={f.notify_mode} onChange={(e) => set("notify_mode", e.target.value)}>{NOTIFY_MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            </Field>
            <label className="checkbox" style={{ alignSelf: "end" }}><input type="checkbox" checked={f.on_shift} onChange={(e) => set("on_shift", e.target.checked)} /> Сейчас на смене</label>
          </div>
          {([["telegram", "Telegram"], ["vk", "ВКонтакте"]] as const).map(([key, name]) => (
            <div key={key} className="row" style={{ gap: 10, alignItems: "center", margin: "6px 0" }}>
              <span style={{ minWidth: 90 }}>{name}</span>
              {linked[key] ? <><span className="badge green">привязан</span><button className="btn btn-xs btn-ghost" disabled={busy} onClick={() => unlink(key)}>Отвязать</button></>
                : <span className="badge gray">не привязан</span>}
            </div>
          ))}
          <div style={{ marginTop: 8 }}>
            <MessengerLinkBox forSelf={u.id === me.id} load={() => adminApi<MessengerLinks>(`/staff/${u.id}/link`, { method: "POST" })} />
          </div>
        </div>
      )}
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16, flexWrap: "wrap" }}>
        {u && u.id !== me.id && <button className="btn btn-ghost red-text" style={{ marginRight: "auto" }} disabled={busy} onClick={remove}>Удалить</button>}
        <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
        <button className="btn" disabled={busy} onClick={save}>Сохранить</button>
      </div>
    </Modal>
  );
}
