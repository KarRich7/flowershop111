"use client";
// Покупатель, вошедший через Telegram / ВКонтакте: профиль, история заказов, выход.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { adoptLegacySession, customerRequest, hasCustomerSession, markSignedIn, SIGNED_IN_KEY } from "@/lib/customer";
import type { CustomerProfile } from "@/lib/types";

type Ctx = {
  me: CustomerProfile | null;
  ready: boolean;
  refresh: () => Promise<CustomerProfile | null>;
  signIn: () => Promise<CustomerProfile | null>;
  logout: () => Promise<void>;
  update: (patch: Partial<Pick<CustomerProfile, "name" | "phone" | "email">>) => Promise<CustomerProfile>;
};

const C = createContext<Ctx>({
  me: null,
  ready: false,
  refresh: async () => null,
  signIn: async () => null,
  logout: async () => {},
  update: async () => {
    throw new Error("no provider");
  },
});
export const useCustomer = () => useContext(C);

export function CustomerProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<CustomerProfile | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    await adoptLegacySession();
    if (!hasCustomerSession()) {
      setMe(null);
      setReady(true);
      return null;
    }
    try {
      const p = await customerRequest<CustomerProfile>("/account/me");
      setMe(p);
      return p;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) markSignedIn(false);
      setMe(null);
      return null;
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    // вход/выход в другой вкладке
    const onStorage = (e: StorageEvent) => e.key === SIGNED_IN_KEY && refresh();
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [refresh]);

  // сервер уже поставил cookie входа — запоминаем только метку и загружаем профиль
  const signIn = useCallback(async () => {
    markSignedIn(true);
    return refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await customerRequest("/account/logout", { method: "POST" });
    } catch {}
    markSignedIn(false);
    setMe(null);
  }, []);

  const update = useCallback(async (patch: Partial<Pick<CustomerProfile, "name" | "phone" | "email">>) => {
    const p = await customerRequest<CustomerProfile>("/account/me", { method: "PATCH", body: patch });
    setMe(p);
    return p;
  }, []);

  const value = useMemo(() => ({ me, ready, refresh, signIn, logout, update }), [me, ready, refresh, signIn, logout, update]);
  return <C.Provider value={value}>{children}</C.Provider>;
}
