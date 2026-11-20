"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useShop } from "@/components/ShopProvider";
import { ApiError, request } from "@/lib/api";
import { forgetOrders, rememberedOrders, type SavedOrder } from "@/lib/customer";

export default function TrackPage() {
  const router = useRouter();
  const shop = useShop();
  const [number, setNumber] = useState("");
  const [phone, setPhone] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<SavedOrder[]>([]);
  useEffect(() => setSaved(rememberedOrders()), []);
  return (
    <div className="container" style={{ maxWidth: 560, padding: "40px 20px 80px" }}>
      <h1>Мой заказ</h1>
      {saved.length > 0 && (
        <section className="card stack" style={{ marginBottom: 20 }} data-testid="saved-orders">
          <div className="panel-title" style={{ margin: 0 }}>Заказы с этого устройства</div>
          <div className="saved-orders">
            {saved.map((o) => (
              <Link key={o.token} href={`/order/${o.token}`} className="chip">
                Заказ №{o.number}
              </Link>
            ))}
          </div>
          <button type="button" className="btn btn-sm btn-quiet" style={{ alignSelf: "flex-start" }} onClick={() => { forgetOrders(); setSaved([]); }}>
            Убрать список с этого устройства
          </button>
        </section>
      )}
      <p className="muted">Введите номер заказа и телефон, указанный при оформлении.</p>
      <form
        className="card stack"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr("");
          try {
            const r = await request<{ token: string }>("/orders/lookup", { body: { number, phone } });
            router.push(`/order/${r.token}`);
          } catch (e2) {
            setErr(e2 instanceof ApiError ? e2.message : "Ошибка");
            setBusy(false);
          }
        }}
      >
        <label className="field">
          <span>Номер заказа</span>
          <input className="input" required placeholder="10001" value={number} onChange={(e) => setNumber(e.target.value)} />
        </label>
        <label className="field">
          <span>Телефон</span>
          <input className="input" required type="tel" placeholder="+7 900 000-00-01" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        {err && <div className="notice red small">{err}</div>}
        <button className="btn btn-lg" disabled={busy}>{busy ? "Ищем…" : "Найти заказ"}</button>
        {shop.payment_test_mode && <div className="hint">Демо: заказ №10001, телефон +7 900 000-00-01.</div>}
      </form>
    </div>
  );
}
