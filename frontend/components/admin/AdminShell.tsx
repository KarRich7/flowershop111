"use client";
import { MenuIcon } from "@/components/Icons";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { adminApi, forgetLegacyToken, type Role, type StaffUser } from "@/lib/admin";
import { request } from "@/lib/api";
import type { ShopSettings } from "@/lib/types";
import { Logo } from "../Logo";
import { ToastProvider } from "../Toast";
import { ExternalIcon } from "@/components/Icons";

const UserCtx = createContext<StaffUser | null>(null);
export const useStaff = () => useContext(UserCtx) as StaffUser;
const UpdateCtx = createContext<(u: Partial<StaffUser>) => void>(() => {});
/** Обновить данные текущего сотрудника в шапке (например, после начала смены). */
export const useStaffUpdate = () => useContext(UpdateCtx);

type NavItem = { href: string; label: string; roles: Role[] } | { sep: string; roles: Role[] };
const ALL: Role[] = ["owner", "florist", "courier"];
const FO: Role[] = ["owner", "florist"];
const O: Role[] = ["owner"];
const NAV: NavItem[] = [
  { href: "/admin", label: "Сводка", roles: ALL },
  { sep: "Продажи", roles: ALL },
  { href: "/admin/orders", label: "Заказы", roles: ALL },
  { href: "/admin/deliveries", label: "Доставки", roles: ALL },
  { href: "/admin/store-sale", label: "Продажа в магазине", roles: FO },
  { sep: "Каталог и склад", roles: FO },
  { href: "/admin/products", label: "Товары", roles: FO },
  { href: "/admin/inventory", label: "Склад", roles: FO },
  { href: "/admin/recipes", label: "Сборка букетов", roles: FO },
  { sep: "Магазин", roles: FO },
  { href: "/admin/customers", label: "Клиенты", roles: FO },
  { href: "/admin/staff", label: "Сотрудники", roles: O },
  { href: "/admin/settings", label: "Настройки", roles: O },
  { href: "/admin/about", label: "Страница «О нас»", roles: O },
  { href: "/admin/faq", label: "Частые вопросы", roles: O },
];
/** Страницы без своего пункта меню подсвечивают «родителя» */
const PARENT: Record<string, string> = { "/admin/categories": "/admin/products", "/admin/audit": "/admin/settings" };

/** Подписи столбцов для таблиц-карточек на телефоне: копируем заголовки <th> в data-label ячеек. */
function useTableLabels(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const root = document.querySelector(".adm-main");
    if (!root) return;
    let raf = 0;
    const apply = () => {
      raf = 0;
      root.querySelectorAll<HTMLTableElement>("table.t").forEach((t) => {
        const heads = Array.from(t.querySelectorAll(":scope > thead th")).map((th) => (th.textContent || "").trim());
        if (!heads.length) return;
        t.querySelectorAll(":scope > tbody > tr").forEach((tr) => {
          let i = 0;
          Array.from(tr.children).forEach((cell) => {
            const el = cell as HTMLTableCellElement;
            if (!el.hasAttribute("data-label") || el.dataset.auto === "1") {
              const label = el.colSpan > 1 ? "" : heads[i] || "";
              if (el.getAttribute("data-label") !== label) el.setAttribute("data-label", label);
              el.dataset.auto = "1";
            }
            i += el.colSpan || 1;
          });
        });
      });
    };
    apply();
    const mo = new MutationObserver(() => {
      if (!raf) raf = requestAnimationFrame(apply);
    });
    mo.observe(root, { childList: true, subtree: true, characterData: true });
    return () => {
      mo.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [active]);
}

