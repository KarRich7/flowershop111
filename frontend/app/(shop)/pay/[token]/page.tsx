"use client";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ApiError, request } from "@/lib/api";
import { money, timeOnly } from "@/lib/format";
import type { PaymentInfo } from "@/lib/types";

export default function PayPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [p, setP] = useState<PaymentInfo | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [done, setDone] = useState("");

  const load = () => request<PaymentInfo>(`/payments/${token}`).then(setP).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function act(action: "succeed" | "fail" | "cancel") {
    setBusy(action);
    setErr("");
    try {
      await request(`/payments/${token}/simulate`, { body: { action } });
      setDone(action);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
    } finally {
      setBusy("");
    }
  }

  if (!p && !err) return <div className="paybox"><div className="paybox-body"><div className="skeleton" style={{ height: 240 }} /></div></div>;
  if (!p) return <div className="container section"><div className="notice red">{err}</div></div>;
  const pending = p.status === "pending";
  return (
    <div className="container">
      <div className="paybox">
        <div className="paybox-head">
          <b>Тестовая оплата</b>
          <span className="badge amber">симулятор · деньги не списываются</span>
        </div>
        <div className="paybox-body stack">
          <div className="muted small">{p.shop_name} · заказ №{p.order_number}</div>
          <div className="price-lg">{money(p.amount)}</div>
          <div className="row">
            <span className={`badge ${p.status === "paid" ? "green" : pending ? "amber" : "red"}`}>{p.status_label}</span>
            <span className="badge gray">Заказ: {p.order_status_label}</span>
          </div>
          {pending && p.expires_at && <div className="hint">Резерв товаров действует до {timeOnly(p.expires_at)}. Если не оплатить — заказ отменится автоматически.</div>}
          {pending ? (
            <>
              <div className="fake-card">
                Карта: 4242 4242 4242 4242 · 12/30 · CVC 123
                <br />
                <span className="tiny">Реальный платёжный провайдер не подключён — выберите результат оплаты.</span>
              </div>
              <button className="btn btn-lg btn-block" disabled={!!busy} onClick={() => act("succeed")}>
                {busy === "succeed" ? "Оплачиваем…" : `Оплатить ${money(p.amount)}`}
              </button>
              <div className="grid-2">
                <button className="btn btn-ghost" disabled={!!busy} onClick={() => act("fail")}>Ошибка оплаты</button>
                <button className="btn btn-ghost" disabled={!!busy} onClick={() => act("cancel")}>Отменить</button>
              </div>
            </>
          ) : (
            <div className={`notice ${p.status === "paid" ? "green" : "red"}`}>
              {p.status === "paid"
                ? "Оплата прошла успешно. Заказ подтверждён и передан флористу."
                : done === "fail" || p.status === "failed"
                  ? "Платёж отклонён. Можно попробовать оплатить ещё раз со страницы заказа, пока действует резерв."
                  : `Статус платежа: ${p.status_label}.`}
            </div>
          )}
          {err && <div className="notice red small">{err}</div>}
          <Link href={`/order/${p.order_token}`} className="btn btn-outline btn-block">Перейти к заказу</Link>
        </div>
      </div>
    </div>
  );
}
