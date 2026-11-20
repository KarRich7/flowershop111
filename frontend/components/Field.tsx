import type { ReactNode } from "react";

/** Поле формы с подписью, подсказкой и текстом ошибки под ним */
export function Field({ label, error, hint, full, children, className = "" }: {
  label: ReactNode; error?: string | null; hint?: ReactNode; full?: boolean; children: ReactNode; className?: string;
}) {
  return (
    <label className={`field ${full ? "full" : ""} ${error ? "has-err" : ""} ${className}`}>
      <span>{label}</span>
      {children}
      {error ? <span className="field-err" role="alert">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </label>
  );
}

/** Выбор цвета: пипетка + HEX-код вручную */
export function ColorInput({ value, onChange, invalid, label = "Цвет" }: { value: string; onChange: (v: string) => void; invalid?: boolean; label?: string }) {
  const safe = /^#[0-9A-Fa-f]{6}$/.test(value) ? value : "#cccccc";
  return (
    <div className="color-input">
      <input type="color" value={safe.toLowerCase()} onChange={(e) => onChange(e.target.value.toUpperCase())} aria-label={`${label}: палитра`} />
      <input className={`input ${invalid ? "invalid" : ""}`} value={value} maxLength={7} placeholder="#RRGGBB" onChange={(e) => onChange(e.target.value.trim())} aria-label={`${label}: код`} />
    </div>
  );
}