export function AdminShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "";
  const router = useRouter();
  const [user, setUser] = useState<StaffUser | null>(null);
  const [shop, setShop] = useState<ShopSettings | null>(null);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [shiftBusy, setShiftBusy] = useState(false);
  const updateUser = (u: Partial<StaffUser>) => setUser((x) => (x ? { ...x, ...u } : x));
  const isLogin = path.startsWith("/admin/login");
  useTableLabels(!!user && !isLogin);

  useEffect(() => {
    setSearch(window.location.search);
    setOpen(false);
  }, [path]);

  useEffect(() => {
    if (isLogin) return;
    // вход хранится в HttpOnly-cookie; без входа /auth/me вернёт 401 и adminApi откроет страницу входа
    adminApi<StaffUser>("/auth/me").then(setUser).catch(() => {});
    request<ShopSettings>("/settings/public").then(setShop).catch(() => {});
  }, [isLogin, router]);

  if (isLogin) return <ToastProvider>{children}</ToastProvider>;
  if (!user) return <div style={{ padding: 40 }}><div className="skeleton" style={{ height: 300 }} /></div>;

  const items = NAV.filter((n) => n.roles.includes(user.role));
  const isOn = (href: string) => {
    const [p, q] = href.split("?");
    if (q) return path === p && search.includes(q);
    if (p === "/admin") return path === "/admin";
    const parent = Object.entries(PARENT).find(([child]) => path.startsWith(child));
    if (parent) return parent[1] === p;
    return path.startsWith(p);
  };

  async function toggleShift() {
    if (!user) return;
    setShiftBusy(true);
    try {
      updateUser(await adminApi<StaffUser>("/me/notify", { method: "PATCH", body: { on_shift: !user.on_shift } }));
    } catch {}
    setShiftBusy(false);
  }

  async function logout() {
    try {
      await adminApi("/auth/logout", { method: "POST" });
    } catch {}
    forgetLegacyToken();
    router.replace("/admin/login");
  }

  return (
    <ToastProvider>
      <UserCtx.Provider value={user}>
      <UpdateCtx.Provider value={updateUser}>
        <div className="adm-mobile-bar">
          <button className="icon-btn" onClick={() => setOpen(!open)} aria-label="Меню" aria-expanded={open}><MenuIcon /></button>
          <Logo settings={shop || { shop_name: "Цветы Урала", tagline: "", logo: null }} compact />
          <span className="badge lilac">{user.role_label}</span>
        </div>
        <div className="adm">
          <aside className={`adm-side ${open ? "open" : ""}`}>
            <Link href="/admin">
              <Logo settings={shop || { shop_name: "Цветы Урала", tagline: "Админ-панель", logo: null }} />
            </Link>
            <nav className="adm-nav">
              {items.map((n, i) =>
                "sep" in n ? (
                  <div className="sep" key={i}>{n.sep}</div>
                ) : (
                  <Link key={n.href} href={n.href} className={isOn(n.href) ? "on" : ""} onClick={() => setSearch(n.href.includes("?") ? `?${n.href.split("?")[1]}` : "")}>
                    {n.label}
                  </Link>
                ),
              )}
            </nav>
            <div className="adm-user" style={{ marginTop: 20 }}>
              <b>{user.name}</b>
              <div className="muted">{user.role_label}</div>
              {user.notify_mode === "shift" && (
                <button className={`btn btn-xs ${user.on_shift ? "" : "btn-ghost"}`} style={{ marginTop: 8 }} disabled={shiftBusy} onClick={toggleShift}
                  title={user.on_shift ? "Уведомления о заказах приходят вам в мессенджер" : "Начните смену, чтобы получать уведомления о заказах"}>
                  {user.on_shift ? "🟢 На смене — закончить" : "▶ Начать смену"}
                </button>
              )}
              <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                <Link href="/" className="btn btn-xs btn-ghost" target="_blank">Сайт <ExternalIcon /></Link>
                <Link href="/admin/notify" className={`btn btn-xs btn-ghost ${path.startsWith("/admin/notify") ? "on" : ""}`}>Уведомления</Link>
                <Link href="/admin/password" className={`btn btn-xs btn-ghost ${path.startsWith("/admin/password") ? "on" : ""}`}>Сменить пароль</Link>
                <button className="btn btn-xs btn-ghost" onClick={logout}>Выйти</button>
              </div>
            </div>
          </aside>
          {open && <div className="adm-backdrop" onClick={() => setOpen(false)} aria-hidden />}
          <main className="adm-main" onClick={() => open && setOpen(false)}>
            {user.weak_password && !path.startsWith("/admin/password") && (
              <div className="notice red adm-weak" role="alert">
                <b>Небезопасный пароль.</b> Вы входите с демо-паролем, который знают посторонние.{" "}
                <Link href="/admin/password?weak=1"><b>Сменить пароль →</b></Link>
              </div>
            )}
            {children}
          </main>
        </div>
      </UpdateCtx.Provider>
      </UserCtx.Provider>
    </ToastProvider>
  );
}
