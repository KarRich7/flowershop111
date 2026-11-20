"use client";
import { DesignView } from "@/components/bouquet/DesignView";
import { FlowerIcon, XIcon } from "@/components/Icons";
import Link from "next/link";
import { useState } from "react";
import { useCart } from "@/components/CartProvider";
import { OrdersClosedNotice, ordersOpen } from "@/components/OrdersClosed";
import { useShop } from "@/components/ShopProvider";
import { useToast } from "@/components/Toast";
import { ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import type { CartItem } from "@/lib/types";

export default function CartPage() {
  const { cart, loading, setQty, remove } = useCart();
  const shop = useShop();
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);

  async function act(id: number, fn: () => Promise<unknown>) {
    setBusy(id);
    try {
      await fn();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Ошибка", "err");
    } finally {
      setBusy(null);
    }
  }

  const items = cart?.items || [];
  const hasCustom = items.some((i) => i.type === "custom_bouquet");
  const closed = !ordersOpen(shop);
  const blocked = closed || !!cart?.problems.length;
  return (
    <div className="container">
      <div className="page-head">
        <h1>Корзина</h1>
      </div>
      {loading ? (
        <div className="skeleton" style={{ height: 240 }} />
      ) : !items.length ? (
        <div className="card empty">
          <p style={{ fontSize: 17 }}>В корзине пока пусто</p>
          <div className="row" style={{ justifyContent: "center" }}>
            <Link href="/bouquets" className="btn">Выбрать букет</Link>
            {shop.constructor_section_enabled !== false && <Link href="/constructor" className="btn btn-outline">Собрать свой</Link>}
          </div>
        </div>
      ) : (
        <div className="cart-grid">
          <div className="card">
            {items.map((it) => (
              <Line key={it.id} it={it} busy={busy === it.id} onQty={(q) => act(it.id, () => setQty(it.id, q))} onRemove={() => act(it.id, () => remove(it.id))} />
            ))}
          </div>
          <aside className="sticky-aside">
            <div className="card">
              <h3>Итого</h3>
              <div className="sum-row">
                <span>Товары ({cart?.count})</span>
                <span>{money(cart?.items_total)}</span>
              </div>
              <div className="sum-row muted">
                <span>Доставка</span>
                <span>рассчитаем при оформлении</span>
              </div>
              <div className="sum-row total">
                <span>К оплате</span>
                <span>{money(cart?.items_total)}</span>
              </div>
              {cart && cart.problems.length > 0 && (
                <div className="notice red small" style={{ marginTop: 12 }}>
                  Сейчас нельзя заказать: {cart.problems.join(", ")}. Уменьшите количество или удалите позицию.
                </div>
              )}
              {hasCustom && (
                <div className="notice small" style={{ marginTop: 12 }}>
                  В заказе есть индивидуальный букет — флорист подтвердит состав перед сборкой.
                </div>
              )}
              {closed && <OrdersClosedNotice s={shop} className="small" />}
              <Link
                href="/checkout"
                className="btn btn-block btn-lg"
                style={{ marginTop: 16, pointerEvents: blocked ? "none" : undefined, opacity: blocked ? 0.5 : 1 }}
                aria-disabled={blocked}
                tabIndex={blocked ? -1 : undefined}
              >
                Оформить заказ
              </Link>
              <Link href="/bouquets" className="btn btn-block btn-ghost" style={{ marginTop: 8 }}>
                Продолжить покупки
              </Link>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function Line({ it, busy, onQty, onRemove }: { it: CartItem; busy: boolean; onQty: (q: number) => void; onRemove: () => void }) {
  const max = it.type === "product" ? it.available ?? 99 : 10;
  return (
    <div className="cart-line" style={{ opacity: busy ? 0.6 : 1 }}>
      {it.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={it.image} alt={it.name} />
      ) : it.design ? (
        <DesignView design={it.design} className="ph" />
      ) : (
        <div className="ph muted"><FlowerIcon /></div>
      )}
      <div>
        {it.slug ? (
          <Link href={`/product/${it.slug}`} className="pcard-name" style={{ fontSize: 20 }}>{it.name}</Link>
        ) : (
          <div className="pcard-name" style={{ fontSize: 20 }}>{it.name}</div>
        )}
        <div className="muted small">{money(it.unit_price)} за шт.</div>
        {it.composition && (
          <div className="tiny muted" style={{ marginTop: 4 }}>
            {it.composition.map((c) => `${c.name}${c.quantity > 1 ? ` ×${c.quantity}` : ""}`).join(", ")} + работа флориста
          </div>
        )}
        {it.design?.florist_choice && <div className="tiny muted">Букет по фото — оформление на усмотрение флориста</div>}
        {it.card_text && <div className="tiny muted">Открытка: «{it.card_text}»</div>}
        {!it.ok && <div className="error-text">{it.error || `Доступно только ${it.available} шт.`}</div>}
      </div>
      <div className="line-actions row" style={{ justifyContent: "flex-end" }}>
        <div className="qty">
          <button className="icon-btn" disabled={busy || it.quantity <= 1} onClick={() => onQty(it.quantity - 1)} aria-label="Меньше">−</button>
          <span>{it.quantity}</span>
          <button className="icon-btn" disabled={busy || it.quantity >= max} onClick={() => onQty(it.quantity + 1)} aria-label="Больше">+</button>
        </div>
        <b className="nowrap" style={{ minWidth: 90, textAlign: "right" }}>{money(it.total)}</b>
        <button className="icon-btn" onClick={onRemove} disabled={busy} aria-label="Удалить" title="Удалить"><XIcon /></button>
      </div>
    </div>
  );
}
