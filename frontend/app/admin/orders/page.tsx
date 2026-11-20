"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorBox, Loading, PageTop, StatusBadge } from "@/components/admin/ui";
import { useStaff } from "@/components/admin/AdminShell";
import { useAdmin } from "@/lib/admin";
import { dateLong, dateTime, hm, money } from "@/lib/format";
import { TruckIcon } from "@/components/Icons";

type Row = {
  id: number; number: string; created_at: string; source: string; source_label: string; status: string; status_label: string;
  payment_status: string; payment_status_label: string; payment_method_label: string; fulfillment: string; fulfillment_label: string;
  date: string | null; time_from: string | null; time_to: string | null; total: number; contact_name: string;
  requires_confirmation: boolean; is_preorder: boolean; courier: string | null; address: string | null;
  address_pending: boolean; surprise: boolean; anonymous: boolean; photo_before: boolean;
};

/** Быстрые вкладки вместо длинного списка статусов: [ключ, подпись, фильтр для адреса] */
const TABS: [string, string, string][] = [
  ["all", "Все", ""],
  ["active", "В работе", "scope=active"],
  ["confirm", "Ждут подтверждения", "status=awaiting_confirmation,new"],
  ["payment", "Ждут оплаты", "status=awaiting_payment"],
];
const tabOf = (status: string, scope: string) =>
  scope === "active" ? "active" : /awaiting_confirmation|^new$/.test(status) ? "confirm" : status === "awaiting_payment" ? "payment" : status ? "" : "all";

export default function OrdersPage() {
  const user = useStaff();
  const [f, setF] = useState({ status: "", scope: "", source: "", date: "", q: "" });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    setF((x) => ({ ...x, status: sp.get("status") || "", scope: sp.get("scope") || "" }));
    setReady(true);
  }, []);
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]).toString();
  const { data, error, loading } = useAdmin<Row[]>(ready ? `/orders${qs ? `?${qs}` : ""}` : null);
  const set = (k: keyof typeof f, v: string) => {
    setF((x) => ({ ...x, [k]: v }));
  };
  function openTab(filter: string) {
    const sp = new URLSearchParams(filter);
    setF((x) => ({ ...x, status: sp.get("status") || "", scope: sp.get("scope") || "" }));
    window.history.replaceState(null, "", filter ? `/admin/orders?${filter}` : "/admin/orders");
  }
  const tab = tabOf(f.status, f.scope);

  return (
    <>
      <PageTop title="Заказы">
        {user.role !== "courier" && <Link href="/admin/store-sale" className="btn btn-sm">+ Продажа в магазине</Link>}
      </PageTop>
      <div className="tabs" role="tablist">
        {TABS.filter(([k]) => user.role !== "courier" || k === "all" || k === "active").map(([k, l, q]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => openTab(q)}>{l}</button>
        ))}
      </div>
      <div className="filters">
        <input className="input" placeholder="№, имя или телефон" value={f.q} onChange={(e) => set("q", e.target.value)} />
        <select className="select" value={f.source} onChange={(e) => set("source", e.target.value)}>
          <option value="">Все каналы</option>
          <option value="web">Сайт</option>
          <option value="telegram">Telegram</option>
          <option value="vk">ВКонтакте</option>
          <option value="store">Магазин</option>
        </select>
        <input className="input" type="date" value={f.date} onChange={(e) => set("date", e.target.value)} title="Дата доставки / получения" />
      </div>
      <ErrorBox text={error} />
      {loading && !data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead>
              <tr><th>Заказ</th><th>Клиент</th><th>Канал</th><th>Статус</th><th>Получение</th><th>Оплата</th><th className="num">Сумма</th></tr>
            </thead>
            <tbody>
              {(data || []).map((o) => (
                <tr key={o.id} className="click" onClick={() => (window.location.href = `/admin/orders/${o.id}`)}>
                  <td><b>№{o.number}</b><div className="tiny muted">{dateTime(o.created_at)}</div></td>
                  <td>{o.contact_name}</td>
                  <td>{o.source_label}</td>
                  <td>
                    <StatusBadge status={o.status} label={o.status_label} />
                    {o.is_preorder && <span className="badge lilac" style={{ marginLeft: 4 }}>предзаказ</span>}
                    {o.address_pending && <span className="badge amber" style={{ marginLeft: 4 }}>узнать адрес</span>}
                  </td>
                  <td>
                    {o.fulfillment_label}
                    <div className="tiny muted">{o.date ? dateLong(o.date) : ""} {o.time_from ? `${hm(o.time_from)}–${hm(o.time_to)}` : ""}</div>
                    {o.fulfillment === "delivery" && <div className="tiny muted">{o.courier ? <span className="row" style={{ gap: 4 }}><TruckIcon /> {o.courier}</span> : "курьер не назначен"}</div>}
                  </td>
                  <td>{o.payment_method_label}<div className="tiny muted">{o.payment_status_label}</div></td>
                  <td className="num"><b>{money(o.total)}</b></td>
                </tr>
              ))}
              {data && !data.length && <tr><td colSpan={7} className="empty">Заказов не найдено</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
