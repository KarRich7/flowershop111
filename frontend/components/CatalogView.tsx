"use client";
import { useMemo, useState } from "react";
import type { Product } from "@/lib/types";
import { ProductCard } from "./ProductCard";

type Sort = "popular" | "price" | "-price";

const OTHER = "Другое";

/**
 * Каталог с вкладками категорий. Порядок вкладок задаёт админка (categories), «Другое» — в конце.
 * search=false — без поиска по названию (страница готовых букетов).
 */
export function CatalogView({ products, initialCategory = "", groupLabel = "Все", categories, search = true }: {
  products: Product[]; initialCategory?: string; groupLabel?: string; categories?: string[]; search?: boolean;
}) {
  const [cat, setCat] = useState(initialCategory);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("popular");
  const [onlyStock, setOnlyStock] = useState(false);

  const catOf = useMemo(() => {
    const known = categories ? new Set(categories) : null;
    return (p: Product) => (p.category && (!known || known.has(p.category)) ? p.category : OTHER);
  }, [categories]);

  const cats = useMemo(() => {
    const m = new Map<string, number>();
    products.forEach((p) => m.set(catOf(p), (m.get(catOf(p)) || 0) + 1));
    const order = categories || [];
    const rank = (n: string) => (n === OTHER ? 1e6 : order.includes(n) ? order.indexOf(n) : 1e5);
    return Array.from(m.entries()).sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0], "ru"));
  }, [products, categories, catOf]);

  const list = useMemo(() => {
    let l = products.filter((p) => (!cat || catOf(p) === cat) && (!onlyStock || p.in_stock));
    const s = search ? q.trim().toLowerCase() : "";
    if (s) l = l.filter((p) => `${p.name} ${p.short_description} ${p.color} ${p.species}`.toLowerCase().includes(s));
    if (sort === "price") l = [...l].sort((a, b) => a.price - b.price);
    if (sort === "-price") l = [...l].sort((a, b) => b.price - a.price);
    if (sort === "popular") l = [...l].sort((a, b) => Number(b.in_stock) - Number(a.in_stock) || Number(b.is_featured) - Number(a.is_featured));
    return l;
  }, [products, cat, q, sort, onlyStock, catOf, search]);

  return (
    <>
      <div className="chips scroll" style={{ marginTop: 8 }}>
        <button className={`chip ${!cat ? "on" : ""}`} onClick={() => setCat("")}>
          {groupLabel} <span className="count">{products.length}</span>
        </button>
        {cats.map(([name, n]) => (
          <button key={name} className={`chip ${cat === name ? "on" : ""}`} onClick={() => setCat(name)}>
            {name} <span className="count">{n}</span>
          </button>
        ))}
      </div>
      <div className={`toolbar ${search ? "" : "no-search"}`}>
        {search && <input className="input" type="search" maxLength={60} placeholder="Поиск по названию, виду или цвету" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Поиск" />}
        <div className="row">
          <label className="checkbox">
            <input type="checkbox" checked={onlyStock} onChange={(e) => setOnlyStock(e.target.checked)} /> Только в наличии
          </label>
          <select className="select" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Сортировка">
            <option value="popular">Сначала популярные</option>
            <option value="price">Сначала дешевле</option>
            <option value="-price">Сначала дороже</option>
          </select>
        </div>
      </div>
      {list.length ? (
        <div className="products">
          {list.map((p) => (
            <ProductCard key={p.id} p={p} />
          ))}
        </div>
      ) : (
        <div className="empty">Ничего не нашлось. Попробуйте изменить фильтры.</div>
      )}
    </>
  );
}
