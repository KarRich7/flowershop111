import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { OrdersClosedStrip } from "@/components/OrdersClosed";
import { FALLBACK_SETTINGS, ShopProvider } from "@/components/ShopProvider";
import { serverGet } from "@/lib/api";
import type { ShopSettings } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ShopLayout({ children }: { children: React.ReactNode }) {
  const settings = (await serverGet<ShopSettings>("/settings/public")) || FALLBACK_SETTINGS;
  // Цвета из настроек магазина: основной — акцент кнопок, дополнительный — только логотип.
  // Фон меняем, лишь если владелец задал свой (не исходный демо-цвет).
  const bg = (settings.background_color || "").toUpperCase();
  const style = {
    "--green": settings.primary_color || "#3E5B36",
    "--lilac": settings.accent_color || "#8F6394",
    ...(bg && bg !== "#FAF7F1" && bg !== "#F7F4EE" ? { "--bg": settings.background_color } : {}),
  } as React.CSSProperties;
  return (
    <ShopProvider settings={settings}>
      <div style={style} className="shop-root">
        <Header />
        <OrdersClosedStrip s={settings} />
        <main style={{ minHeight: "60vh" }}>{children}</main>
        <Footer />
      </div>
    </ShopProvider>
  );
}
