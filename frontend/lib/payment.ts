/** Куда вести покупателя по ссылке на оплату.
 *  Тестовая страница оплаты магазина (/pay/…) открывается внутри сайта, даже если FRONTEND_URL указывает
 *  на localhost, а касса (RollyPay, ЮKassa) — по полному адресу на её домене. */
export function paymentHref(url: string): { href: string; internal: boolean } {
  try {
    const u = new URL(url, window.location.href);
    const bare = (h: string) => h.replace(/^www\./, "");
    const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
    if (bare(u.hostname) === bare(window.location.hostname) || local) return { href: u.pathname + u.search, internal: true };
    return { href: u.href, internal: false };
  } catch {
    return { href: url, internal: url.startsWith("/") };
  }
}
