"use client";
import { XIcon } from "@/components/Icons";
import type { ReactNode } from "react";
import { STATUS_TONE } from "@/lib/format";

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return <span className={`badge ${STATUS_TONE[status] || "gray"}`}>{label}</span>;
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Закрыть"><XIcon /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function PageTop({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="adm-top">
      <h1>{title}</h1>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export function Loading() {
  return <div className="skeleton" style={{ height: 220 }} />;
}

export function ErrorBox({ text }: { text: string }) {
  return text ? <div className="notice red">{text}</div> : null;
}
