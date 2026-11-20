"use client";
import { useStaff, useStaffUpdate } from "@/components/admin/AdminShell";
import { MessengerLinkBox } from "@/components/admin/MessengerLinks";
import { ErrorBox, Loading, PageTop } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, NOTIFY_MODES, useAdmin, type MessengerLinks, type NotifyMode, type StaffUser } from "@/lib/admin";
import * as V from "@/lib/validate";
import { useState } from "react";

type MyNotify = StaffUser & { on_shift_now: string[]; shift_max_hours: number };

const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "");

export default function NotifyPage() {
  const me = useStaff();
  const update = useStaffUpdate();
  const toast = useToast();
  const { data, error, reload } = useAdmin<MyNotify>("/me/notify");
  const [busy, setBusy] = useState(false);
  async function patch(body: Record<string, unknown>, ok: string) {
    setBusy(true);
    try {
      update(await adminApi<StaffUser>("/me/notify", { method: "PATCH", body }));
      toast(ok, "ok");
      reload();
    } catch (x) {
      toast(V.serverError(x), "err");
    }
    setBusy(false);
  }
  if (error) return <ErrorBox text={error} />;
  if (!data) return <Loading />;
  const linked = data.telegram_linked || data.vk_linked;
  const others = data.on_shift_now.filter((n) => n !== me.name);
  return (
    <>
      <PageTop title="Уведомления о заказах" />
      <div className="notice small" style={{ marginBottom: 14 }}>
        Бот магазина присылает сотрудникам сообщения о <b>новых заказах</b> и <b>вопросах покупателей</b> — в Telegram или ВКонтакте.
        Флористам — только пока они на смене. Если на смене никого нет, сообщение получит владелец.
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Смена</h3>
        <p style={{ margin: "4px 0 10px" }}>
          {data.on_shift ? <>🟢 Вы на смене с <b>{time(data.shift_started_at)}</b>.</> : <>⚪ Вы сейчас не на смене.</>}{" "}
          {others.length ? <>Также на смене: {others.join(", ")}.</> : <span className="muted">Больше никого на смене нет.</span>}
        </p>
        <button className={`btn ${data.on_shift ? "btn-ghost" : ""}`} disabled={busy} onClick={() => patch({ on_shift: !data.on_shift }, data.on_shift ? "Смена закончена" : "Смена начата")}>
          {data.on_shift ? "⏹ Закончить смену" : "▶ Начать смену"}
        </button>
        <div className="tiny muted" style={{ marginTop: 8 }}>
          Смену можно начать и закончить и в боте: команда /smena в Telegram или слово «смена» в ВК. Забытая смена закроется сама через {data.shift_max_hours} ч.
        </div>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 14 }}>
        <h3 style={{ marginTop: 0 }}>Когда присылать</h3>
        <select className="select" value={data.notify_mode} disabled={busy} onChange={(e) => patch({ notify_mode: e.target.value as NotifyMode }, "Сохранено")}>
          {NOTIFY_MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>

      <div className="card" style={{ padding: 16 }}>
        <h3 style={{ marginTop: 0 }}>Куда присылать</h3>
        {([["telegram", "Telegram", data.telegram_linked], ["vk", "ВКонтакте", data.vk_linked]] as const).map(([key, name, on]) => (
          <div key={key} className="row" style={{ gap: 10, alignItems: "center", marginBottom: 8 }}>
            <b style={{ minWidth: 90 }}>{name}</b>
            {on ? <span className="badge green">привязан</span> : <span className="badge gray">не привязан</span>}
            {on && <button className="btn btn-xs btn-ghost" disabled={busy} onClick={() => patch({ unlink: key }, `${name} отвязан`)}>Отвязать</button>}
          </div>
        ))}
        {!linked && <div className="small" style={{ margin: "6px 0 10px" }}>Привяжите хотя бы один мессенджер — иначе уведомления не придут.</div>}
        <MessengerLinkBox forSelf load={() => adminApi<MessengerLinks>("/me/notify/link", { method: "POST" })} />
        <div className="tiny muted" style={{ marginTop: 8 }}>После привязки обновите страницу. Если привязаны оба, сообщения идут в Telegram, а в ВК — только когда Telegram недоступен.</div>
      </div>
    </>
  );
}
