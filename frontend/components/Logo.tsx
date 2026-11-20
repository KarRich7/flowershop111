import type { ShopSettings } from "@/lib/types";

/** Текстовый логотип в стиле присланного баннера «Цветочный магазин / Цветы Урала».
 *  Если в настройках загружен файл логотипа — показываем его. */
export function Logo({ settings, compact = false }: { settings: Pick<ShopSettings, "shop_name" | "tagline" | "logo">; compact?: boolean }) {
  if (settings.logo) {
    return (
      <span className="logo">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={settings.logo} alt={settings.shop_name} />
      </span>
    );
  }
  const words = settings.shop_name.trim().split(/\s+/);
  const first = words[0] || "";
  const rest = words.slice(1).join(" ");
  return (
    <span className="logo" aria-label={settings.shop_name}>
      {!compact && settings.tagline && <span className="logo-top">{settings.tagline.toUpperCase()}</span>}
      <span className="logo-main">
        <span className="l1">{first.toUpperCase()}</span>
        {rest && <span className="l2">{rest.toUpperCase()}</span>}
      </span>
    </span>
  );
}
