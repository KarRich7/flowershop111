"use client";
import { useState } from "react";
import Link from "next/link";
import type { ProductDetail } from "@/lib/types";
import { money, stockLabel } from "@/lib/format";
import { OrdersClosedNotice, ordersOpen } from "./OrdersClosed";
import { AddToCart } from "./ProductCard";
import { useShop } from "./ShopProvider";

export function Gallery({ p }: { p: ProductDetail }) {
  const imgs = p.images.length ? p.images : p.image ? [{ url: p.image, alt: p.name }] : [];
  const [i, setI] = useState(0);
  return (
    <div className="pd-gallery">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {imgs[i] ? <img src={imgs[i].url} alt={imgs[i].alt || p.name} /> : <div className="skeleton" style={{ aspectRatio: "4/5" }} />}
      {imgs.length > 1 && (
        <div className="pd-thumbs">
          {imgs.map((im, k) => (
            <button key={im.url} className={k === i ? "on" : ""} onClick={() => setI(k)} aria-label={`Фото ${k + 1}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={im.url} alt="" />
            </button>
          ))}
        </div>
      )}
      {p.photo_credit && <div className="tiny muted" style={{ marginTop: 8 }}>{p.photo_credit}</div>}
    </div>
  );
}

export function ProductBuy({ p }: { p: ProductDetail }) {
  const [qty, setQty] = useState(1);
  const shop = useShop();
  const st = stockLabel(p);
  const max = Math.max(p.available, 1);
  const perStem = p.type === "flower" || p.type === "greenery";
  return (
    <div className="stack">
      <div className="row">
        <span className={`badge ${st.tone}`}>{st.text}</span>
        {p.made_to_order && p.in_stock && <span className="badge lilac">Соберём под заказ</span>}
        {p.type_label && <span className="badge gray">{p.type_label}</span>}
      </div>
      <div className="price-lg">
        {money(p.price)}
        {perStem && <span className="muted" style={{ fontSize: 16, fontWeight: 500 }}> за {p.unit}</span>}
      </div>
      {!ordersOpen(shop) && <OrdersClosedNotice s={shop} />}
      {p.in_stock && ordersOpen(shop) && (
        <div className="row">
          <div className="qty">
            <button className="icon-btn" onClick={() => setQty(Math.max(1, qty - 1))} disabled={qty <= 1} aria-label="Меньше">−</button>
            <span>{qty}</span>
            <button className="icon-btn" onClick={() => setQty(Math.min(max, qty + 1))} disabled={qty >= max} aria-label="Больше">+</button>
          </div>
          <AddToCart product={p} quantity={qty} label={`В корзину · ${money(p.price * qty)}`} />
        </div>
      )}
      {p.in_stock && ordersOpen(shop) && <div className="hint">Доступно к заказу: {p.available} {perStem ? p.unit : "шт."}</div>}
      {!p.in_stock && ordersOpen(shop) && (
        <div className="notice amber">
          Сейчас нет в наличии. Посмотрите <Link href="/bouquets" style={{ fontWeight: 700 }}>другие букеты</Link>
          {shop.constructor_section_enabled !== false && (
            <>
              {" "}или <Link href="/constructor" style={{ fontWeight: 700 }}>соберите свой</Link> из цветов в наличии
            </>
          )}
          .
        </div>
      )}
    </div>
  );
}
