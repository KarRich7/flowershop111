"use client";
import Link from "next/link";
import { useState } from "react";
import type { Product } from "@/lib/types";
import { money, stockLabel } from "@/lib/format";
import { useCart } from "./CartProvider";
import { ordersOpen } from "./OrdersClosed";
import { useShop } from "./ShopProvider";
import { useToast } from "./Toast";
import { ApiError } from "@/lib/api";

export function ProductCard({ p }: { p: Product }) {
  const st = stockLabel(p);
  const href = p.type === "bouquet" ? `/product/${p.slug}` : `/product/${p.slug}`;
  return (
    <article className="pcard">
      <Link href={href} className={`pcard-img ${st.tone === "out" ? "out" : ""}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {p.image ? <img src={p.image} alt={p.name} loading="lazy" /> : null}
        <span className={`badge ${st.tone}`}>{st.text}</span>
      </Link>
      <div className="pcard-body">
        <Link href={href} className="pcard-name">
          {p.name}
        </Link>
        <div className="pcard-desc">{p.short_description}</div>
        <div className="pcard-foot">
          <span className="price">
            {money(p.price)}
            {p.type === "flower" || p.type === "greenery" ? <span className="muted small"> / {p.unit}</span> : null}
          </span>
          <AddToCart product={p} small />
        </div>
      </div>
    </article>
  );
}

export function AddToCart({ product, quantity = 1, small = false, label }: { product: Product; quantity?: number; small?: boolean; label?: string }) {
  const { add } = useCart();
  const shop = useShop();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const closed = !ordersOpen(shop);
  const disabled = closed || !product.in_stock || product.available <= 0 || busy;
  return (
    <button
      className={`btn ${small ? "btn-sm" : "btn-lg"}`}
      disabled={disabled}
      title={closed ? shop.orders_closed_message : undefined}
      onClick={async () => {
        setBusy(true);
        try {
          await add(product.id, quantity);
          toast(`«${product.name}» в корзине`, "ok");
        } catch (e) {
          toast(e instanceof ApiError ? e.message : "Не удалось добавить", "err");
        } finally {
          setBusy(false);
        }
      }}
    >
      {closed ? "Заказы на паузе" : !product.in_stock || product.available <= 0 ? "Нет в наличии" : busy ? "Добавляем…" : label || "В корзину"}
    </button>
  );
}
