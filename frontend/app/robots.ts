import type { MetadataRoute } from "next";
import { shopSettings, siteUrl } from "@/lib/seo";

// robots.txt считается при каждом запросе: SITE_INDEXING=true (в .env) открывает сайт поисковикам.
// Пока магазин тестовый — индексация закрыта целиком. Служебные разделы закрыты всегда.
export const dynamic = "force-dynamic";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const open = (process.env.SITE_INDEXING || "").toLowerCase() === "true";
  const privatePaths = ["/admin", "/api/", "/order/", "/pay/", "/checkout", "/cart", "/track"];
  if (!open) return { rules: [{ userAgent: "*", disallow: "/" }] };
  // ссылка на карту сайта (app/sitemap.ts) — поисковики найдут все страницы и товары
  const base = siteUrl(await shopSettings());
  return { rules: [{ userAgent: "*", allow: "/", disallow: privatePaths }], sitemap: base ? `${base}/sitemap.xml` : undefined, host: base || undefined };
}
