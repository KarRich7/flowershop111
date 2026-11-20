// Индивидуальный букет в корзине, заказе и админке: эскиз покупателя или — для «букета по фото» —
// фото выбранных цветов с пометкой «оформление на усмотрение флориста».
import type { Design } from "@/lib/types";
import { DesignSketch } from "./DesignSketch";

export function DesignView({ design, className = "", label }: { design?: Design; className?: string; label?: string }) {
  if (!design) return null;
  if (!design.florist_choice) return <DesignSketch design={design} className={className} label={label} />;
  const items = new Map((design.items || []).map((i) => [i.id, i]));
  const rows = (design.flowers || []).map((r) => ({ ...r, it: items.get(r.item_id) }));
  const shown = rows.slice(0, 4);
  return (
    <div className={`fchoice ${className}`} role="img" aria-label={`${label || "Букет по фото"}: оформление на усмотрение флориста`}>
      <div className={`fchoice-grid n${shown.length}`}>
        {shown.map((r) => {
          const src = r.it?.image || r.it?.constructor_image;
          return (
            <span key={r.item_id} className="fchoice-cell" style={{ background: r.it?.color_hex || "#eee" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {src && <img src={src} alt="" loading="lazy" />}
              <span className="fchoice-n">×{r.quantity}</span>
            </span>
          );
        })}
      </div>
      <span className="fchoice-tag">Оформит флорист</span>
    </div>
  );
}
