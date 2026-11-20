import { ZoneMap } from "@/components/maps/ZoneMap";
import { FALLBACK_SETTINGS } from "@/components/ShopProvider";
import { serverGet } from "@/lib/api";
import { deliveryArea, leadTime, money, plural, todayIso } from "@/lib/format";
import type { ShopSettings, Slot, Zone } from "@/lib/types";
import { pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("delivery", "/delivery");
}

export default async function DeliveryPage() {
  const [s0, zones, slots] = await Promise.all([
    serverGet<ShopSettings>("/settings/public"),
    serverGet<Zone[]>("/delivery/zones"),
    serverGet<Slot[]>(`/delivery/slots?date=${todayIso(1)}&fulfillment=delivery`),
  ]);
  const s = s0 || FALLBACK_SETTINGS;
  const leadText = leadTime(s.min_lead_minutes); // интервал доступен, если до его конца не меньше этого времени
  const pre = s.preorder_threshold_days;
  return (
    <div className="container" style={{ paddingBottom: 60 }}>
      <div className="page-head">
        <h1>Доставка и оплата</h1>
        <p className="muted lead">
          Доставляем {deliveryArea(s.city)} — в цветные зоны на карте{s.free_delivery_from ? `, от ${money(s.free_delivery_from)} бесплатно` : ""}. Адрес отмечается на карте при оформлении, и стоимость считается сразу.
        </p>
      </div>
      <div style={{ marginBottom: 24 }}>
        <ZoneMap zones={zones || []} shop={s.maps?.shop || null} shopLabel={`Самовывоз: ${s.address}`} className="lg" />
      </div>
      <section className="card" style={{ marginBottom: 24 }} data-testid="how-we-deliver">
        <div className="panel-title">Как мы доставляем</div>
        <div className="how-grid">
          <div>
            <b>Фото перед отправкой</b>
            <p>Флорист фотографирует собранный букет, фото появляется на странице заказа{s.customer_login?.telegram || s.customer_login?.vk ? " и приходит в Telegram или ВКонтакте" : ""}. Если что-то не так — поправим до выезда курьера.</p>
          </div>
          <div>
            <b>Не знаете адрес?</b>
            <p>Укажите телефон получателя и примерный район. Флорист сам позвонит и узнает, куда и когда удобно привезти, — не говоря, что это цветы.</p>
          </div>
          <div>
            <b>Сюрприз или звонок заранее</b>
            <p>Обычно курьер звонит получателю перед выездом. Для сюрприза позвонит только у двери. Если получателя нет на месте, свяжемся с вами и договоримся о новом времени или вручим тому, кого вы назовёте.</p>
          </div>
          <div>
            <b>Анонимно</b>
            <p>Можно не говорить, от кого букет: курьер не назовёт отправителя, а открытку можно оставить без подписи.</p>
          </div>
        </div>
      </section>
      <div className="grid-2">
        <div className="card">
          <div className="panel-title">Зоны доставки</div>
          <div className="table-wrap" style={{ border: 0 }}>
            <table className="t">
              <thead>
                <tr><th>Зона</th><th className="num">Стоимость</th><th className="num">Бесплатно от</th></tr>
              </thead>
              <tbody>
                {(zones || []).map((z) => (
                  <tr key={z.id}>
                    <td>
                      <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                        <span className="swatch" style={{ background: z.color, borderRadius: 4 }} />
                        <b style={{ fontWeight: 600 }}>{z.name}</b>
                      </span>
                      <div className="tiny muted">{z.description}</div>
                    </td>
                    <td className="num">{money(z.price)}</td>
                    <td className="num">{z.free_from ? money(z.free_from) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="stack">
          <div className="card">
            <div className="panel-title">Интервалы</div>
            <div className="chips">
              {(slots || []).map((sl) => <span key={sl.id} className="chip">{sl.label}</span>)}
            </div>
            <p className="muted small" style={{ marginTop: 12 }}>
              Курьер привезёт букет в любой момент выбранного интервала. Количество доставок в интервале ограничено, занятые интервалы
              недоступны. Заказ на сегодня принимаем, если до конца интервала не меньше {leadText}. Заказ больше чем на {pre}{" "}
              {plural(pre, "день", "дня", "дней")} вперёд — предзаказ: флорист подтвердит его и закупит цветы к дате.
            </p>
          </div>
          <div className="card">
            <div className="panel-title">Самовывоз</div>
            <p className="small">{s.address}<br />{s.working_hours}</p>
            <p className="muted small">Готовый букет можно забрать примерно через {s.pickup_ready_minutes} минут после подтверждения. Мы напишем, когда заказ будет готов.</p>
          </div>
          <div className="card">
            <div className="panel-title">Оплата</div>
            <ul className="small" style={{ paddingLeft: 18, margin: 0 }}>
              <li><b>Онлайн картой.</b> После оформления откроется страница оплаты. Букет резервируется на {s.online_reservation_minutes} минут, без оплаты резерв снимается автоматически.</li>
              {s.allow_cash_on_delivery && <li><b>При получении.</b> Только для готовых букетов{s.flowers_section_enabled !== false ? " и цветов" : ""}, заказ подтверждает администратор.</li>}
              {s.constructor_section_enabled !== false && <li><b>Индивидуальный букет</b> оплачивается только онлайн: сначала флорист подтверждает состав, затем появляется кнопка оплаты.</li>}
              <li><b>Предзаказ и доставка с уточнением адреса</b> оплачиваются после подтверждения флористом.</li>
            </ul>
            {s.payment_test_mode && <div className="notice amber small" style={{ marginTop: 12 }}>Демо-режим: онлайн-оплата работает через тестовый симулятор, реальные деньги не списываются.</div>}
          </div>
          <div className="card">
            <div className="panel-title">Отмена и возврат</div>
            <p className="small muted" style={{ margin: 0 }}>
              До начала сборки заказ можно отменить по телефону {s.phone}. Если заказ был оплачен онлайн, деньги вернутся на карту.
              {s.constructor_section_enabled !== false ? "Индивидуальный букет после сборки не возвращается." : ""}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
