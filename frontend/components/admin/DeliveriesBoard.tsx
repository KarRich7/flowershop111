"use client";
import Link from "next/link";
import { useState } from "react";
import { useStaff } from "./AdminShell";
import { ErrorBox, Loading, StatusBadge } from "./ui";
import { useToast } from "../Toast";
import { adminApi, useAdmin, type StaffUser } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { dateLong, money, todayIso } from "@/lib/format";

type Row = {
  id: number; order_id: number; number: string; status: string; status_label: string; order_status: string; order_status_label: string;
  slot: string; zone: string; address: string; apartment: string; recipient: string; phone: string; courier: StaffUser | null;
  total: number; payment_status_label: string; payment_method: string;
  address_pending: boolean; surprise: boolean; anonymous: boolean;
};

export function DeliveriesBoard({ embedded = false }: { embedded?: boolean }) {
  const user = useStaff();
  const toast = useToast();
  const [date, setDate] = useState(todayIso());
  const { data, error, reload } = useAdmin<{ date: string; deliveries: Row[]; slots: { id: number; label: string; capacity: number }[] }>(`/deliveries?date=${date}`);
  const { data: couriers } = useAdmin<StaffUser[]>(user.role === "courier" ? null : "/couriers");
  const [busy, setBusy] = useState(0);

  async function act(orderId: number, path: string, body: unknown) {
    setBusy(orderId);
    try {
      await adminApi(`/orders/${orderId}${path}`, { body });
      toast("Сохранено", "ok");
      reload();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    } finally {
      setBusy(0);
    }
  }

  return (
    <>
      <div className="filters">
        <button className="btn btn-sm btn-ghost" onClick={() => setDate(todayIso())}>Сегодня</button>
        <button className="btn btn-sm btn-ghost" onClick={() => setDate(todayIso(1))}>Завтра</button>
        <input className="input" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
        <span className="muted small">{dateLong(date)}</span>
      </div>
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="stack">
          {data.slots.map((s) => {
            const rows = data.deliveries.filter((d) => d.slot === s.label);
            return (
              <div key={s.id} className="card card-tight">
                <div className="row-between" style={{ marginBottom: 6 }}>
                  <b>{s.label}</b>
                  {!embedded && <span className="muted small">{rows.length} из {s.capacity}</span>}
                </div>
                {!rows.length ? <div className="muted small">Нет доставок</div> : (
                  <div className="table-wrap" style={{ border: 0 }}>
                    <table className="t">
                      <tbody>
                        {rows.map((d) => (
                          <tr key={d.id} style={{ opacity: busy === d.order_id ? 0.5 : 1 }}>
                            <td data-label="Заказ"><Link href={`/admin/orders/${d.order_id}`}><b>№{d.number}</b></Link><div><StatusBadge status={d.order_status} label={d.order_status_label} /></div></td>
                            <td data-label="Адрес" className="full-cell">
                              {d.address}{d.apartment ? `, кв. ${d.apartment}` : ""}<div className="tiny muted">{d.zone}</div>
                              {(d.address_pending || d.surprise || d.anonymous) && (
                                <div className="flag-badges" style={{ marginTop: 4 }}>
                                  {d.address_pending && <span className="badge amber">адрес уточняется</span>}
                                  {d.surprise && <span className="badge lilac">сюрприз: звонить только у двери</span>}
                                  {d.anonymous && <span className="badge gray">не называть отправителя</span>}
                                </div>
                              )}
                            </td>
                            <td data-label="Получатель">{d.recipient}<div className="tiny"><a href={`tel:${d.phone}`} className="tel-link">{d.phone}</a></div></td>
                            <td data-label="Сумма" className="small">{money(d.total)}<div className="tiny muted">{d.payment_status_label}</div></td>
                            <td data-label={user.role === "courier" ? "" : "Курьер"} className={user.role === "courier" ? "" : "full-cell"}>
                              {user.role === "courier" ? (
                                <div className="row">
                                  {d.order_status === "ready" && <button className="btn btn-xs" onClick={() => act(d.order_id, "/transition", { status: "handed_to_courier" })}>Забрал заказ</button>}
                                  {d.order_status === "handed_to_courier" && <button className="btn btn-xs" onClick={() => act(d.order_id, "/transition", { status: "delivered" })}>Доставлено</button>}
                                  {!["ready", "handed_to_courier"].includes(d.order_status) && <span className="tiny muted">{d.status_label}</span>}
                                </div>
                              ) : (
                                <select className="select input-sm" value={d.courier?.id || ""} disabled={["delivered", "completed"].includes(d.order_status)} onChange={(e) => e.target.value && act(d.order_id, "/assign-courier", { courier_id: Number(e.target.value) })}>
                                  <option value="">— курьер —</option>
                                  {(couriers || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                                </select>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
