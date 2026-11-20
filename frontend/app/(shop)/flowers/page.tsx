import Link from "next/link";
import { redirect } from "next/navigation";
import { CatalogView } from "@/components/CatalogView";
import { ProductCard } from "@/components/ProductCard";
import { serverGet } from "@/lib/api";
import type { Category, Product, ShopSettings } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("flowers", "/flowers");
}

export default async function Flowers() {
  const [s, flowers, extras, cats] = await Promise.all([
    serverGet<ShopSettings>("/settings/public"),
    serverGet<Product[]>("/catalog/products?type=flower,greenery"),
    serverGet<Product[]>("/catalog/products?type=card,addon"),
    serverGet<Category[]>("/catalog/categories?type=flower"),
  ]);
  if (s && !s.flowers_section_enabled) redirect("/bouquets");
  const constructor = s?.constructor_section_enabled !== false;
  return (
    <div className="container">
      <div className="page-head">
        <div className="eyebrow">Наличие на складе</div>
        <h1>Цветы поштучно</h1>
        <p className="muted" style={{ maxWidth: 680 }}>
          Цена указана за один стебель или ветку.
          {constructor && (
            <>
              {" "}Можно купить цветы отдельно или собрать из них свой букет в{" "}
              <Link href="/constructor" style={{ color: "var(--lilac)", fontWeight: 700 }}>конструкторе</Link>.
            </>
          )}{" "}
          Отдельные цветы заказываются только на сайте — в ботах доступны готовые букеты.
        </p>
      </div>
      <CatalogView products={flowers || []} categories={(cats || []).map((c) => c.name)} groupLabel="Все цветы" />
      <div className="page-head" style={{ marginTop: 30 }}>
        <h2>Открытки и дополнения</h2>
      </div>
      <div className="products">
        {(extras || []).map((p) => (
          <ProductCard key={p.id} p={p} />
        ))}
      </div>
      <div style={{ height: 60 }} />
    </div>
  );
}

