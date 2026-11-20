"use client";
// Вход через Telegram / ВКонтакте: сайт выдаёт ссылку на нашего бота, покупатель подтверждает вход в чате,
// сайт дожидается подтверждения и получает сессию. Заодно бот получает право писать покупателю —
// уведомления о заказах приходят в выбранный мессенджер.
import { useEffect, useRef, useState } from "react";
import { useCustomer } from "@/components/CustomerProvider";
import { useShop } from "@/components/ShopProvider";
import { ApiError, request } from "@/lib/api";
import type { CustomerProfile, LoginStart, LoginStatus, Messenger } from "@/lib/types";

const LABEL: Record<Messenger, string> = { telegram: "Telegram", vk: "ВКонтакте" };

export function TelegramIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <path fill="currentColor" d="M21.4 4.2 2.9 11.3c-1.3.5-1.2 1.2-.2 1.5l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.4l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.4-1.5zM9.6 14.4l8.4-7.6c.4-.3-.1-.5-.6-.2L7.9 13.4" />
    </svg>
  );
}
export function VkIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <path fill="currentColor" d="M12.8 17.5C6.9 17.5 3.5 13.5 3.4 6.8h3c.1 4.9 2.3 7 4 7.4V6.8h2.8V11c1.7-.2 3.5-2.1 4.1-4.2h2.8c-.5 2.6-2.4 4.5-3.8 5.3 1.4.6 3.6 2.3 4.4 5.4h-3.1c-.7-2-2.3-3.6-4.4-3.8v3.8h-.4z" />
    </svg>
  );
}

type Wait = LoginStart & { deadline: number; opened: boolean };

export function MessengerLogin({
  orderToken,
  onSignedIn,
  compact = false,
}: {
  orderToken?: string;
  onSignedIn?: (p: CustomerProfile | null) => void;
  compact?: boolean;
}) {
  const shop = useShop();
  const { signIn } = useCustomer();
  const avail = shop.customer_login || { telegram: false, vk: false, test_mode: false };
  const [wait, setWait] = useState<Wait | null>(null);
  const [busy, setBusy] = useState<Messenger | null>(null);
  const [msg, setMsg] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const done = useRef(false);

  // опрос статуса, пока покупатель подтверждает вход в мессенджере
  useEffect(() => {
    if (!wait) return;
    done.current = false;
    let stop = false;
    const check = async () => {
      if (stop || done.current) return;
      setNow(Date.now());
      try {
        // секретный токен запроса входа браузер передаёт сам в HttpOnly-cookie
        const st = await request<LoginStatus>("/account/login/status", { method: "POST", body: {} });
        if (stop || done.current) return;
        if (st.status === "confirmed") {
          done.current = true;
          const p = await signIn();
          setWait(null);
          onSignedIn?.(p);
        } else if (st.status === "pending") {
          if (st.opened) setWait((w) => (w && !w.opened ? { ...w, opened: true } : w));
        } else {
          done.current = true;
          setWait(null);
          setMsg(st.status === "cancelled" ? "Вход отменён в мессенджере." : "Время на подтверждение истекло. Попробуйте ещё раз.");
        }
      } catch {}
    };
    const t = window.setInterval(check, 2000);
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const onVis = () => document.visibilityState === "visible" && check();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop = true;
      clearInterval(t);
      clearInterval(tick);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [wait?.deadline]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!avail.telegram && !avail.vk) return null;

  async function start(ch: Messenger) {
    setMsg("");
    setBusy(ch);
    try {
      const st = await request<LoginStart>("/account/login/start", { body: { channel: ch, order_token: orderToken || undefined } });
      setWait({ ...st, deadline: Date.now() + st.expires_in * 1000, opened: false });
      if (st.link) window.open(st.link, "_blank", "noopener");
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Не удалось начать вход");
    } finally {
      setBusy(null);
    }
  }

  async function testConfirm() {
    if (!wait) return;
    try {
      await request("/account/login/test-confirm", { body: {} });
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Не удалось подтвердить");
    }
  }

  if (wait) {
    const left = Math.max(0, Math.round((wait.deadline - now) / 1000));
    const name = LABEL[wait.channel];
    return (
      <div className="msgr-wait" role="status" aria-live="polite">
        <div className="msgr-wait-head">
          <span className="spinner" aria-hidden />
          <b>{wait.opened ? `Подтвердите вход в ${name}` : `Откройте ${name} и нажмите «${orderToken ? "Подключить" : "Войти на сайт"}»`}</b>
        </div>
        <div className="row msgr-wait-actions">
          {wait.link && (
            <a className={`btn btn-sm ${wait.channel === "telegram" ? "btn-tg" : "btn-vk"}`} href={wait.link} target="_blank" rel="noopener noreferrer">
              {wait.channel === "telegram" ? <TelegramIcon size={16} /> : <VkIcon size={16} />} Открыть {name}
            </a>
          )}
          {wait.test_mode && (
            <button type="button" className="btn btn-sm btn-outline" onClick={testConfirm}>
              Подтвердить вход (тестовый режим)
            </button>
          )}
          <button type="button" className="btn btn-sm btn-quiet" onClick={() => { done.current = true; setWait(null); }}>
            Отмена
          </button>
        </div>
        <p className="tiny muted">
          Если кнопка не сработала, отправьте боту код <b className="num msgr-code">{wait.code.slice(0, 3)} {wait.code.slice(3)}</b>. Действует ещё{" "}
          <span className="num">{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span>
        </p>
      </div>
    );
  }

  return (
    <div className={`msgr ${compact ? "compact" : ""}`}>
      <div className="row msgr-btns">
        {avail.telegram && (
          <button type="button" className="btn btn-tg" onClick={() => start("telegram")} disabled={!!busy}>
            <TelegramIcon /> {busy === "telegram" ? "Открываем…" : "Войти через Telegram"}
          </button>
        )}
        {avail.vk && (
          <button type="button" className="btn btn-vk" onClick={() => start("vk")} disabled={!!busy}>
            <VkIcon /> {busy === "vk" ? "Открываем…" : "Войти через ВКонтакте"}
          </button>
        )}
      </div>
      {msg && <p className="field-err" role="alert">{msg}</p>}
    </div>
  );
}
