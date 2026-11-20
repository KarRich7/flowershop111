"use client";
import Link from "next/link";
import { useState } from "react";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import * as V from "@/lib/validate";
import { ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import type { Product } from "@/lib/types";

type Row = Product & { is_active: boolean; sku: string };

export default function StoreSale() {
  const toast = useToast();
  const { data, error, reload } = useAdmin<Row[]>("/products");
  const [type, setType] = useState("bouquet");
  const [q, setQ] = useState("");
  const [lines, setLines] = useState<Record<number, number>>({});
  const [payment, setPayment] = useState<"cash" | "card">("card");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ order_id: number; number: string; total: number } | null>(null);

  const products = (data || []).filter((p) => p.is_active && ["bouquet", "flower", "greenery", "card", "addon"].includes(p.type));
  const list = products.filter((p) => (!type || p.type === type) && (!q || p.name.toLowerCase().includes(q.toLowerCase())));
  const byId = new Map(products.map((p) => [p.id, p]));
  const chosen = Object.entries(lines).filter(([, n]) => n > 0).map(([id, n]) => ({ p: byId.get(Number(id))!, n })).filter((x) => x.p);
  const total = chosen.reduce((s, x) => s + x.p.price * x.n, 0);
  const add = (p: Row, d: number) => setLines((l) => ({ ...l, [p.id]: Math.max(0, Math.min(p.available, (l[p.id] || 0) + d)) }));

  return (
    <>
      <PageTop title="Продажа в магазине" />
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="pos">
          <div>
            <div className="filters">
              <div className="seg">
                {[["bouquet", "Букеты"], ["flower", "Цветы"], ["greenery", "Зелень"], ["card", "Открытки"], ["addon", "Доп."]].map(([v, l]) => (
                  <button key={v} className={type === v ? "on" : ""} onClick={() => setType(v)}>{l}</button>
                ))}
              </div>
              <input className="input" placeholder="Поиск" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="pos-grid">
              {list.map((p) => (
                <button key={p.id} className="pos-item" disabled={p.available <= (lines[p.id] || 0)} onClick={() => add(p, 1)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {p.image && <img src={p.image} alt="" />}
                  <div>
                    <b>{p.name}</b>
                    <div className="row-between"><span>{money(p.price)}</span><span className={`badge ${p.available ? "green" : "red"}`}>{p.available}</span></div>
                  </div>
                </button>
              ))}
            </div>
          </div>
          <aside className="card sticky-aside">
            <div className="panel-title">Чек</div>
            {!chosen.length && <p className="muted small">Нажмите на товар, чтобы добавить.</p>}
            {chosen.map(({ p, n }) => (
              <div key={p.id} className="row-between" style={{ padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                <span className="small" style={{ flex: 1 }}>{p.name}</span>
                <div className="qty">
                  <button className="icon-btn" onClick={() => add(p, -1)} aria-label="Меньше">−</button>
                  <span>{n}</span>
                  <button className="icon-btn" disabled={n >= p.available} onClick={() => add(p, 1)} aria-label="Больше">+</button>
                </div>
                <b className="nowrap" style={{ minWidth: 80, textAlign: "right" }}>{money(p.price * n)}</b>
              </div>
            ))}
            <div className="sum-row total"><span>Итого</span><span>{money(total)}</span></div>
            <div className="seg" style={{ margin: "10px 0" }}>
              <button className={payment === "card" ? "on" : ""} onClick={() => setPayment("card")}>Картой</button>
              <button className={payment === "cash" ? "on" : ""} onClick={() => setPayment("cash")}>Наличными</button>
            </div>
            <input className={`input ${phone && V.phone(phone, "Телефон", false) ? "invalid" : ""}`} type="tel" maxLength={20} placeholder="Телефон покупателя (необязательно)" value={phone} onChange={(e) => setPhone(e.target.value)} />
            {phone && V.phone(phone, "Телефон", false) && <div className="field-err">{V.phone(phone, "Телефон", false)}</div>}
            <button
              className="btn btn-block btn-lg"
              style={{ marginTop: 12 }}
              disabled={busy || !chosen.length || !!(phone && V.phone(phone, "Телефон", false))}
              onClick={async () => {
                setBusy(true);
                try {
                  const r = await adminApi<{ order_id: number; number: string; total: number }>("/store-sale", { body: { lines: chosen.map((x) => ({ product_id: x.p.id, quantity: x.n })), payment, customer_phone: phone } });
                  setLast(r);
                  setLines({});
                  setPhone("");
                  toast(`Продажа №${r.number} проведена`, "ok");
                  reload();
                } catch (e) {
                  toast(e instanceof ApiError ? e.message : "Ошибка", "err");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Провести продажу
            </button>
            {last && (
              <div className="notice green small" style={{ marginTop: 12 }}>
                Продажа <Link href={`/admin/orders/${last.order_id}`} style={{ fontWeight: 700 }}>№{last.number}</Link> на {money(last.total)} проведена. Остатки обновлены во всех каналах.
              </div>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
