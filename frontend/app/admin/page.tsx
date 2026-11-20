"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, Modal, PageTop, StatusBadge } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { dateTime, money } from "@/lib/format";
import { DeliveriesBoard } from "@/components/admin/DeliveriesBoard";
import { ArrowRightIcon } from "@/components/Icons";
import { SecurityBanner } from "@/components/admin/SecurityStatus";

type Dash = {
  role: string;
  orders_today: number;
  awaiting_confirmation: number;
  new_to_confirm: number;
  awaiting_payment: number;
  in_work: number;
  deliveries_today: number;
  unassigned_deliveries: number;
  low_stock: { id: number; name: string; available: number; min_stock: number }[];
  recent_orders: { id: number; number: string; status: string; status_label: string; source_label: string; total: number; created_at: string; name: string }[];
  feed: { id: number; kind: string; text: string; at: string; handled: boolean; can_reply: boolean }[];
  open_support: number;
  revenue_today: number;
  revenue_week: number;
  by_source: { source: string; orders: number; revenue: number }[];
  in_transit?: number;
  delivered?: number;
  orders_enabled?: boolean;
  orders_closed_message?: string;
};

export default function Dashboard() {
  const user = useStaff();
  const { data, error, reload } = useAdmin<Dash>("/dashboard");
  const [reply, setReply] = useState<Dash["feed"][number] | null>(null);
  useEffect(() => {
    const t = setInterval(reload, 15000);
    return () => clearInterval(t);
  }, [reload]);

  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  const toConfirm = data.awaiting_confirmation + data.new_to_confirm;
  // в ленте — только сообщения покупателей, на которые можно ответить; события заказов уже видны в «Последних заказах»
  const messages = (data.feed || []).filter((f) => f.can_reply); // у курьера ленты нет

  if (data.role === "courier")
    return (
      <>
        <PageTop title={`Здравствуйте, ${user.first_name || user.name}!`} />
        <div className="kpis">
          <div className="kpi"><b>{data.deliveries_today}</b><span>доставок сегодня</span></div>
          <div className="kpi accent"><b>{data.in_transit}</b><span>в пути</span></div>
          <div className="kpi"><b>{data.delivered}</b><span>доставлено</span></div>
        </div>
        <DeliveriesBoard embedded />
      </>
    );

  return (
    <>
      <PageTop title="Сводка">
        <Link href="/admin/store-sale" className="btn btn-sm">+ Продажа в магазине</Link>
        <Link href="/admin/inventory?tab=supply" className="btn btn-sm btn-ghost">Принять поставку</Link>
      </PageTop>
      {user.role === "owner" && <SecurityBanner />}
      {data.orders_enabled === false && <OrdersPausedBanner owner={user.role === "owner"} message={data.orders_closed_message || ""} onDone={reload} />}
      <div className="kpis">
        <Link href="/admin/orders?status=awaiting_confirmation,new" className={`kpi ${toConfirm ? "warn" : ""}`}><b>{toConfirm}</b><span>ждут подтверждения</span></Link>
        <Link href="/admin/orders?scope=active" className="kpi accent"><b>{data.in_work}</b><span>в работе</span></Link>
        <Link href="/admin/orders" className="kpi"><b>{data.orders_today}</b><span>заказов сегодня</span></Link>
        <Link href="/admin/deliveries" className={`kpi ${data.unassigned_deliveries ? "warn" : ""}`}>
          <b>{data.deliveries_today}</b>
          <span>доставок сегодня</span>
          {data.unassigned_deliveries ? <small className="kpi-sub">без курьера: {data.unassigned_deliveries}</small> : null}
        </Link>
        {user.role === "owner" && (
          <div className="kpi"><b>{money(data.revenue_today)}</b><span>выручка сегодня</span><small className="kpi-sub">за 7 дней: {money(data.revenue_week)}</small></div>
        )}
      </div>
      <div className="od-grid">
        <div className="stack">
          <div className="card">
            <div className="row-between"><div className="panel-title">Последние заказы</div><Link href="/admin/orders" className="link-arrow">Все заказы <ArrowRightIcon /></Link></div>
            <div className="table-wrap" style={{ border: 0 }}>
              <table className="t">
                <tbody>
                  {data.recent_orders.map((o) => (
                    <tr key={o.id} className="click" onClick={() => (window.location.href = `/admin/orders/${o.id}`)}>
                      <td><b>№{o.number}</b><div className="tiny muted">{dateTime(o.created_at)}</div></td>
                      <td>{o.name}<div className="tiny muted">{o.source_label}</div></td>
                      <td><StatusBadge status={o.status} label={o.status_label} /></td>
                      <td className="num">{money(o.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {user.role === "owner" && data.by_source.length > 0 && (
            <div className="card">
              <div className="panel-title">Каналы продаж (7 дней)</div>
              {data.by_source.map((s) => {
                const max = Math.max(...data.by_source.map((x) => x.revenue), 1);
                return (
                  <div key={s.source} style={{ marginBottom: 10 }}>
                    <div className="sum-row" style={{ padding: 0 }}><span>{s.source} · {s.orders} зак.</span><b>{money(s.revenue)}</b></div>
                    <div style={{ height: 8, borderRadius: 9, background: "#efe9df" }}><div style={{ width: `${(s.revenue / max) * 100}%`, height: 8, borderRadius: 9, background: "var(--lilac)" }} /></div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className="stack">
          <div className="card">
            <div className="panel-title">Мало на складе</div>
            {data.low_stock.length ? (
              <ul className="feed">
                {data.low_stock.map((l) => (
                  <li key={l.id} className="row-between"><span>{l.name}</span><span className={`badge ${l.available <= 0 ? "red" : "amber"}`}>{l.available} (мин. {l.min_stock})</span></li>
                ))}
              </ul>
            ) : <p className="muted small">Всё в порядке</p>}
            <Link href="/admin/inventory" className="btn btn-sm btn-ghost" style={{ marginTop: 8 }}>Открыть склад</Link>
          </div>
          {messages.length > 0 && (
          <div className="card">
            <div className="panel-title">Сообщения покупателей {data.open_support ? <span className="badge amber">{data.open_support} без ответа</span> : null}</div>
            <ul className="feed" style={{ maxHeight: 560, overflowY: "auto" }}>
              {messages.map((f) => (
                <li key={f.id}>
                  <div style={{ whiteSpace: "pre-wrap" }}>{f.text}</div>
                  <div className="row-between tiny muted">
                    <span>{dateTime(f.at)}</span>
                    {!f.handled ? <button className="btn btn-xs btn-lilac" onClick={() => setReply(f)}>Ответить</button> : <span className="badge gray">отвечено</span>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
          )}
        </div>
      </div>
      {reply && <ReplyModal item={reply} onClose={() => setReply(null)} onDone={reload} />}
    </>
  );
}

function ReplyModal({ item, onClose, onDone }: { item: { id: number; text: string }; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <Modal title="Ответ клиенту в мессенджер" onClose={onClose}>
      <div className="notice small" style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>{item.text}</div>
      <textarea className="textarea" value={text} onChange={(e) => setText(e.target.value)} placeholder="Здравствуйте! Да, можем…" />
      <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
        <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
        <button
          className="btn"
          disabled={busy || !text.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              await adminApi(`/support/${item.id}/reply`, { body: { text } });
              toast("Ответ отправлен", "ok");
              onDone();
              onClose();
            } catch (e) {
              toast(e instanceof ApiError ? e.message : "Ошибка", "err");
              setBusy(false);
            }
          }}
        >
          Отправить
        </button>
      </div>
    </Modal>
  );
}

/** Приём заказов закрыт: напоминание на сводке; владелец открывает приём одной кнопкой */
function OrdersPausedBanner({ owner, message, onDone }: { owner: boolean; message: string; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function open() {
    setBusy(true);
    try {
      await adminApi("/settings", { method: "PATCH", body: { orders_enabled: true } });
      toast("Приём заказов открыт", "ok");
      onDone();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Не удалось открыть приём", "err");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="notice amber row-between" style={{ marginBottom: 16 }} data-testid="orders-paused">
      <span>
        <b>Приём заказов закрыт.</b> Покупатели видят: «{message}»
      </span>
      {owner && (
        <span className="row">
          <Link href="/admin/settings" className="btn btn-sm btn-ghost">Настройки</Link>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={open}>{busy ? "Открываем…" : "Открыть приём заказов"}</button>
        </span>
      )}
    </div>
  );
}
