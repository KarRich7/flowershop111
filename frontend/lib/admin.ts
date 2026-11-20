"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiError, request } from "./api";

/** Старая версия сайта хранила токен в localStorage; теперь вход — в HttpOnly-cookie (см. adoptLegacyToken) */
const LEGACY_TOKEN_KEY = "cu_admin_token";

export type Role = "owner" | "florist" | "courier";
export interface StaffUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  name: string;
  role: Role;
  role_label: string;
  phone: string;
  is_active: boolean;
  is_demo: boolean;
  weak_password?: boolean;
  notify_mode: NotifyMode;
  notify_mode_label: string;
  telegram_linked: boolean;
  vk_linked: boolean;
  on_shift: boolean;
  shift_started_at: string | null;
}

export type NotifyMode = "always" | "shift" | "off";
export const NOTIFY_MODES: [NotifyMode, string][] = [["always", "Всегда"], ["shift", "Только на смене"], ["off", "Не присылать"]];

/** Одноразовые ссылки привязки Telegram/ВК для уведомлений сотруднику (действуют 24 ч). */
export interface MessengerLinks {
  telegram_url: string;
  vk_url: string;
  expires_at: string;
  code_message: string;
  telegram_hint: string;
  vk_hint: string;
}

let adopting: Promise<void> | null = null;

/** Один раз после обновления: токен из localStorage переносится в HttpOnly-cookie и стирается из браузера,
 *  чтобы сотрудникам не пришлось входить заново. */
function adoptLegacyToken(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if (!adopting) {
    adopting = (async () => {
      let legacy: string | null = null;
      try {
        legacy = localStorage.getItem(LEGACY_TOKEN_KEY);
      } catch {}
      if (!legacy) return;
      try {
        await request("/admin/auth/adopt", { method: "POST", token: legacy });
      } catch {}
      try {
        localStorage.removeItem(LEGACY_TOKEN_KEY);
      } catch {}
    })();
  }
  return adopting;
}

export function forgetLegacyToken() {
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {}
}

export async function adminApi<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  await adoptLegacyToken();
  try {
    return await request<T>(`/admin${path}`, opts);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401 && typeof window !== "undefined") {
      if (!window.location.pathname.startsWith("/admin/login")) window.location.href = "/admin/login";
    }
    throw e;
  }
}

export function useAdmin<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      const d = await adminApi<T>(path);
      setData(d);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Рубли из поля ввода → копейки */
export function toKopecks(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(String(v).replace(",", ".").replace(/\s/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : null;
}
export function toRub(k: number | null | undefined): string {
  return k === null || k === undefined ? "" : String(k / 100);
}
