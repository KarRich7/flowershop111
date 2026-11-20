"use client";
import { BagIcon, MenuIcon, XIcon } from "@/components/Icons";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useCart } from "./CartProvider";
import { useCustomer } from "./CustomerProvider";
import { useShop } from "./ShopProvider";
import { Logo } from "./Logo";
import { shopNav } from "@/lib/format";

const INFO = [
  { href: "/delivery", label: "Доставка и оплата" },
  { href: "/about", label: "О нас" },
  { href: "/contacts", label: "Контакты" },
];

export function Header() {
  const shop = useShop();
  const { cart } = useCart();
  const { me } = useCustomer();
  const canLogin = shop.customer_login?.telegram || shop.customer_login?.vk;
  // владелец может убрать вход совсем (Настройки → Разделы сайта) — тогда не показываем и кабинет
  const loginOn = shop.customer_login?.enabled !== false;
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);
  return (
    <>
      {shop.demo_notice !== false && (
        <div className="demo-strip">
          Демо-версия: товары и остатки тестовые{shop.payment_test_mode ? ", оплата через симулятор, деньги не списываются" : ""}.
        </div>
      )}
      <header className="header">
        <div className="container header-in">
          <Link href="/" aria-label="На главную">
            <Logo settings={shop} />
          </Link>
          <nav className={`nav ${open ? "open" : ""}`} aria-label="Основное меню">
            {[...shopNav(shop), ...INFO].map((n) => (
              <Link key={n.href} href={n.href} className={path?.startsWith(n.href) ? "on" : ""}>
                {n.label}
              </Link>
            ))}
            <Link href="/track" className={`${path === "/track" ? "on" : ""}`}>
              Мой заказ
            </Link>
          </nav>
          <div className="header-actions">
            {((me && loginOn) || canLogin) && (
              <Link href="/account" className={`btn btn-sm btn-quiet acc-btn ${path === "/account" ? "on" : ""}`} aria-label={me ? "Личный кабинет" : "Войти"} title={me ? `Личный кабинет${me.name ? ": " + me.name : ""}` : undefined}>
                {me ? <span className="acc-dot" aria-hidden>{(me.name || "?").slice(0, 1).toUpperCase()}</span> : null}
                <span className={`hide-mobile acc-name ${me ? "acc-name-me" : ""}`}>{me ? (me.name || "Кабинет").split(" ")[0] : "Войти"}</span>
              </Link>
            )}
            <Link href="/cart" className="btn btn-sm cart-btn" aria-label="Корзина">
              <BagIcon size={16} /> <span className="hide-mobile">Корзина</span>
              {cart && cart.count > 0 && <span className="cart-count">{cart.count}</span>}
            </Link>
            <button className="icon-btn burger" aria-label="Меню" aria-expanded={open} onClick={() => setOpen(!open)}>
              {open ? <XIcon size={16} /> : <MenuIcon />}
            </button>
          </div>
        </div>
      </header>
    </>
  );
}
