// Пермское время (UTC+5): в базе часовых поясов оно называется Asia/Yekaterinburg
export const TZ = "Asia/Yekaterinburg";

/** «по Кондратово и Медовому» — куда возим, для заголовков и подвала */
export function deliveryArea(city?: string | null): string {
  const c = (city || "").trim();
  if (!c || /кондратов|медов/i.test(c)) return "по Кондратово и Медовому";
  return `по населённому пункту ${c} и окрестностям`;
}

/** Пункты меню магазина с учётом выключенных разделов */
export function shopNav(s: { flowers_section_enabled?: boolean; constructor_section_enabled?: boolean }) {
  return [
    { href: "/bouquets", label: "Букеты" },
    ...(s.flowers_section_enabled !== false ? [{ href: "/flowers", label: "Цветы поштучно" }] : []),
    ...(s.constructor_section_enabled !== false ? [{ href: "/constructor", label: "Собрать букет" }] : []),
  ];
}

const rub = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

/** Цена хранится в копейках. */
export function money(kopecks: number | null | undefined): string {
  if (kopecks === null || kopecks === undefined) return "—";
  const rubles = kopecks / 100;
  const s = Number.isInteger(rubles)
    ? rub.format(rubles)
    : new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rubles);
  return `${s} ₽`;
}

export function dateLong(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", weekday: "short", timeZone: iso.length === 10 ? undefined : TZ }).format(d);
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(new Date(iso));
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(new Date(iso));
}

export function hm(t: string | null | undefined): string {
  return t ? t.slice(0, 5) : "";
}

/** Сегодняшняя дата в часовом поясе магазина, YYYY-MM-DD. */
export function todayIso(offsetDays = 0): string {
  const now = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  return parts;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export function stockLabel(p: { in_stock: boolean; available: number; made_to_order?: boolean; type?: string }): { text: string; tone: "ok" | "low" | "out" } {
  if (!p.in_stock || p.available <= 0) return { text: "Нет в наличии", tone: "out" };
  if (p.available <= 3) return { text: `Осталось ${p.available} ${p.type === "flower" ? "шт." : "шт."}`, tone: "low" };
  return { text: "В наличии", tone: "ok" };
}

export const STATUS_TONE: Record<string, string> = {
  new: "lilac",
  awaiting_confirmation: "amber",
  awaiting_payment: "amber",
  confirmed: "green",
  assembling: "green",
  ready: "green",
  handed_to_courier: "blue",
  awaiting_pickup: "blue",
  delivered: "gray",
  completed: "gray",
  cancelled: "red",
};

/** Сколько времени до конца интервала нужно на сборку и дорогу: «2 ч 30 мин» (как в правилах доставки) */
export function leadTime(minLeadMinutes: number | null | undefined): string {
  const lead = (minLeadMinutes ?? 120) + 30;
  const h = Math.floor(lead / 60);
  const m = lead % 60;
  return m ? `${h ? `${h} ч ` : ""}${m} мин` : `${h} ч`;
}
