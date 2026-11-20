"use client";
import Link from "next/link";
import { use, useState } from "react";
import { useStaff } from "@/components/admin/AdminShell";
import { ErrorBox, Loading, Modal, StatusBadge } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin, type StaffUser } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { dateLong, dateTime, hm, money } from "@/lib/format";
import type { OrderPublic, QuoteLine } from "@/lib/types";
import { DesignView } from "@/components/bouquet/DesignView";
import { ExternalIcon } from "@/components/Icons";

type AdminOrder = Omit<OrderPublic, "items" | "delivery"> & {
  id: number;
  contact_phone: string;
  recipient_phone: string;
  contact_email?: string;
  allowed_transitions: { status: string; label: string }[];
  created_by: string | null;
  customer?: { id: number; name: string; phone: string } | null;
  delivery?: NonNullable<OrderPublic["delivery"]> & { entrance?: string; floor?: string; address_verified?: boolean; courier?: StaffUser | null; assigned_at?: string | null; delivered_at?: string | null };
  warning?: string;
  events?: { type: string; from: string; to: string; to_label: string; message: string; actor: string; at: string }[];
  payments?: { id: number; provider: string; amount: number; status: string; status_label: string; is_test: boolean; created_at: string; paid_at: string | null; failure_reason: string; url: string }[];
  reservations?: { item: string; quantity: number; kind: string; status: string; expires_at: string | null }[];
  notifications?: { channel: string; status: string; text: string; at: string; error: string }[];
  items: (OrderPublic["items"][number] & { sku?: string; plan?: Record<string, number>; wishes?: string; card_text?: string; composition: QuoteLine[] | null })[];
};

