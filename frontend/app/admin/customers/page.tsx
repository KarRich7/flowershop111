"use client";
import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { useAdmin } from "@/lib/admin";
import { dateTime, money } from "@/lib/format";

type C = { id: number; name: string; phone: string; email: string; orders_count: number; orders_sum: number; created_at: string; is_demo: boolean; channels: { channel: string; label?: string }[] | string[] };
type CD = { id: number; name: string; phone: string; email: string; notes: string; orders: { id: number; number: string; status_label: string; total: number; created_at: string; source_label: string }[] };

export default function CustomersPage() {
  const [q, setQ] = useState("");
  const { data, error } = useAdmin<C[]>(`/customers${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <PageTop title="Клиенты" />
      <div className="filters"><input className="input" placeholder="Имя, телефон, e-mail" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Клиент</th><th>Контакты</th><th>Каналы</th><th className="num">Заказов</th><th className="num">Сумма</th><th>С нами с</th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="click" onClick={() => setOpen(c.id)}>
                  <td><b>{c.name}</b> {c.is_demo && <span className="badge gray">демо</span>}</td>
                  <td className="small">{c.phone}<div className="muted">{c.email}</div></td>
                  <td className="small">{(c.channels || []).map((x) => (typeof x === "string" ? x : x.label || x.channel)).join(", ") || "сайт / магазин"}</td>
                  <td className="num">{c.orders_count}</td>
                  <td className="num">{money(c.orders_sum)}</td>
                  <td className="small muted">{dateTime(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <CustomerModal id={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function CustomerModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { data } = useAdmin<CD>(`/customers/${id}`);
  return (
    <Modal title={data?.name || "Клиент"} onClose={onClose}>
      {!data ? <Loading /> : (
        <>
          <dl className="kv"><dt>Телефон</dt><dd>{data.phone}</dd><dt>E-mail</dt><dd>{data.email || "—"}</dd>{data.notes && (<><dt>Заметки</dt><dd>{data.notes}</dd></>)}</dl>
          <hr className="divider" />
          <b>Заказы</b>
          {data.orders.map((o) => (
            <div key={o.id} className="sum-row">
              <Link href={`/admin/orders/${o.id}`}>№{o.number} <span className="muted small">· {o.source_label} · {dateTime(o.created_at)}</span></Link>
              <span className="small">{o.status_label} · <b>{money(o.total)}</b></span>
            </div>
          ))}
        </>
      )}
    </Modal>
  );
}
