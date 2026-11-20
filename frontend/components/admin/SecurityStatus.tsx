"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { adminApi } from "@/lib/admin";

export type SecurityItem = { code: string; level: "critical" | "warning" | "info"; title: string; detail: string; fix: string };
export type SecurityReport = { production: boolean; critical: number; warnings: number; items: SecurityItem[] };

const LEVEL: Record<SecurityItem["level"], string> = { critical: "Важно", warning: "Желательно", info: "Подсказка" };

/** Что ещё нужно настроить перед работой с настоящими покупателями (только владелец). Секреты не показываются. */
export function SecurityStatus() {
  const [r, setR] = useState<SecurityReport | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    adminApi<SecurityReport>("/security/check").then(setR).catch(() => setErr("Не удалось получить проверку безопасности"));
  }, []);
  return (
    <div className="card" data-testid="security-status">
      <div className="row-between" style={{ flexWrap: "wrap", gap: 8 }}>
        <div className="panel-title" style={{ margin: 0 }}>Безопасность</div>
        {r && (
          <span className={`badge ${r.critical ? "red" : r.warnings ? "amber" : "green"}`}>
            {r.critical ? `важных замечаний: ${r.critical}` : r.warnings ? `замечаний: ${r.warnings}` : "всё в порядке"}
          </span>
        )}
      </div>
      {err && <div className="notice red small" style={{ marginTop: 10 }}>{err}</div>}
      {r && (
        <>
          <p className="hint" style={{ margin: "10px 0 12px" }}>
            Режим: <b>{r.production ? "боевой" : "тестовый стенд"}</b>.
          </p>
          {!r.items.length ? (
            <div className="sec-item ok"><span className="msg-dot" aria-hidden /><div><b>Замечаний нет</b><p>Пароли, ключи и режим работы настроены.</p></div></div>
          ) : (
            <div className="sec-list">
              {r.items.map((i) => (
                <div key={i.code} className={`sec-item ${i.level}`}>
                  <span className="msg-dot" aria-hidden />
                  <div>
                    <b>{LEVEL[i.level]}: {i.title}</b>
                    {i.detail && <p>{i.detail}</p>}
                    {i.fix && <p>Как исправить: <code>{i.fix}</code></p>}
                  </div>
                </div>
              ))}
            </div>
          )}
          <p className="hint" style={{ marginTop: 12, marginBottom: 0 }}>
            <Link href="/admin/password" style={{ color: "var(--green)", fontWeight: 600 }}>Сменить свой пароль</Link>
          </p>
        </>
      )}
    </div>
  );
}

/** Плашка на главной админки, если есть важные замечания. */
export function SecurityBanner() {
  const [n, setN] = useState(0);
  useEffect(() => {
    adminApi<SecurityReport>("/security/check").then((r) => setN(r.production ? r.critical : 0)).catch(() => {});
  }, []);
  if (!n) return null;
  return (
    <div className="notice red" style={{ marginBottom: 16 }} role="alert">
      <b>Безопасность: важных замечаний — {n}.</b> Сайт работает в боевом режиме, но часть защиты не настроена.{" "}
      <Link href="/admin/settings?tab=system#security"><b>Посмотреть →</b></Link>
    </div>
  );
}