export default function OrderDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const user = useStaff();
  const toast = useToast();
  const { data: o, error, setData } = useAdmin<AdminOrder>(`/orders/${id}`);
  const { data: couriers } = useAdmin<StaffUser[]>(user.role === "courier" ? null : "/couriers");
  const [busy, setBusy] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [refundOpen, setRefundOpen] = useState(false);
  const [note, setNote] = useState("");
  const [addrOpen, setAddrOpen] = useState(false);

  async function run(key: string, path: string, body: unknown = {}, method?: string) {
    setBusy(key);
    try {
      const r = await adminApi<AdminOrder>(`/orders/${id}${path}`, { body, method });
      setData(r);
      toast(r.warning || "Готово", r.warning ? "info" : "ok");
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
      return false;
    } finally {
      setBusy("");
    }
  }

  if (error) return <ErrorBox text={error} />;
  if (!o) return <Loading />;
  const isStaff = user.role !== "courier";
  const canConfirm = isStaff && ["new", "awaiting_confirmation"].includes(o.status);
  const transitions = o.allowed_transitions.filter((t) => t.status !== "cancelled" && !(canConfirm && ["confirmed", "awaiting_payment"].includes(t.status)));
  const canCancel = isStaff && o.allowed_transitions.some((t) => t.status === "cancelled");
  const hasCustom = o.items.some((i) => i.type === "custom_bouquet");
  const pending = !!o.delivery?.address_pending;
  const addressEditable = isStaff && !!o.delivery && ["new", "awaiting_confirmation", "awaiting_payment", "confirmed", "assembling", "ready"].includes(o.status);
  const photoMissing = o.photo_before && !o.photos.length && o.status !== "cancelled";
  const confirmWhy = [pending && "узнайте адрес у получателя", hasCustom && "проверьте состав индивидуального букета и наличие материалов", o.is_preorder && "проверьте, сможете ли собрать предзаказ к дате"].filter(Boolean).join("; ");
  const refundable = user.role === "owner" && (o.payments || []).some((p) => p.status === "paid" && !["cash_on_delivery", "store_cash", "store_card"].includes(p.provider));

  return (
    <>
      <div className="adm-top">
        <div>
          <Link href="/admin/orders" className="small muted adm-back">← Заказы</Link>
          <h1>Заказ №{o.number}</h1>
          <div className="row" style={{ marginTop: 6 }}>
            <StatusBadge status={o.status} label={o.status_label} />
            <span className={`badge ${o.payment_status === "paid" ? "green" : "amber"}`}>{o.payment_method_label} · {o.payment_status_label}</span>
            <span className="badge gray">{o.source_label}</span>
            {o.is_preorder && <span className="badge lilac">Предзаказ</span>}
            {hasCustom && <span className="badge lilac">Индивидуальный букет</span>}
            {pending && <span className="badge amber">Адрес — узнать у получателя</span>}
            {o.delivery?.surprise && <span className="badge lilac">Сюрприз: не звонить заранее</span>}
            {o.delivery?.anonymous && <span className="badge gray">Анонимно</span>}
            {o.photo_before && <span className={`badge ${o.photos.length ? "green" : "amber"}`}>{o.photos.length ? "Фото отправлено" : "Нужно фото до отправки"}</span>}
          </div>
        </div>
        <div className="row">
          <a className="btn btn-sm btn-ghost" href={`/order/${o.token}`} target="_blank" rel="noreferrer">Страница клиента <ExternalIcon /></a>
        </div>
      </div>

      <div className="od-grid">
        <div className="stack">
          <div className="card">
            <div className="panel-title">Действия</div>
            <div className="row">
              {canConfirm && (
                <button className="btn" disabled={!!busy || pending} title={pending ? "Сначала впишите адрес, который назвал получатель" : undefined} onClick={() => run("confirm", "/confirm")}>
                  {o.status === "awaiting_confirmation" && hasCustom ? "Подтвердить состав" : "Подтвердить заказ"}
                </button>
              )}
              {transitions.map((t) => (
                <button key={t.status} className="btn btn-outline" disabled={!!busy} onClick={() => run(t.status, "/transition", { status: t.status })}>
                  {t.label}
                </button>
              ))}
              {canCancel && <button className="btn btn-ghost" style={{ color: "var(--red)" }} onClick={() => setCancelOpen(true)}>Отменить заказ</button>}
              {refundable && <button className="btn btn-ghost" onClick={() => setRefundOpen(true)}>Возврат оплаты</button>}
              {!canConfirm && !transitions.length && !canCancel && !refundable && <span className="muted small">Нет доступных действий</span>}
            </div>
            {o.status === "awaiting_confirmation" && (
              <p className="hint" style={{ marginTop: 10 }}>
                {confirmWhy ? confirmWhy[0].toUpperCase() + confirmWhy.slice(1) + "." : "Проверьте заказ."} После подтверждения клиент получит ссылку на оплату (если выбрана онлайн-оплата).
              </p>
            )}
            {photoMissing && ["confirmed", "assembling", "ready"].includes(o.status) && (
              <p className="hint" style={{ marginTop: 10 }}>Покупатель просил фото букета: загрузите его ниже — без фото заказ не передать курьеру.</p>
            )}
          </div>

          {pending && isStaff && (
            <div className="card" data-testid="ask-address">
              <div className="panel-title">Адрес — узнать у получателя</div>
              <p className="small" style={{ marginTop: 0 }}>
                Покупатель не знает адрес. Позвоните получателю{o.recipient_name ? ` (${o.recipient_name})` : ""}:{" "}
                <a href={`tel:${o.recipient_phone}`}><b>{o.recipient_phone}</b></a>. Не говорите, что это цветы, — «для вас доставка, куда и когда удобно привезти?»
                {o.delivery?.anonymous ? " Отправителя не называйте." : ""}
              </p>
              <AddressForm busy={!!busy} onSave={(v) => run("address", "/delivery", v, "PATCH")} />
            </div>
          )}

          {isStaff && o.fulfillment === "delivery" && o.status !== "cancelled" && (o.photo_before || o.photos.length > 0 || ["confirmed", "assembling", "ready"].includes(o.status)) && (
            <div className="card" data-testid="order-photos">
              <div className="panel-title">Фото букета</div>
              <PhotoManager
                photos={o.photos}
                busy={!!busy}
                onUpload={async (file) => {
                  const fd = new FormData();
                  fd.append("image", file);
                  setBusy("photo");
                  try {
                    setData(await adminApi<AdminOrder>(`/orders/${id}/photos`, { method: "POST", form: fd }));
                    toast("Фото загружено и отправлено покупателю", "ok");
                  } catch (e) {
                    toast(e instanceof ApiError ? e.message : "Ошибка загрузки", "err");
                  } finally {
                    setBusy("");
                  }
                }}
                onDelete={async (pid) => {
                  setBusy("photo");
                  try {
                    setData(await adminApi<AdminOrder>(`/order-photos/${pid}`, { method: "DELETE" }));
                  } catch (e) {
                    toast(e instanceof ApiError ? e.message : "Ошибка", "err");
                  } finally {
                    setBusy("");
                  }
                }}
              />
              <p className="hint" style={{ marginBottom: 0 }}>
                {o.photo_before ? "Покупатель просил фото перед отправкой. " : ""}Фото видно на странице заказа клиента; о первом фото придёт сообщение.
              </p>
            </div>
          )}

          <div className="card">
            <div className="panel-title">Состав</div>
            {o.items.map((i, k) => (
              <div key={k} style={{ padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="sum-row" style={{ padding: 0 }}>
                  <b>{i.name} <span className="muted">× {i.quantity}</span></b>
                  <span>{money(i.line_total)}</span>
                </div>
                <div className="tiny muted">
                  {i.sku} {i.plan ? `· ${planLabel(i.plan)}` : ""}
                </div>
                {i.composition && (
                  <div className="order-design">
                    {i.design && <DesignView design={i.design} className="order-sketch" label="Эскиз букета от покупателя" />}
                    <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      {i.composition.map((c) => <li key={c.item_id}>{c.name} — {c.quantity}</li>)}
                    </ul>
                  </div>
                )}
                {i.design?.florist_choice && (
                  <div className="notice amber small" style={{ marginTop: 8 }}>
                    Букет по фото: покупатель выбрал только цветы, упаковку и ленту — форма и расстановка на усмотрение флориста.
                  </div>
                )}
                {i.wishes && <div className="small">Пожелания: {i.wishes}</div>}
                {i.card_text && <div className="small">Открытка: «{i.card_text}»</div>}
              </div>
            ))}
            <div className="sum-row" style={{ marginTop: 8 }}><span>Товары</span><span>{money(o.items_total)}</span></div>
            <div className="sum-row"><span>Доставка</span><span>{money(o.delivery_cost)}</span></div>
            <div className="sum-row total"><span>Итого</span><span>{money(o.total)}</span></div>
            {o.card_text && <div className="notice small" style={{ marginTop: 10 }}>Текст открытки: «{o.card_text}»</div>}
            {o.comment && <div className="notice amber small" style={{ marginTop: 10 }}>Комментарий клиента: {o.comment}</div>}
          </div>

          {o.events && (
            <div className="card">
              <div className="panel-title">История и комментарии</div>
              {isStaff && (
                <div className="row" style={{ marginBottom: 14 }}>
                  <input className="input" style={{ flex: 1 }} placeholder="Внутренний комментарий" value={note} onChange={(e) => setNote(e.target.value)} />
                  <button className="btn btn-sm" disabled={!note.trim() || !!busy} onClick={async () => (await run("note", "/notes", { text: note })) && setNote("")}>Добавить</button>
                </div>
              )}
              <ul className="timeline">
                {[...o.events].reverse().map((e, k) => (
                  <li key={k}>
                    <b>{e.to_label || (e.type === "note" && e.actor === "система" ? "Подсказка" : eventLabel(e.type))}</b> <span className="muted small">· {dateTime(e.at)} · {e.actor}</span>
                    {e.message && <div className="small">{e.message}</div>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <aside className="stack">
          <div className="card">
            <div className="panel-title">{o.fulfillment_label}</div>
            <dl className="kv">
              <dt>Дата</dt><dd>{dateLong(o.date)}{o.time_from ? `, ${hm(o.time_from)}–${hm(o.time_to)}` : ""}</dd>
              {o.delivery && (
                <>
                  <dt>Адрес</dt>
                  <dd>
                    {o.delivery.address}
                    {o.delivery.apartment ? `, кв. ${o.delivery.apartment}` : ""}
                    {o.delivery.entrance ? `, под. ${o.delivery.entrance}` : ""}
                    {o.delivery.floor ? `, эт. ${o.delivery.floor}` : ""}
                  </dd>
                  {(o.delivery.surprise || o.delivery.anonymous) && (
                    <>
                      <dt>Вручение</dt>
                      <dd>{[o.delivery.surprise && "сюрприз — не звонить заранее, только у двери", o.delivery.anonymous && "не называть отправителя"].filter(Boolean).join("; ")}</dd>
                    </>
                  )}
                  <dt>Зона</dt><dd>{o.delivery.zone}</dd>
                  <dt>Статус</dt><dd>{o.delivery.status_label}</dd>
                </>
              )}
              {o.pickup && (<><dt>Пункт</dt><dd>{o.pickup.address}</dd></>)}
              <dt>Клиент</dt><dd>{o.contact_name}<br /><a href={`tel:${o.contact_phone}`}>{o.contact_phone}</a>{o.contact_email ? <><br />{o.contact_email}</> : null}</dd>
              {(o.recipient_name || o.recipient_phone) && (<><dt>Получатель</dt><dd>{o.recipient_name} {o.recipient_phone}</dd></>)}
              {o.created_by && (<><dt>Оформил</dt><dd>{o.created_by}</dd></>)}
            </dl>
            {o.delivery && isStaff && couriers && !["delivered", "completed", "cancelled"].includes(o.status) && (
              <div className="field" style={{ marginTop: 14 }}>
                <span>Курьер</span>
                <select className="select" value={o.delivery.courier?.id || ""} disabled={!!busy} onChange={(e) => e.target.value && run("assign", "/assign-courier", { courier_id: Number(e.target.value) })}>
                  <option value="">— не назначен —</option>
                  {couriers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            )}
            {o.delivery?.courier && !isStaff && <p className="small" style={{ marginTop: 10 }}>Курьер: {o.delivery.courier.name}</p>}
            {addressEditable && !pending && (
              addrOpen ? (
                <div style={{ marginTop: 14 }}>
                  <AddressForm busy={!!busy} initial={o.delivery} onCancel={() => setAddrOpen(false)} onSave={async (v) => (await run("address", "/delivery", v, "PATCH")) && setAddrOpen(false)} />
                </div>
              ) : (
                <button className="btn btn-sm btn-ghost" style={{ marginTop: 10 }} onClick={() => setAddrOpen(true)}>Изменить адрес</button>
              )
            )}
          </div>

          {o.payments && o.payments.length > 0 && (
            <div className="card">
              <div className="panel-title">Платежи</div>
              {o.payments.map((p) => (
                <div key={p.id} className="sum-row">
                  <span>
                    {providerLabel(p.provider)} {p.is_test && <span className="badge amber">тест</span>}
                    <div className="tiny muted">{dateTime(p.created_at)}{p.failure_reason ? ` · ${p.failure_reason}` : ""}</div>
                  </span>
                  <span className="center">{money(p.amount)}<div className="tiny muted">{p.status_label}</div></span>
                </div>
              ))}
            </div>
          )}

          {o.reservations && o.reservations.length > 0 && (
            <div className="card">
              <div className="panel-title">Резервы склада</div>
              {o.reservations.map((r, k) => (
                <div key={k} className="sum-row small">
                  <span>{r.item} × {r.quantity}<div className="tiny muted">{r.kind}</div></span>
                  <span className="muted">{r.status}</span>
                </div>
              ))}
            </div>
          )}

          {o.notifications && o.notifications.length > 0 && (
            <div className="card">
              <div className="panel-title">Уведомления клиенту</div>
              <ul className="feed">
                {o.notifications.map((n, k) => (
                  <li key={k}>
                    <div className="tiny muted">{n.channel} · {n.status} · {dateTime(n.at)}</div>
                    <div className="small" style={{ whiteSpace: "pre-wrap" }}>{n.text.slice(0, 220)}</div>
                    {n.error && <div className="tiny muted" style={{ fontStyle: "italic" }}>ℹ {n.error}</div>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>

      {cancelOpen && <ReasonModal title="Отмена заказа" placeholder="Причина отмены (видна клиенту)" action="Отменить заказ" onClose={() => setCancelOpen(false)} onSubmit={async (reason) => (await run("cancel", "/cancel", { reason })) && setCancelOpen(false)} />}
      {refundOpen && <ReasonModal title="Возврат оплаты" placeholder="Причина возврата" action="Вернуть деньги" onClose={() => setRefundOpen(false)} onSubmit={async (reason) => (await run("refund", "/refund", { reason })) && setRefundOpen(false)} />}
    </>
  );
}

type AddressFields = { address: string; apartment: string; entrance: string; floor: string };

function AddressForm({ initial, busy, onSave, onCancel }: { initial?: Partial<AddressFields>; busy: boolean; onSave: (v: AddressFields) => void; onCancel?: () => void }) {
  const [v, setV] = useState<AddressFields>({
    address: initial?.address || "", apartment: initial?.apartment || "", entrance: initial?.entrance || "", floor: initial?.floor || "",
  });
  const set = (k: keyof AddressFields) => (e: React.ChangeEvent<HTMLInputElement>) => setV((x) => ({ ...x, [k]: e.target.value }));
  return (
    <form className="stack" style={{ gap: 10 }} onSubmit={(e) => { e.preventDefault(); onSave(v); }}>
      <input className="input" required maxLength={255} placeholder="Населённый пункт, улица, дом" value={v.address} onChange={set("address")} aria-label="Адрес доставки" />
      <div className="row" style={{ gap: 8 }}>
        <input className="input" style={{ flex: 1 }} maxLength={20} placeholder="Кв./офис" value={v.apartment} onChange={set("apartment")} aria-label="Квартира" />
        <input className="input" style={{ flex: 1 }} maxLength={20} placeholder="Подъезд" value={v.entrance} onChange={set("entrance")} aria-label="Подъезд" />
        <input className="input" style={{ flex: 1 }} maxLength={20} placeholder="Этаж" value={v.floor} onChange={set("floor")} aria-label="Этаж" />
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn btn-sm" disabled={busy || !v.address.trim()}>Сохранить адрес</button>
        {onCancel && <button type="button" className="btn btn-sm btn-ghost" onClick={onCancel}>Отмена</button>}
      </div>
      <span className="hint">Адрес проверяется геокодером; если он в другой зоне, в истории появится подсказка про доплату.</span>
    </form>
  );
}

function PhotoManager({ photos, busy, onUpload, onDelete }: { photos: OrderPublic["photos"]; busy: boolean; onUpload: (f: File) => void; onDelete: (id: number) => void }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      {photos.length > 0 && (
        <div className="order-photos">
          {photos.map((p) => (
            <div key={p.id} className="photo-tile">
              <a href={p.url} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.url} alt="Фото букета" />
              </a>
              <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={() => onDelete(p.id)} aria-label="Удалить фото">✕</button>
            </div>
          ))}
        </div>
      )}
      <label className={`btn btn-sm btn-outline ${busy ? "disabled" : ""}`} style={{ alignSelf: "flex-start" }}>
        {busy ? "Загружаем…" : "Загрузить фото букета"}
        <input type="file" accept="image/*" hidden disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
      </label>
    </div>
  );
}

function ReasonModal({ title, placeholder, action, onClose, onSubmit }: { title: string; placeholder: string; action: string; onClose: () => void; onSubmit: (r: string) => void }) {
  const [r, setR] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <textarea className="textarea" placeholder={placeholder} value={r} onChange={(e) => setR(e.target.value)} />
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button className="btn btn-ghost" onClick={onClose}>Назад</button>
        <button className="btn btn-danger" disabled={!r.trim()} onClick={() => onSubmit(r.trim())}>{action}</button>
      </div>
    </Modal>
  );
}

function planLabel(p: unknown) {
  if (!p || typeof p !== "object") return "";
  const d = p as Record<string, number>;
  const parts: string[] = [];
  if (d.stock) parts.push(`из готовых: ${d.stock}`);
  if (d.made_to_order) parts.push(`собрать по рецептуре: ${d.made_to_order}`);
  if (d.custom) parts.push(`индивидуальная сборка: ${d.custom}`);
  return parts.join(", ");
}
function providerLabel(p: string) {
  return ({ simulator: "Онлайн (симулятор)", rollypay: "Онлайн (RollyPay)", yookassa: "Онлайн (ЮKassa)", cash_on_delivery: "При получении", store_cash: "Наличные", store_card: "Карта в магазине" } as Record<string, string>)[p] || p;
}
function eventLabel(t: string) {
  return ({ address: "Адрес доставки", photo: "Фото букета", note: "Комментарий сотрудника", payment: "Платёж", courier: "Курьер", created: "Заказ создан", status: "Статус" } as Record<string, string>)[t] || t;
}
