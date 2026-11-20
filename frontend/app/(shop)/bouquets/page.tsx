import { CatalogView } from "@/components/CatalogView";
import { ProductCard } from "@/components/ProductCard";
import { serverGet } from "@/lib/api";
import type { Category, Product, ShopSettings } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("bouquets", "/bouquets");
}

export default async function Bouquets({ searchParams }: { searchParams: Promise<{ category?: string }> }) {
  const sp = await searchParams;
  const [products, cats, s] = await Promise.all([
    serverGet<Product[]>("/catalog/products?type=bouquet"),
    serverGet<Category[]>("/catalog/categories?type=bouquet"),
    serverGet<ShopSettings>("/settings/public"),
  ]);
  // открытки и дополнения обычно на странице «Цветы поштучно»; если она выключена — показываем их здесь
  const extras = s && !s.flowers_section_enabled ? (await serverGet<Product[]>("/catalog/products?type=card,addon")) || [] : [];
  return (
    <div className="container">
      <div className="page-head">
        <div className="eyebrow">Каталог</div>
        <h1>Готовые букеты</h1>
        <p className="muted" style={{ maxWidth: 680 }}>
          Наличие обновляется в реальном времени: остатки общие для сайта, Telegram, ВКонтакте и продаж в магазине.
          Букеты «под заказ» собираем из цветов в наличии в день доставки.
        </p>
      </div>
      <CatalogView products={products || []} categories={(cats || []).map((c) => c.name)} search={false} initialCategory={sp.category || ""} groupLabel="Все букеты" />
      {extras.length > 0 && (
        <>
          <div className="page-head" style={{ marginTop: 30 }}>
            <h2>Открытки и дополнения</h2>
          </div>
          <div className="products">
            {extras.map((p) => (
              <ProductCard key={p.id} p={p} />
            ))}
          </div>
        </>
      )}
      <div style={{ height: 60 }} />
    </div>
  );
}
