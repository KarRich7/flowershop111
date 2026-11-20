// Заголовки (title) и описания (description) страниц для поисковиков. Тексты задаёт владелец
// в админке: Настройки → «Поиск (SEO)»; пустые поля — стандартный текст с названием магазина и городом.
import type { Metadata } from "next";
import { serverGet } from "./api";
import { money } from "./format";
import type { SeoPageKey, ShopSettings } from "./types";

export function shopSettings() {
  return serverGet<ShopSettings>("/settings/public");
}

/** Адрес сайта без «/» в конце: https://cvetyurala.ru */
export function siteUrl(s?: ShopSettings | null): string {
  return (s?.seo?.site_url || "").replace(/\/+$/, "");
}

export function absUrl(s: ShopSettings | null | undefined, path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//.test(path)) return path;
  const base = siteUrl(s);
  return base ? base + path : undefined;
}

export function buildMetadata(s: ShopSettings | null, title: string, description: string, path: string, image?: string | null): Metadata {
  const url = absUrl(s, path);
  const img = absUrl(s, image || s?.hero_image || null);
  return {
    title: { absolute: title },
    description,
    alternates: url ? { canonical: url } : undefined,
    openGraph: {
      type: "website",
      locale: "ru_RU",
      siteName: s?.shop_name,
      title,
      description,
      url,
      images: img ? [img] : undefined,
    },
  };
}

/** Метаданные страницы по ключу из настроек SEO */
export async function pageMetadata(key: SeoPageKey, path: string): Promise<Metadata> {
  const s = await shopSettings();
  const page = s?.seo?.pages?.[key];
  if (!page) return {};
  return buildMetadata(s, page.title, page.description, path);
}

/** Шаблон страниц товаров: {name}, {price}, {description} */
export function fillTemplate(t: string, vars: { name: string; price: number; description?: string }): string {
  const desc = (vars.description || "").replace(/\s+/g, " ").trim();
  const short = desc.length > 140 ? `${desc.slice(0, 137).replace(/\s+\S*$/, "")}…` : desc;
  const withDot = short && !/[.!?…]$/.test(short) ? `${short}.` : short;
  return t
    .replace(/\{name\}/g, vars.name)
    .replace(/\{price\}/g, money(vars.price))
    .replace(/\{description\}/g, withDot)
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,!?])/g, "$1")
    .replace(/\.{2,}/g, ".")
    .trim();
}

/** Безопасная вставка JSON-LD (разметка schema.org для поисковиков) */
export function jsonLd(data: unknown): { __html: string } {
  return { __html: JSON.stringify(data).replace(/</g, "\\u003c") };
}
