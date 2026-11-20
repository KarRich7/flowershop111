"use client";
// Личный кабинет покупателя: вход через Telegram / ВКонтакте, контакты для автозаполнения, история заказов.
import Link from "next/link";
import { useEffect, useState } from "react";
import { MessengerLogin, TelegramIcon, VkIcon } from "@/components/account/MessengerLogin";
import { useCustomer } from "@/components/CustomerProvider";
import { useShop } from "@/components/ShopProvider";
import { useToast } from "@/components/Toast";
import { ApiError, request } from "@/lib/api";
import { phoneHuman } from "@/lib/customer";
import { dateLong, dateTime, money, STATUS_TONE } from "@/lib/format";
import * as V from "@/lib/validate";

export default function AccountPage() {
  const shop = useShop();
  const toast = useToast();
  const { me, ready, update, logout } = useCustomer();
  const [f, setF] = useState({ name: "", phone: "", email: "" });
  const [errors, setErrors] = useState<V.Errors>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me) setF({ name: me.name, phone: phoneHuman(me.phone), email: me.email });
  }, [me]);

  if (!ready) return <div className="container section"><div className="skeleton" style={{ height: 320 }} /></div>;

  const canLogin = shop.customer_login?.telegram || shop.customer_login?.vk;
  if (!me)
    return (
      <div className="container" style={{ paddingBottom: 64, maxWidth: 720 }}>
        <div className="page-head">
          <h1>Личный кабинет</h1>
        </div>
        <section className="card stack">
          {canLogin ? (
            <>
              <div className="panel-title" style={{ marginBottom: 0 }}>Войдите через Telegram или ВКонтакте</div>
              <ul className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
                <li>статус заказов приходит в мессенджер;</li>
                <li>имя, телефон и прошлый адрес подставляются при оформлении;</li>
                <li>история заказов — на этой странице и в боте.</li>
              </ul>
              <MessengerLogin />
              <p className="tiny muted" style={{ margin: "10px 0 0" }}>Пароль не нужен: вход подтверждается кнопкой в чате с нашим ботом.</p>
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              {shop.customer_login?.enabled === false ? "Личный кабинет сейчас отключён." : "Вход через мессенджеры пока не подключён."} Статус заказа можно посмотреть на странице{" "}
              <Link href="/track" style={{ color: "var(--green)", fontWeight: 600 }}>«Мой заказ»</Link>.
            </p>
          )}
        </section>
      </div>
    );

  const set = (k: keyof typeof f, v: string) => {
    setF((x) => ({ ...x, [k]: v }));
    setErrors((e) => ({ ...e, [k]: "" }));
  };

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const errs = V.collect({
      name: V.personName(f.name, "Имя", false),
      phone: V.phone(f.phone, "Телефон", false),
      email: V.email(f.email),
    });
    setErrors(errs);
    if (V.hasErrors(errs)) return;
    setBusy(true);
    try {
      await update({ name: f.name.trim(), phone: f.phone.trim(), email: f.email.trim() });
      toast("Данные сохранены", "ok");
    } catch (e2) {
      toast(V.serverError(e2, setErrors, ["name", "phone", "email"]) || "Не удалось сохранить", "err");
    } finally {
      setBusy(false);
    }
  }

  async function logoutAll() {
    try {
      await request("/account/logout-all", { method: "POST" });
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) return toast("Не удалось выйти", "err");
    }
    await logout();
  }

  const fe = (k: string) => (errors[k] ? <span className="field-err" role="alert">{errors[k]}</span> : null);
  return (
    <div className="container" style={{ paddingBottom: 64 }}>
      <div className="page-head">
        <h1>Личный кабинет</h1>
      </div>
      <div className="acc-grid">
        <div className="stack">
          <form className="card stack" onSubmit={save} noValidate>
            <div className="panel-title" style={{ marginBottom: 0 }}>Контакты для заказов</div>
            <label className="field">
              <span>Имя</span>
              <input className={`input ${errors.name ? "invalid" : ""}`} maxLength={80} value={f.name} onChange={(e) => set("name", e.target.value)} autoComplete="name" />
              {fe("name")}
            </label>
            <label className="field">
              <span>Телефон</span>
              <input className={`input ${errors.phone ? "invalid" : ""}`} type="tel" maxLength={20} placeholder="+7 900 000-00-00" value={f.phone} onChange={(e) => set("phone", e.target.value)} autoComplete="tel" />
              {fe("phone")}
            </label>
            <label className="field">
              <span>E-mail</span>
              <input className={`input ${errors.email ? "invalid" : ""}`} type="email" maxLength={120} value={f.email} onChange={(e) => set("email", e.target.value)} autoComplete="email" />
              {fe("email")}
            </label>
            <div className="row">
              <button className="btn" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</button>
            </div>
          </form>
          <section className="card">
            <div className="panel-title">Уведомления</div>
            <ul className="acc-channels">
              {me.channels.map((c) => (
                <li key={c.channel}>
                  <span className={`acc-ch-ico ${c.channel}`}>{c.channel === "telegram" ? <TelegramIcon size={16} /> : <VkIcon size={16} />}</span>
                  <span>
                    <b>{c.label}</b> {c.username ? <span className="muted">@{c.username}</span> : c.display_name ? <span className="muted">{c.display_name}</span> : null}
                    {c.test && <span className="badge gray" style={{ marginLeft: 6 }}>тест</span>}
                    <div className="tiny muted">Сюда приходят статусы заказов и ответы флориста</div>
                  </span>
                </li>
              ))}
            </ul>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-sm btn-outline" onClick={logout}>Выйти</button>
              <button type="button" className="btn btn-sm btn-quiet" onClick={logoutAll}>Выйти на всех устройствах</button>
            </div>
          </section>
        </div>
        <section className="card">
          <div className="panel-title">Мои заказы</div>
          {me.orders.length ? (
            <div className="acc-orders">
              {me.orders.map((o) => (
                <Link key={o.token} href={`/order/${o.token}`} className="acc-order">
                  <span>
                    <b>№{o.number}</b> <span className="muted small">от {dateTime(o.created_at)}</span>
                  </span>
                  <span className="num nowrap">{money(o.total)}</span>
                  <span className="small">
                    <span className={`badge ${STATUS_TONE[o.status] || "gray"}`}>{o.status_label}</span>{" "}
                    <span className="muted">{o.fulfillment_label}, {dateLong(o.date)}{o.source !== "web" ? ` · ${o.source_label}` : ""}</span>
                  </span>
                  <span />
                  <span className="acc-items">{o.items}</span>
                </Link>
              ))}
            </div>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              Заказов пока нет. <Link href="/bouquets" style={{ color: "var(--green)", fontWeight: 600 }}>Выбрать букет</Link>
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
