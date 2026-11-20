import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { shopSettings, siteUrl } from "@/lib/seo";
import "./fonts.css";
import "./globals.css";

// Шрифты (Cormorant Garamond, Manrope) подключены локально из app/fonts — без next/font/google,
// чтобы `npm run build` (и docker build) не зависел от доступа к fonts.googleapis.com.

// Заголовок и описание по умолчанию, коды подтверждения Яндекс Вебмастера и Google Search Console —
// из админки (Настройки → «Поиск (SEO)»). Страницы задают свои title/description через lib/seo.ts.
export async function generateMetadata(): Promise<Metadata> {
  const s = await shopSettings();
  const shop = s?.shop_name || "Цветы Урала";
  const home = s?.seo?.pages?.home;
  const base = siteUrl(s);
  let metadataBase: URL | undefined;
  try {
    metadataBase = base ? new URL(base) : undefined;
  } catch {
    metadataBase = undefined;
  }
  const verification: Metadata["verification"] = {};
  if (s?.seo?.google_verification) verification.google = s.seo.google_verification;
  if (s?.seo?.yandex_verification) verification.yandex = s.seo.yandex_verification;
  return {
    metadataBase,
    title: { default: home?.title || `${shop} — букеты с доставкой`, template: `%s · ${shop}` },
    description: home?.description || "Цветочная мастерская: готовые букеты с доставкой, самовывоз.",
    verification,
    // Индексация поисковиками управляется robots.txt (app/robots.ts, переменная SITE_INDEXING)
  };
}

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#F7F4EE" };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Страницы собираются на каждый запрос: в них нужен свежий nonce из middleware.ts (строгая CSP).
  // Next.js ставит его своим скриптам сам; здесь достаточно прочитать заголовки.
  await headers();
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
