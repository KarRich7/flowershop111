import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Gallery, ProductBuy } from "@/components/ProductBuy";
import { ProductCard } from "@/components/ProductCard";
import { serverGet } from "@/lib/api";
import { deliveryArea } from "@/lib/format";
import { absUrl, buildMetadata, fillTemplate, jsonLd, shopSettings } from "@/lib/seo";
import type { Product, ProductDetail, ShopSettings } from "@/lib/types";

// Заголовок и описание для поисковиков — по шаблону из админки (Настройки → «Поиск (SEO)» → «Страницы товаров»)
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const [p, s] = await Promise.all([serverGet<ProductDetail>(`/catalog/products/${slug}`), shopSettings()]);
  if (!p) return { title: "Товар не найден" };
  const tpl = s?.seo?.pages?.product;
  const vars = { name: p.name, price: p.price, description: p.short_description || p.description };
  const title = tpl ? fillTemplate(tpl.title, vars) : p.name;
  const description = tpl ? fillTemplate(tpl.description, vars) : p.short_description;
  return buildMetadata(s, title, description, `/product/${p.slug}`, p.images?.[0]?.url || p.image);
}

export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [p, s] = await Promise.all([
    serverGet<ProductDetail>(`/catalog/products/${slug}`),
    serverGet<ShopSettings>("/settings/public"),
  ]);
  if (!p) notFound();
  // Состав есть только у букетов с рецептом; у цветов, допов, упаковки — нет
  const composition = p.composition ?? [];
  const similar = p.type === "bouquet" ? ((await serverGet<Product[]>("/catalog/products?type=bouquet&in_stock=1")) || []).filter((x) => x.id !== p.id && x.category === p.category).slice(0, 4) : [];
  const back = p.type === "bouquet" || s?.flowers_section_enabled === false ? { href: "/bouquets", label: "Букеты" } : { href: "/flowers", label: "Цветы поштучно" };
  // разметка schema.org Product: поисковики могут показать цену и наличие прямо в выдаче
  const url = absUrl(s, `/product/${p.slug}`);
  const schema = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: p.name,
    description: p.short_description || p.description || undefined,
    image: (p.images?.length ? p.images.map((i) => i.url) : p.image ? [p.image] : []).map((u) => absUrl(s, u)).filter(Boolean),
    category: p.category || undefined,
    url,
    offers: {
      "@type": "Offer",
      price: (p.price / 100).toFixed(2),
      priceCurrency: "RUB",
      availability: p.in_stock || p.made_to_order ? "https://schema.org/InStock" : "https://schema.org/OutOfStock",
      url,
    },
  };
  return (
    <div className="container">
      <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(schema)} />
      <div className="crumbs">
        <Link href="/">Главная</Link> / <Link href={back.href}>{back.label}</Link> / {p.name}
      </div>
      <div className="pd">
        <Gallery p={p} />
        <div className="stack">
          {p.category && <div className="eyebrow">{p.category}</div>}
          <h1>{p.name}</h1>
          {p.short_description && <p className="muted" style={{ fontSize: 16 }}>{p.short_description}</p>}
          <ProductBuy p={p} />
          {p.description && (
            <>
              <hr className="divider" />
              <p>{p.description}</p>
            </>
          )}
          {(composition.length > 0 || p.height_cm) && (
            <div className="card card-tight">
              <dl className="kv">
                {composition.length > 0 && (
                  <>
                    <dt>Состав</dt>
                    <dd>{composition.map((c) => `${c.name} — ${c.quantity} шт.`).join("; ")}</dd>
                  </>
                )}
                {p.height_cm ? (
                  <>
                    <dt>Высота</dt>
                    <dd>≈ {p.height_cm} см</dd>
                  </>
                ) : null}
                {p.color && (
                  <>
                    <dt>Цвет</dt>
                    <dd>
                      <span className="swatch" style={{ background: p.color_hex || "#ccc" }} /> {p.color}
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}
          <div className="notice green small">
            Доставка {deliveryArea(s?.city)} в выбранный интервал, фото букета перед отправкой, или бесплатный самовывоз. Подробнее — в разделе{" "}
            <Link href="/delivery" style={{ fontWeight: 700 }}>«Доставка и оплата»</Link>.
          </div>
        </div>
      </div>
      {similar.length > 0 && (
        <section style={{ paddingBottom: 60 }}>
          <h2>Похожие букеты</h2>
          <div className="products">
            {similar.map((x) => (
              <ProductCard key={x.id} p={x} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
