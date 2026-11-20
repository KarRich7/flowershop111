"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { ApiError, request } from "@/lib/api";
import { dateLong, dateTime, hm, money, STATUS_TONE, timeOnly } from "@/lib/format";
import type { OrderPublic } from "@/lib/types";
import { DesignView } from "@/components/bouquet/DesignView";
import { MessengerLogin } from "@/components/account/MessengerLogin";
import { useShop } from "@/components/ShopProvider";
import { rememberOrder } from "@/lib/customer";
import { paymentHref } from "@/lib/payment";

const FLOW_DELIVERY = ["new", "confirmed", "assembling", "ready", "handed_to_courier", "delivered", "completed"];
const FLOW_PICKUP = ["new", "confirmed", "assembling", "ready", "awaiting_pickup", "delivered", "completed"];

export default function OrderPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const shop = useShop();
  const [o, setO] = useState<OrderPublic | null>(null);
  const [err, setErr] = useState("");
  const [paying, setPaying] = useState(false);
  const [isNew, setIsNew] = useState(false);

  const load = useCallback(() => {
    request<OrderPublic>(`/orders/track/${token}`)
      .then((x) => {
        setO(x);
        rememberOrder(x.token, x.number); // заказ найдётся на странице «Мой заказ» без номера и телефона
      })
      .catch((e) => setErr(e.message));
  }, [token]);

  useEffect(() => {
    setIsNew(new URLSearchParams(window.location.search).has("new"));
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  async function pay() {
    setPaying(true);
    try {
      const r = await request<{ payment_url: string }>(`/orders/track/${token}/pay`, { method: "POST" });
      window.location.href = paymentHref(r.payment_url).href;
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Ошибка");
      setPaying(false);
    }
  }

  if (err && !o) return <div className="container section"><div className="notice red">{err}</div></div>;
  if (!o) return <div className="container section"><div className="skeleton" style={{ height: 380 }} /></div>;

  const flow = o.fulfillment === "pickup" ? FLOW_PICKUP : FLOW_DELIVERY;
  const idx = Math.max(flow.indexOf(o.status), ["awaiting_confirmation", "awaiting_payment"].includes(o.status) ? 0 : -1);
  return (
    <div className="container" style={{ paddingBottom: 60 }}>
      <div className="page-head">
        <div className="eyebrow">Заказ от {dateTime(o.created_at)} · {o.source_label}</div>
        <h1>Заказ №{o.number}</h1>
        <div className="row">
          <span className={`badge ${STATUS_TONE[o.status] || "gray"}`}>{o.status_label}</span>
          <span className={`badge ${o.payment_status === "paid" ? "green" : o.payment_status === "refunded" ? "gray" : "amber"}`}>{o.payment_status_label}</span>
          {o.is_preorder && <span className="badge lilac">Предзаказ</span>}
        </div>
      </div>

      {isNew && o.status !== "cancelled" && (
        <div className="notice green" style={{ marginBottom: 16 }}>
          Спасибо! Заказ принят. Сохраните эту страницу — здесь всегда актуальный статус. Номер заказа и телефон можно использовать на странице{" "}
          <Link href="/track" style={{ fontWeight: 700 }}>«Мой заказ»</Link> — на этом устройстве заказ появится там сам.
        </div>
      )}

      {o.status === "awaiting_payment" && (
        <div className="notice amber row-between" style={{ marginBottom: 16 }}>
          <span>
            Заказ ожидает оплаты{o.reservation_expires_at ? ` — резерв действует до ${timeOnly(o.reservation_expires_at)}` : ""}.
          </span>
          <button className="btn btn-sm" onClick={pay} disabled={paying}>{paying ? "…" : `Оплатить ${money(o.total)}`}</button>
        </div>
      )}
      {o.status === "awaiting_confirmation" && (
        <div className="notice" style={{ marginBottom: 16 }}>
          {o.delivery?.address_pending
            ? "Флорист позвонит получателю и уточнит адрес — не говоря, что это цветы."
            : "Флорист проверяет состав и наличие."}{" "}
          После подтверждения {o.payment_method === "online" ? "здесь появится кнопка оплаты" : "заказ будет передан в работу"}.
        </div>
      )}
      {o.status === "cancelled" && (
        <div className="notice red" style={{ marginBottom: 16 }}>Заказ отменён{o.cancel_reason ? `: ${o.cancel_reason}` : ""}.</div>
      )}

      <div className="od-grid">
        <div className="stack">
          {o.status !== "cancelled" && (
            <div className="card">
              <div className="panel-title">Статус</div>
              <div className="progress">
                {flow.slice(0, -1).map((s, i) => (
                  <div key={s} className={i <= idx ? "on" : ""} />
                ))}
              </div>
              <div className="small muted">{o.status_label}</div>
            </div>
          )}
          {(o.photos.length > 0 || (o.photo_before && o.status !== "cancelled")) && (
            <div className="card" data-testid="order-photos">
              <div className="panel-title">Фото букета</div>
              {o.photos.length ? (
                <div className="order-photos">
                  {o.photos.map((p) => (
                    <a key={p.id} href={p.url} target="_blank" rel="noreferrer">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={p.url} alt={`Букет к заказу №${o.number}`} />
                    </a>
                  ))}
                </div>
              ) : (
                <p className="small muted" style={{ margin: 0 }}>Флорист сфотографирует букет перед отправкой — фото появится здесь{o.notify_channels?.length ? " и придёт в мессенджер" : ""}.</p>
              )}
            </div>
          )}
          <div className="card">
            <div className="panel-title">Состав заказа</div>
            {o.items.map((i, k) => (
              <div key={k} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="sum-row" style={{ padding: 0 }}>
                  <b>{i.name} <span className="muted">× {i.quantity}</span></b>
                  <span>{money(i.line_total)}</span>
                </div>
                {i.composition && <div className="tiny muted">{i.composition.map((c) => `${c.name}${c.quantity > 1 ? ` ×${c.quantity}` : ""}`).join(", ")}</div>}
                {i.design && <DesignView design={i.design} className="order-sketch" label="Эскиз вашего букета" />}
              </div>
            ))}
            <div className="sum-row" style={{ marginTop: 8 }}><span>Товары</span><span>{money(o.items_total)}</span></div>
            <div className="sum-row"><span>{o.fulfillment === "pickup" ? "Самовывоз" : "Доставка"}</span><span>{o.delivery_cost ? money(o.delivery_cost) : "бесплатно"}</span></div>
            <div className="sum-row total"><span>Итого</span><span>{money(o.total)}</span></div>
          </div>
          <div className="card">
            <div className="panel-title">История</div>
            <ul className="timeline">
              {o.history.map((h, k) => (
                <li key={k}>
                  <b>{h.label}</b> <span className="muted small">· {dateTime(h.at)}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <aside className="stack">
          <div className="card">
            <div className="panel-title">{o.fulfillment_label}</div>
            <dl className="kv">
              <dt>Дата</dt>
              <dd>{dateLong(o.date)}</dd>
              {o.time_from && (
                <>
                  <dt>Интервал</dt>
                  <dd>{hm(o.time_from)}–{hm(o.time_to)}</dd>
                </>
              )}
              {o.delivery && (
                <>
                  <dt>Адрес</dt>
                  <dd>{o.delivery.address}{o.delivery.apartment ? `, кв. ${o.delivery.apartment}` : ""}</dd>
                  {(o.delivery.surprise || o.delivery.anonymous) && (
                    <>
                      <dt>Вручение</dt>
                      <dd>{[o.delivery.surprise && "сюрприз — без звонка заранее", o.delivery.anonymous && "не говорим, от кого"].filter(Boolean).join("; ")}</dd>
                    </>
                  )}
                  <dt>Зона</dt>
                  <dd>{o.delivery.zone}</dd>
                  <dt>Доставка</dt>
                  <dd>{o.delivery.status_label}</dd>
                </>
              )}
              {o.pickup && (
                <>
                  <dt>Адрес</dt>
                  <dd>{o.pickup.address}</dd>
                  {o.pickup.ready_at && (
                    <>
                      <dt>Готов к</dt>
                      <dd>{dateTime(o.pickup.ready_at)}</dd>
                    </>
                  )}
                </>
              )}
              <dt>Заказчик</dt>
              <dd>{o.contact_name}, {o.contact_phone}</dd>
              {o.recipient_name && (
                <>
                  <dt>Получатель</dt>
                  <dd>{o.recipient_name}</dd>
                </>
              )}
              <dt>Оплата</dt>
              <dd>{o.payment_method_label} · {o.payment_status_label}</dd>
              {o.card_text && (
                <>
                  <dt>Открытка</dt>
                  <dd>«{o.card_text}»</dd>
                </>
              )}
            </dl>
          </div>
          {o.notify_channels && o.notify_channels.length > 0 ? (
            <div className="card small notify-card">
              <b>Уведомления включены</b>
              <span className="muted">Изменения статуса придут в {o.notify_channels.map((c) => c.label).join(" и ")}.</span>
            </div>
          ) : (shop.customer_login?.telegram || shop.customer_login?.vk) && !["cancelled", "delivered", "completed"].includes(o.status) ? (
            <div className="card small notify-card">
              <b>Получать статус в мессенджере</b>
              <span className="muted">Подключите Telegram или ВКонтакте — пришлём сообщение, когда букет соберут и передадут курьеру.</span>
              <MessengerLogin orderToken={o.token} onSignedIn={() => load()} compact />
            </div>
          ) : null}
          <div className="card small">
            <b>Вопросы по заказу?</b>
            <p className="muted" style={{ margin: "6px 0 0" }}>
              {o.shop.phone} · {o.shop.working_hours}
              <br />
              {o.shop.address}
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
