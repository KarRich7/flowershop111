import type { ShopSettings } from "@/lib/types";

/** Принимаются ли сейчас заказы (владелец может закрыть приём в админке: Настройки → «Приём заказов») */
export const ordersOpen = (s: Pick<ShopSettings, "orders_enabled">) => s.orders_enabled !== false;

const tel = (phone: string) => phone.replace(/[^\d+]/g, "");

/** Полоса под шапкой на всех страницах магазина, пока приём закрыт */
export function OrdersClosedStrip({ s }: { s: ShopSettings }) {
  if (ordersOpen(s)) return null;
  return (
    <div className="closed-strip" role="status" data-testid="orders-closed">
      <b>Приём заказов временно закрыт.</b> {s.orders_closed_message}
      {s.phone ? <> Телефон: <a href={`tel:${tel(s.phone)}`}>{s.phone}</a></> : null}
    </div>
  );
}

/** Карточка-предупреждение там, где обычно кладут в корзину или оформляют заказ */
export function OrdersClosedNotice({ s, className = "" }: { s: ShopSettings; className?: string }) {
  if (ordersOpen(s)) return null;
  return (
    <div className={`notice amber ${className}`} role="status">
      <b>Приём заказов временно закрыт.</b> {s.orders_closed_message}
      {s.phone ? <> Телефон: <a href={`tel:${tel(s.phone)}`} style={{ fontWeight: 700 }}>{s.phone}</a></> : null}
    </div>
  );
}
