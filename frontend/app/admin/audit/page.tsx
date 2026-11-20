"use client";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { useAdmin } from "@/lib/admin";
import { dateTime } from "@/lib/format";

type A = { id: number; at: string; user: string; action: string; entity: string; data: Record<string, unknown>; ip: string };

const LABELS: Record<string, string> = {
  login: "Вход", login_failed: "Неудачный вход", logout: "Выход", order_status: "Смена статуса", order_confirm: "Подтверждение заказа",
  order_cancel: "Отмена заказа", courier_assign: "Назначение курьера", order_refund: "Возврат",
  order_address: "Адрес доставки", order_photo: "Фото букета", order_photo_delete: "Удаление фото букета", product_create: "Создание товара",
  product_update: "Изменение товара", product_image: "Фото товара", stock_supply: "Поставка", stock_write_off: "Списание", stock_adjust: "Корректировка",
  stock_inventory: "Инвентаризация", store_sale: "Продажа в магазине", recipe_update: "Изменение рецептуры", bouquet_assemble: "Сборка букетов",
  settings_update: "Изменение настроек", settings_branding: "Логотип / обложка", staff_create: "Новый сотрудник", staff_update: "Изменение сотрудника",
  support_reply: "Ответ клиенту", zone_update: "Зона доставки", slot_update: "Интервал доставки",
};

export default function AuditPage() {
  const { data, error } = useAdmin<A[]>("/audit-log");
  return (
    <>
      <PageTop title="Журнал действий" />
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Время</th><th>Сотрудник</th><th>Действие</th><th>Объект</th><th>Детали</th><th>IP</th></tr></thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.id}>
                  <td className="small nowrap">{dateTime(a.at)}</td>
                  <td>{a.user}</td>
                  <td><b>{LABELS[a.action] || a.action}</b></td>
                  <td className="small muted">{a.entity}</td>
                  <td className="tiny muted" style={{ maxWidth: 360, wordBreak: "break-word" }}>{Object.keys(a.data || {}).length ? JSON.stringify(a.data) : ""}</td>
                  <td className="tiny muted">{a.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
