// Проверка полей форм на клиенте. Те же правила повторяет бэкенд (apps/core/validation.py) —
// клиент просто подсказывает раньше, а сервер не даёт записать некорректные данные в обход формы.
import { ApiError } from "./api";

export type Errors = Record<string, string>;
type Opt = { required?: boolean; min?: number; max?: number };

const NAME_RE = /^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё .'\-]*$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}$/;
const HEX_RE = /^#[0-9A-Fa-f]{6}$/;
const SKU_RE = /^[A-Za-z0-9][A-Za-z0-9_\-]*$/;
const TIME_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

export const isBlank = (v: unknown) => v === null || v === undefined || String(v).trim() === "";

export function text(v: string, label: string, { required = false, min = 0, max = 255 }: Opt = {}): string | null {
  const s = (v || "").trim();
  if (!s) return required ? `Заполните поле «${label}»` : null;
  if (s.length < min) return `Минимум ${min} символа`;
  if (s.length > max) return `Не больше ${max} символов (сейчас ${s.length})`;
  return null;
}

export function int(v: string | number, label: string, { required = true, min, max }: Opt = {}): string | null {
  if (isBlank(v)) return required ? `Заполните поле «${label}»` : null;
  const s = String(v).replace(/\s/g, "").replace(",", ".");
  if (!/^-?\d+$/.test(s)) return "Нужно целое число";
  const n = Number(s);
  if (min !== undefined && n < min) return `Не меньше ${min}`;
  if (max !== undefined && n > max) return `Не больше ${max}`;
  return null;
}

/** Сумма в рублях из поля ввода: до 2 знаков после запятой, без минуса */
export function rub(v: string, label: string, { required = true, min = 0, max = 1_000_000 }: Opt = {}): string | null {
  if (isBlank(v)) return required ? `Укажите «${label}»` : null;
  const s = String(v).replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return "Сумма числом, например 1500 или 99,90";
  const n = Number(s);
  if (n < min) return `Не меньше ${min} ₽`;
  if (n > max) return `Не больше ${max.toLocaleString("ru-RU")} ₽`;
  return null;
}

export function hex(v: string, label: string, required = false): string | null {
  if (isBlank(v)) return required ? `Укажите «${label}»` : null;
  return HEX_RE.test(v.trim()) ? null : "Цвет в формате #RRGGBB, например #3E5B36";
}

export function phone(v: string, label = "Телефон", required = true): string | null {
  if (isBlank(v)) return required ? `Укажите «${label}»` : null;
  let d = v.replace(/\D/g, "");
  if (d.length === 11 && d[0] === "8") d = "7" + d.slice(1);
  if (d.length === 10 && d[0] === "9") d = "7" + d;
  return d.length === 11 && d[0] === "7" ? null : "Номер в формате +7 900 000-00-00";
}

export function email(v: string, required = false): string | null {
  if (isBlank(v)) return required ? "Укажите e-mail" : null;
  return v.trim().length <= 120 && EMAIL_RE.test(v.trim()) ? null : "Адрес вида name@example.ru";
}

export function personName(v: string, label = "Имя", required = true): string | null {
  if (isBlank(v)) return required ? `Укажите «${label}»` : null;
  const s = v.trim();
  if (s.length < 2 || !NAME_RE.test(s)) return "Только буквы, пробел и дефис, минимум 2 символа";
  if (s.length > 80) return "Слишком длинное имя";
  return null;
}

export function url(v: string, hosts: string[] = []): string | null {
  if (isBlank(v)) return null;
  const m = /^https:\/\/([^/\s]+)(\/\S*)?$/.exec(v.trim());
  if (!m) return "Ссылка должна начинаться с https://";
  const host = m[1].toLowerCase().replace(/^www\./, "");
  if (hosts.length && !hosts.includes(host)) return `Нужна ссылка на ${hosts.join(" или ")}`;
  return null;
}

export function sku(v: string): string | null {
  if (isBlank(v)) return null;
  return v.trim().length <= 32 && SKU_RE.test(v.trim()) ? null : "Латинские буквы, цифры и дефис, до 32 символов";
}

export function time(v: string, label: string): string | null {
  return TIME_RE.test((v || "").trim()) ? null : `${label}: время ЧЧ:ММ`;
}

/** Собирает ошибки: { поле: текст } только для полей с ошибкой */
export function collect(pairs: Record<string, string | null | undefined>): Errors {
  const out: Errors = {};
  for (const [k, v] of Object.entries(pairs)) if (v) out[k] = v;
  return out;
}

export const hasErrors = (e: Errors) => Object.keys(e).length > 0;

/** Ошибка сервера → подсветка поля. Возвращает текст для уведомления, если поле не найдено в форме */
export function serverError(e: unknown, setErrors?: (fn: (prev: Errors) => Errors) => void, known?: string[]): string {
  const msg = e instanceof ApiError ? e.message : "Не удалось сохранить. Попробуйте ещё раз";
  const field = e instanceof ApiError ? (e.details?.field as string | undefined) : undefined;
  if (field && setErrors && (!known || known.includes(field))) {
    setErrors((prev) => ({ ...prev, [field]: msg }));
  }
  return msg;
}
