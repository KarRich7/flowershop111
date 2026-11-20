// Эскиз индивидуального букета из сохранённого состава (корзина, страница заказа, карточка заказа в админке).
import type { Design } from "@/lib/types";
import { BouquetCanvas, arrange, freeSpot, type CatalogItem, type Inst } from "./draw";

export function DesignSketch({ design, className = "", label }: { design?: Design; className?: string; label?: string }) {
  if (!design) return null;
  const catalog = new Map<number, CatalogItem>((design.items || []).map((i) => [i.id, i]));
  const want = new Map<number, number>();
  [...(design.flowers || []), ...(design.greenery || [])].forEach((r) => want.set(r.item_id, (want.get(r.item_id) || 0) + r.quantity));
  let uid = 0;
  let insts: Inst[] = (design.layout || [])
    .filter((p) => want.has(p.item_id))
    .map((p) => ({ uid: ++uid, item_id: p.item_id, u: p.x * 2 - 1, v: p.y * 2 - 1, r: p.r || 0, f: !!p.f }));
  const placed = new Map<number, number>();
  insts.forEach((i) => placed.set(i.item_id, (placed.get(i.item_id) || 0) + 1));
  const missing: Inst[] = [];
  want.forEach((n, id) => {
    for (let k = placed.get(id) || 0; k < n; k++) missing.push({ uid: ++uid, item_id: id, u: 0, v: 0, r: 0 });
  });
  if (!insts.length) insts = arrange(missing, catalog);
  else
    missing.forEach((m) => {
      const green = catalog.get(m.item_id)?.type === "greenery";
      insts.push({ ...m, ...freeSpot(insts, green, m.uid) });
    });
  const pack = design.packaging_id ? catalog.get(design.packaging_id) : null;
  const ribbon = design.ribbon_id ? catalog.get(design.ribbon_id) : null;
  return (
    <div className={`sketch ${className}`}>
      <BouquetCanvas
        catalog={catalog}
        insts={insts}
        packaging={pack}
        ribbon={ribbon}
        card={design.card_id ? { text: design.card_text || "" } : null}
        label={label || "Эскиз индивидуального букета"}
      />
    </div>
  );
}
