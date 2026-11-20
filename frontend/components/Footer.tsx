"use client";
import Link from "next/link";
import { useShop } from "./ShopProvider";
import { Logo } from "./Logo";
import { deliveryArea } from "@/lib/format";

export function Footer() {
  const s = useShop();
  return (
    <footer className="footer">
      <div className="container footer-grid">
        <div>
          <Logo settings={s} />
          <p className="muted small" style={{ marginTop: 14, maxWidth: 320 }}>
            Свежие букеты{s.flowers_section_enabled !== false ? " и цветы поштучно" : ""} с доставкой {deliveryArea(s.city)}.{s.demo_notice !== false ? " Демонстрационная версия магазина." : ""}
          </p>
        </div>
        <div>
          <h4>Магазин</h4>
          <Link href="/bouquets">Готовые букеты</Link>
          {s.flowers_section_enabled !== false && <Link href="/flowers">Цветы поштучно</Link>}
          {s.constructor_section_enabled !== false && <Link href="/constructor">Конструктор букета</Link>}
          {s.telegram_url && <a href={s.telegram_url} target="_blank" rel="noopener noreferrer">Telegram</a>}
          {s.vk_url && <a href={s.vk_url} target="_blank" rel="noopener noreferrer">ВКонтакте</a>}
        </div>
        <div>
          <h4>Покупателям</h4>
          <Link href="/delivery">Доставка и оплата</Link>
          <Link href="/track">Мой заказ</Link>
          <Link href="/about">О нас</Link>
          <Link href="/contacts">Контакты</Link>
        </div>
        <div>
          <h4>Контакты</h4>
          <span className="small">{s.address}</span>
          {s.phone && <a href={`tel:${s.phone.replace(/[^+\d]/g, "")}`}>{s.phone}</a>}
          <span className="small muted">{s.working_hours}</span>
        </div>
      </div>
      <div className="container tiny muted" style={{ marginTop: 26 }}>
        © {new Date().getFullYear()} {s.shop_name}.
        {s.demo_notice !== false && " Тестовый MVP: фотографии букетов — AI-сгенерированные демо-изображения, данные покупателей вымышленные."}
      </div>
    </footer>
  );
}
