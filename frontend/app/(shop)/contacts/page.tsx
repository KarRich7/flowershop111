import Link from "next/link";
import { ZoneMap } from "@/components/maps/ZoneMap";
import { FALLBACK_SETTINGS } from "@/components/ShopProvider";
import { serverGet } from "@/lib/api";
import type { ShopSettings } from "@/lib/types";
import { jsonLd, pageMetadata } from "@/lib/seo";

export function generateMetadata() {
  return pageMetadata("contacts", "/contacts");
}

export default async function ContactsPage() {
  const s = (await serverGet<ShopSettings>("/settings/public")) || FALLBACK_SETTINGS;
  const shopPoint = s.maps?.shop || null;
  return (
    <div className="container" style={{ paddingBottom: 64 }}>
      {s.seo?.organization && <script type="application/ld+json" dangerouslySetInnerHTML={jsonLd(s.seo.organization)} />}
      <div className="page-head">
        <h1>Контакты</h1>
      </div>
      <div className="grid-2">
        <div className="card stack">
          <dl className="kv" style={{ fontSize: 15 }}>
            <dt>Адрес</dt><dd>{s.address}</dd>
            <dt>Телефон</dt><dd><a href={`tel:${s.phone.replace(/[^+\d]/g, "")}`}>{s.phone}</a></dd>
            <dt>E-mail</dt><dd>{s.email}</dd>
            <dt>Часы работы</dt><dd>{s.working_hours}</dd>
          </dl>
          {(s.telegram_url || s.vk_url) && (
            <>
              <hr className="divider" />
              <div className="row">
                {s.telegram_url && <a className="btn btn-sm" href={s.telegram_url} target="_blank" rel="noopener noreferrer">Telegram</a>}
                {s.vk_url && <a className="btn btn-sm btn-ghost" href={s.vk_url} target="_blank" rel="noopener noreferrer">ВКонтакте</a>}
              </div>
            </>
          )}
          <p className="hint">Демо-контакты. Адрес, телефон, точку на карте и ссылки на ботов владелец меняет в админ-панели, раздел «Настройки»</p>
        </div>
        <div>
          <ZoneMap zones={[]} shop={shopPoint} shopLabel={`${s.shop_name}, ${s.address}`} zoom={15} className="contacts-map" />
        </div>
      </div>
    </div>
  );
}
