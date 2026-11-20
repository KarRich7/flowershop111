import Link from "next/link";
import { BouquetCanvas, arrange, type CatalogItem, type Inst } from "@/components/bouquet/draw";
import { Faq } from "@/components/Faq";
import { ArrowRightIcon } from "@/components/Icons";
import { ProductCard } from "@/components/ProductCard";
import { FALLBACK_SETTINGS } from "@/components/ShopProvider";
import { serverGet } from "@/lib/api";
import { jsonLd, pageMetadata } from "@/lib/seo";
import { deliveryArea, money } from "@/lib/format";
import type { Category, ConstructorOptions, FaqBlock, Product, ShopSettings } from "@/lib/types";

export function generateMetadata() {
  return pageMetadata("home", "/");
}

export default async function Home() {
  const [settings, featured, cats, faq] = await Promise.all([
    serverGet<ShopSettings>("/settings/public"),
    serverGet<Product[]>("/catalog/products?type=bouquet&featured=1"),
    serverGet<Category[]>("/catalog/categories"),
    serverGet<{ blocks: FaqBlock[] }>("/faq"),
  ]);
  const s = settings || FALLBACK_SETTINGS;
  const flowersOn = s.flowers_section_enabled !== false;
  const constructorOn = s.constructor_section_enabled !== false;
  const options = constructorOn ? await serverGet<ConstructorOptions>("/constructor/options") : null;
  const list = featured || [];
  const hero = list.find((p) => p.in_stock && p.image) || list.find((p) => p.image);
  const sketch = demoSketch(options);
  const offer = ["Готовые букеты", flowersOn && "цветы поштучно", constructorOn && "конструктор"].filter(Boolean) as string[];
  const offerText = offer.length > 1 ? `${offer.slice(0, -1).join(", ")} и ${offer[offer.length - 1]}` : "Свежие готовые букеты";

  return (
    <>
      <section className="hero">
        <div className="container hero-grid">
          <div>
            <h1>Цветы с доставкой {deliveryArea(s.city)}</h1>
            <p className="hero-lead">
              {offerText}. На сайте только то, что сегодня есть в мастерской, а привезём в выбранный интервал.
            </p>
            <div className="hero-actions">
              <Link href="/bouquets" className="btn btn-lg">Выбрать букет</Link>
              {constructorOn && <Link href="/constructor" className="btn btn-lg btn-ghost">Собрать свой</Link>}
            </div>
            {s.free_delivery_from ? (
              <div className="hero-facts">
                <div><b>от {money(s.free_delivery_from)}</b><span>доставка бесплатно</span></div>
              </div>
            ) : null}
          </div>
          {hero && (
            <div className="hero-visual">
              <Link href={`/product/${hero.slug}`} className="hero-photo">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={hero.image || ""} alt={hero.name} />
              </Link>
              <Link href={`/product/${hero.slug}`} className="hero-tag">
                <b>{hero.name}</b>
                <span className="muted small">{hero.short_description}</span>
                <div className="row-between">
                  <span className="price">{money(hero.price)}</span>
                  <span>{hero.in_stock ? "в наличии" : hero.made_to_order ? "под заказ" : "нет в наличии"}</span>
                </div>
              </Link>
            </div>
          )}
        </div>
      </section>

      <section className="section-sm">
        <div className="container">
          <div className="row-between" style={{ marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>Популярные букеты</h2>
            <Link href="/bouquets" className="link-arrow">Весь каталог <ArrowRightIcon /></Link>
          </div>
          {cats && cats.length > 0 && (
            <div className="chips scroll" style={{ marginBottom: 20 }}>
              {cats.map((c) => (
                <Link key={c.name} href={`/bouquets?category=${encodeURIComponent(c.name)}`} className="chip">
                  {c.name} <span className="count">{c.in_stock}</span>
                </Link>
              ))}
            </div>
          )}
          {list.length ? (
            <div className="products">
              {list.slice(0, 8).map((p) => (
                <ProductCard key={p.id} p={p} />
              ))}
            </div>
          ) : (
            <div className="notice amber">Каталог временно недоступен. Проверьте, что бэкенд запущен</div>
          )}
        </div>
      </section>

      {constructorOn && (
        <section className="section">
          <div className="container">
            <div className="promo">
              <div>
                <h2>Соберите букет из того, что есть в&nbsp;наличии</h2>
                <p className="muted">
                  Перенесите цветы на букет, выберите упаковку, ленту и открытку. Цена считается сразу по сегодняшним ценам, флорист соберёт по вашему эскизу.
                </p>
                <div className="row">
                  <Link href="/constructor" className="btn">Открыть конструктор</Link>
                  {flowersOn && <Link href="/flowers" className="btn btn-ghost">Цветы в наличии</Link>}
                </div>
              </div>
              {sketch && (
                <Link href="/constructor" className="sketch promo-sketch" aria-label="Открыть конструктор">
                  <BouquetCanvas catalog={sketch.catalog} insts={sketch.insts} packaging={sketch.packaging} ribbon={sketch.ribbon} card={{ text: "С днём рождения" }} label="Пример букета из конструктора" />
                </Link>
              )}
            </div>
          </div>
        </section>
      )}

      <Faq s={s} blocks={faq?.blocks || []} />
      {s.seo?.organization && <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(s.seo.organization)} />}

      {(s.telegram_url || s.vk_url) && (
        <section className="section">
          <div className="container">
            <h2>Заказ в мессенджерах</h2>
            <p className="muted" style={{ maxWidth: 640 }}>
              В ботах можно посмотреть каталог готовых букетов, проверить наличие, оформить заказ и получать уведомления о статусе.
            </p>
            <div className="bots">
              {s.telegram_url && (
                <div className="card bot-card">
                  <div className="bot-ico tg">TG</div>
                  <div>
                    <b>Telegram-бот</b>
                    <p className="muted small">Чат-бот с кнопками: каталог, заказ и статус доставки.</p>
                    <a className="btn btn-sm" href={s.telegram_url} target="_blank" rel="noopener noreferrer">Открыть в Telegram</a>
                  </div>
                </div>
              )}
              {s.vk_url && (
                <div className="card bot-card">
                  <div className="bot-ico vk">VK</div>
                  <div>
                    <b>Сообщения сообщества ВКонтакте</b>
                    <p className="muted small">Каталог и заказ прямо в диалоге с сообществом.</p>
                    <a className="btn btn-sm" href={s.vk_url} target="_blank" rel="noopener noreferrer">Написать в VK</a>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
}

/** Пример букета для блока конструктора: собираем из реальных позиций в наличии */
function demoSketch(o: ConstructorOptions | null) {
  if (!o || !o.flowers.length) return null;
  const catalog = new Map<number, CatalogItem>();
  [...o.flowers, ...o.greenery, ...o.packaging, ...o.ribbons].forEach((p) =>
    catalog.set(p.inventory_item_id, { id: p.inventory_item_id, name: p.name, species: p.species, color_hex: p.color_hex, type: p.type, constructor_image: p.constructor_image }),
  );
  const pick = (re: RegExp) => o.flowers.find((f) => re.test(`${f.species} ${f.name}`.toLowerCase()));
  const fl = [pick(/пионовид/), pick(/эустом/), pick(/кустов/), pick(/ранунк|гортенз/)].filter(Boolean) as Product[];
  const flowers = fl.length >= 2 ? fl : o.flowers.slice(0, 3);
  const plan: [number, number][] = flowers.map((f, i) => [f.inventory_item_id, [5, 4, 3, 2][i] || 2]);
  const green = o.greenery.find((g) => g.name.toLowerCase().includes("эвкалипт")) || o.greenery[0];
  if (green) plan.push([green.inventory_item_id, 4]);
  let uid = 0;
  const raw: Inst[] = plan.flatMap(([id, n]) => Array.from({ length: n }, () => ({ uid: ++uid, item_id: id, u: 0, v: 0, r: 0 })));
  const pack = o.packaging.find((p) => p.name.toLowerCase().includes("крафт")) || o.packaging[0];
  const rib = o.ribbons.find((p) => p.name.toLowerCase().includes("шпагат")) || o.ribbons[0];
  return {
    catalog,
    insts: arrange(raw, catalog),
    packaging: pack ? catalog.get(pack.inventory_item_id) : null,
    ribbon: rib ? catalog.get(rib.inventory_item_id) : null,
  };
}
