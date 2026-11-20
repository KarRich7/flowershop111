// Сессия покупателя (вход через Telegram / ВКонтакте). Сам токен хранится в HttpOnly-cookie: браузер
// отправляет его сервером сам, а JavaScript страницы (и чужой внедрённый скрипт) его не видит.
// В localStorage — только метка «на этом устройстве входили» (не секрет), чтобы не спрашивать профиль зря.
import { request } from "./api";

export const SIGNED_IN_KEY = "cu_signed_in";
const LEGACY_KEY = "cu_customer_token"; // старая версия сайта хранила здесь сам токен
const CONTACT_KEY = "cu_contact";

export function hasCustomerSession(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(SIGNED_IN_KEY) === "1" || !!localStorage.getItem(LEGACY_KEY);
  } catch {
    return false;
  }
}
export function markSignedIn(on: boolean) {
  try {
    if (on) localStorage.setItem(SIGNED_IN_KEY, "1");
    else localStorage.removeItem(SIGNED_IN_KEY);
    localStorage.removeItem(LEGACY_KEY);
  } catch {}
}

/** Один раз после обновления сайта: токен из localStorage переносится в HttpOnly-cookie и стирается. */
export async function adoptLegacySession() {
  let legacy: string | null = null;
  try {
    legacy = localStorage.getItem(LEGACY_KEY);
  } catch {}
  if (!legacy) return;
  try {
    await request("/account/session/adopt", { method: "POST", headers: { "X-Customer-Token": legacy } });
    markSignedIn(true);
  } catch {
    markSignedIn(false);
  }
}

export function customerRequest<T>(path: string, opts: Parameters<typeof request>[1] = {}) {
  return request<T>(path, opts);
}

/** Контакты из прошлого заказа на этом устройстве (если покупатель не входил через мессенджер) */
export type SavedContact = { name: string; phone: string; email: string };
export function loadContact(): SavedContact | null {
  try {
    const c = JSON.parse(localStorage.getItem(CONTACT_KEY) || "null");
    return c && typeof c.name === "string" ? c : null;
  } catch {
    return null;
  }
}
export function saveContact(c: SavedContact) {
  try {
    localStorage.setItem(CONTACT_KEY, JSON.stringify(c));
  } catch {}
}
export function forgetContact() {
  try {
    localStorage.removeItem(CONTACT_KEY);
  } catch {}
}

/** +79120001122 → +7 912 000-11-22 */
export function phoneHuman(p: string) {
  const d = (p || "").replace(/\D/g, "");
  if (d.length !== 11) return p || "";
  return `+7 ${d.slice(1, 4)} ${d.slice(4, 7)}-${d.slice(7, 9)}-${d.slice(9)}`;
}

/** Заказы, оформленные на этом устройстве без входа: чтобы найти их без номера и телефона */
const ORDERS_KEY = "cu_orders";
export type SavedOrder = { token: string; number: string; at: string };
export function rememberedOrders(): SavedOrder[] {
  try {
    const list = JSON.parse(localStorage.getItem(ORDERS_KEY) || "[]");
    return Array.isArray(list) ? list.filter((o) => o && typeof o.token === "string" && typeof o.number === "string") : [];
  } catch {
    return [];
  }
}
export function rememberOrder(token: string, number: string) {
  try {
    const rest = rememberedOrders().filter((o) => o.token !== token);
    localStorage.setItem(ORDERS_KEY, JSON.stringify([{ token, number, at: new Date().toISOString() }, ...rest].slice(0, 10)));
  } catch {}
}
export function forgetOrders() {
  try {
    localStorage.removeItem(ORDERS_KEY);
  } catch {}
}
