"use client";
import { useState } from "react";
import { useToast } from "@/components/Toast";
import type { MessengerLinks } from "@/lib/admin";

/** Кнопка «Получить ссылки» → ссылки t.me / vk.me для привязки мессенджера сотрудника (открыть или скопировать). */
export function MessengerLinkBox({ load, forSelf }: { load: () => Promise<MessengerLinks>; forSelf: boolean }) {
  const toast = useToast();
  const [links, setLinks] = useState<MessengerLinks | null>(null);
  const [busy, setBusy] = useState(false);
  async function get() {
    setBusy(true);
    try {
      setLinks(await load());
    } catch {
      toast("Не удалось получить ссылки", "err");
    }
    setBusy(false);
  }
  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast("Ссылка скопирована", "ok");
    } catch {
      window.prompt("Скопируйте ссылку:", url);
    }
  }
  if (!links) {
    return <button className="btn btn-sm btn-ghost" disabled={busy} onClick={get}>{forSelf ? "Привязать Telegram или ВК" : "Ссылки для привязки Telegram / ВК"}</button>;
  }
  const rows: [string, string, string][] = [["Telegram", links.telegram_url, links.telegram_hint], ["ВКонтакте", links.vk_url, links.vk_hint]];
  return (
    <div className="notice small">
      <div style={{ marginBottom: 6 }}>
        {forSelf
          ? "Откройте ссылку на телефоне, где установлен мессенджер, и нажмите «Запустить» / «Начать». Ссылка одноразовая, действует 24 часа."
          : "Отправьте ссылку сотруднику (лично, не в общий чат). Он откроет её на телефоне и нажмёт «Запустить» / «Начать». Ссылка одноразовая, действует 24 часа."}
      </div>
      {rows.map(([name, url, hint]) => (
        <div key={name} className="row" style={{ gap: 8, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
          <b style={{ minWidth: 90 }}>{name}</b>
          {url ? (
            <>
              <a className="btn btn-xs" href={url} target="_blank" rel="noopener noreferrer">Открыть</a>
              <button className="btn btn-xs btn-ghost" onClick={() => copy(url)}>Скопировать</button>
            </>
          ) : <span className="muted">{hint}</span>}
        </div>
      ))}
      {(links.telegram_url || links.vk_url) && (
        <div className="tiny muted" style={{ marginTop: 8 }}>
          Если ссылка не сработала, отправьте боту сообщение <code style={{ userSelect: "all" }}>{links.code_message}</code>{" "}
          <button className="btn btn-xs btn-ghost" onClick={() => copy(links.code_message)}>Скопировать</button>
        </div>
      )}
    </div>
  );
}
