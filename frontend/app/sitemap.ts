import type { MetadataRoute } from "next";
import { serverGet } from "@/lib/api";
import { shopSettings, siteUrl } from "@/lib/seo";
import type { Product } from "@/lib/types";

// sitemap.xml — список страниц для Яндекса и Google (адрес: https://<сайт>/sitemap.xml).
// Считается при каждом запросе: новые букеты попадают в него сразу. Адрес сайта — FRONTEND_URL в .env.
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const s = await shopSettings();
  const base = siteUrl(s);
  if (!base) return [];
  const flowersOn = s?.flowers_section_enabled !== false;
  const constructorOn = s?.constructor_section_enabled !== false;
  const types = ["bouquet", flowersOn && "flower,greenery"].filter(Boolean).join(",");
  const products = (await serverGet<Product[]>(`/catalog/products?type=${types}`)) || [];
  const now = new Date();
  const page = (path: string, priority: number, changeFrequency: "daily" | "weekly" | "monthly") => ({
    url: base + path,
    lastModified: now,
    changeFrequency,
    priority,
  });
  return [
    page("/", 1, "daily"),
    page("/bouquets", 0.9, "daily"),
    ...(flowersOn ? [page("/flowers", 0.8, "daily")] : []),
    ...(constructorOn ? [page("/constructor", 0.6, "monthly")] : []),
    page("/delivery", 0.7, "monthly"),
    page("/about", 0.5, "monthly"),
    page("/contacts", 0.6, "monthly"),
    ...products.map((p) => page(`/product/${p.slug}`, p.type === "bouquet" ? 0.7 : 0.5, "weekly")),
  ];
}
