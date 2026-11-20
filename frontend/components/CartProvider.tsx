"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, request } from "@/lib/api";
import type { Cart, Composition } from "@/lib/types";

const KEY = "cu_cart_token";

type CartApi = {
  cart: Cart | null;
  loading: boolean;
  add: (productId: number, quantity?: number) => Promise<Cart>;
  addCustom: (composition: Composition, quantity?: number) => Promise<Cart>;
  setQty: (itemId: number, quantity: number) => Promise<Cart>;
  remove: (itemId: number) => Promise<Cart>;
  refresh: () => Promise<Cart | null>;
  reset: () => void;
};

const Ctx = createContext<CartApi | null>(null);

export function useCart(): CartApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("CartProvider missing");
  return v;
}

export function CartProvider({ children }: { children: ReactNode }) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [loading, setLoading] = useState(true);
  const creating = useRef<Promise<string> | null>(null);

  const createToken = useCallback(async () => {
    if (!creating.current) {
      creating.current = request<Cart>("/carts", { method: "POST" }).then((c) => {
        localStorage.setItem(KEY, c.token);
        setCart(c);
        return c.token;
      }).finally(() => {
        creating.current = null;
      });
    }
    return creating.current;
  }, []);

  const token = useCallback(async () => localStorage.getItem(KEY) || (await createToken()), [createToken]);

  const refresh = useCallback(async () => {
    const t = localStorage.getItem(KEY);
    if (!t) {
      setCart(null);
      setLoading(false);
      return null;
    }
    try {
      const c = await request<Cart>(`/carts/${t}`);
      setCart(c);
      return c;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 409 || e.status === 400)) {
        localStorage.removeItem(KEY);
        setCart(null);
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Если корзина устарела (например, уже оформлена), создаём новую и повторяем действие один раз.
  const withCart = useCallback(
    async (fn: (t: string) => Promise<Cart>) => {
      let t = await token();
      try {
        const c = await fn(t);
        setCart(c);
        return c;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.code === "cart_closed")) {
          localStorage.removeItem(KEY);
          t = await createToken();
          const c = await fn(t);
          setCart(c);
          return c;
        }
        throw e;
      }
    },
    [token, createToken],
  );

  const api: CartApi = {
    cart,
    loading,
    refresh,
    add: (productId, quantity = 1) =>
      withCart((t) => request<Cart>(`/carts/${t}/items`, { body: { product_id: productId, quantity } })),
    addCustom: (composition, quantity = 1) =>
      withCart((t) => request<Cart>(`/carts/${t}/custom-bouquet`, { body: { composition, quantity } })),
    setQty: (itemId, quantity) =>
      withCart((t) => request<Cart>(`/carts/${t}/items/${itemId}`, { method: "PATCH", body: { quantity } })),
    remove: (itemId) => withCart((t) => request<Cart>(`/carts/${t}/items/${itemId}`, { method: "DELETE" })),
    reset: () => {
      localStorage.removeItem(KEY);
      setCart(null);
    },
  };
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}
