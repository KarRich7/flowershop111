"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Logo } from "@/components/Logo";
import { ApiError, request } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      // сервер ставит HttpOnly-cookie входа; токен в ответе не приходит и в браузере не хранится
      const r = await request<{ user?: { weak_password?: boolean } }>("/admin/auth/login", {
        body: { username: username.trim(), password },
      });
      router.replace(r.user?.weak_password ? "/admin/password?weak=1" : "/admin");
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Ошибка входа");
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card stack" onSubmit={submit}>
        <Logo settings={{ shop_name: "Цветы Урала", tagline: "Цветочный магазин", logo: null }} />
        <h2 style={{ marginTop: 10 }}>Вход для сотрудников</h2>
        <label className="field">
          <span>Логин</span>
          <input className="input" name="username" autoComplete="username" autoCapitalize="none" autoCorrect="off"
            spellCheck={false} maxLength={150} required value={username} onChange={(e) => setU(e.target.value)} />
        </label>
        <div className="field">
          <label htmlFor="login-password" className="label">Пароль</label>
          <div className="pw-wrap">
            <input id="login-password" className="input" name="password" type={show ? "text" : "password"} autoComplete="current-password"
              maxLength={128} required value={password} onChange={(e) => setP(e.target.value)} />
            <button type="button" className="pw-toggle" onClick={() => setShow(!show)} aria-label={show ? "Скрыть пароль" : "Показать пароль"}>
              {show ? "Скрыть" : "Показать"}
            </button>
          </div>
        </div>
        {err && <div className="notice red small" role="alert">{err}</div>}
        <button className="btn btn-lg" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
        <div className="tiny muted">
          Логины и пароли выдаёт владелец магазина (Админка → «Сотрудники»). Забыли пароль — попросите владельца задать новый.
          После 5 неверных попыток вход блокируется на 15 минут.
        </div>
      </form>
    </div>
  );
}
