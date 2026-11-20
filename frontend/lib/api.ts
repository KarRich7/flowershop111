// Тонкая обёртка над fetch. В браузере запросы идут на тот же origin (/api/* проксируется Next.js),
// на сервере (SSR) — напрямую на бэкенд по API_INTERNAL_URL.
// Вход сотрудника и покупателя хранится в HttpOnly-cookie: браузер отправляет его сам, а JavaScript
// страницы его не видит. Заголовок «X-Requested-With: fetch» подтверждает серверу, что запрос
// пришёл с нашего сайта (без него cookie для изменений не принимается — защита от CSRF).

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;
  constructor(message: string, code: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export function apiBase(): string {
  if (typeof window === "undefined") return process.env.API_INTERNAL_URL || "http://localhost:8000";
  return "";
}

type Opts = {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  token?: string | null;
  form?: FormData;
};

export async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers || {}) };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`;
  if (typeof window !== "undefined") headers["X-Requested-With"] = "fetch";
  let res: Response;
  try {
    res = await fetch(`${apiBase()}/api/v1${path}`, {
      method: opts.method || (body ? "POST" : "GET"),
      headers,
      body,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("Сервер недоступен. Проверьте, что бэкенд запущен.", "network", 0);
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
    const fallback = (data as { detail?: string })?.detail;
    throw new ApiError(err?.message || fallback || `Ошибка ${res.status}`, err?.code || "error", res.status, err?.details || {});
  }
  return data as T;
}

/** Серверный запрос для страниц (SSR). Возвращает null, если бэкенд недоступен. */
export async function serverGet<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(path);
  } catch {
    return null;
  }
}

export function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
