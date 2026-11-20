import { NextResponse, type NextRequest } from "next/server";

// Политика безопасности контента (CSP) со случайным одноразовым ключом (nonce) на каждый показ страницы.
// Выполняются только скрипты, помеченные этим ключом (их ставит Next.js), и скрипты, которые они сами
// загрузили (Яндекс Карты), — 'strict-dynamic'. Внедрённый на страницу чужой <script> или обработчик
// onclick="…" браузер не выполнит: без 'unsafe-inline' и 'unsafe-eval'.
// Стили остаются 'unsafe-inline' — их использует React (style={…}) и Яндекс Карты; выполнять код они не могут.
const YANDEX = "https://api-maps.yandex.ru https://*.api-maps.yandex.ru https://yandex.ru https://*.yandex.ru https://*.yandex.net https://yastatic.net";

export function buildCsp(nonce: string, dev = false) {
  return [
    "default-src 'self'",
    // адреса Яндекса — для браузеров без поддержки 'strict-dynamic'; 'unsafe-eval' — только в режиме разработки
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""} ${YANDEX}`,
    `style-src 'self' 'unsafe-inline' blob: ${YANDEX}`,
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src 'self' ${YANDEX}${dev ? " ws:" : ""}`,
    `frame-src 'self' ${YANDEX}`,
    "worker-src 'self' blob:",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function middleware(req: NextRequest) {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const nonce = btoa(String.fromCharCode(...bytes));
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");
  // Next.js берёт nonce из этого заголовка запроса и сам ставит его своим скриптам
  const headers = new Headers(req.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set("Content-Security-Policy", csp);
  return res;
}

export const config = {
  matcher: [
    {
      // страницы сайта; API, фото и статические файлы — без middleware
      source: "/((?!api/|media/|_next/static|_next/image|favicon.ico|icon.png|apple-icon.png|robots.txt|sitemap.xml|fonts/).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
