import type { NextConfig } from "next";

// Все запросы /api/* и /media/* проксируются на Django-бэкенд.
// В Docker это http://backend:8000, локально — http://localhost:8000.
const backend = process.env.API_INTERNAL_URL || "http://localhost:8000";

// Политика безопасности контента (CSP) со случайным nonce на каждый показ страницы — в middleware.ts.
const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "geolocation=(self), camera=(), microphone=(), payment=(), usb=(), interest-cohort=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    // /api и /media отдаёт Django со своими заголовками безопасности
    return [{ source: "/((?!api/|media/).*)", headers: SECURITY_HEADERS }];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/media/:path*", destination: `${backend}/media/:path*` },
    ];
  },
};

export default nextConfig;
