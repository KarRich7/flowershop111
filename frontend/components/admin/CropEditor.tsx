"use client";
import { useRef, useState } from "react";
import type { CropBox } from "@/lib/types";

const MIN = 0.08;
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/**
 * Рамка бутона поверх исходной вырезки: перетащите рамку или потяните за уголок.
 * Рамка квадратная в пикселях фото — так бутон на эскизе не растягивается.
 */
export function CropEditor({ src, crop, busy, onSave }: { src: string; crop: CropBox | null; busy?: boolean; onSave: (c: CropBox) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [c, setC] = useState<CropBox>(crop || { x: 0, y: 0, w: 1, h: 1 });
  const drag = useRef<{ mode: "move" | "size"; px: number; py: number; start: CropBox } | null>(null);
  const aspect = nat ? nat.w / nat.h : 1; // ширина / высота фото

  function down(mode: "move" | "size") {
    return (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      drag.current = { mode, px: e.clientX, py: e.clientY, start: c };
    };
  }
  function move(e: React.PointerEvent) {
    const d = drag.current;
    const r = wrap.current?.getBoundingClientRect();
    if (!d || !r) return;
    const dx = (e.clientX - d.px) / r.width;
    const dy = (e.clientY - d.py) / r.height;
    if (d.mode === "move") {
      setC({ ...d.start, x: clamp(d.start.x + dx, 0, 1 - d.start.w), y: clamp(d.start.y + dy, 0, 1 - d.start.h) });
    } else {
      // сторона квадрата в долях ширины; высота в долях = ширина * aspect
      const grow = Math.max(dx, dy / aspect);
      let w = clamp(d.start.w + grow, MIN, 1 - d.start.x);
      let h = w * aspect;
      if (d.start.y + h > 1) {
        h = 1 - d.start.y;
        w = h / aspect;
      }
      setC({ ...d.start, w: Math.max(w, MIN), h: Math.max(h, MIN * aspect) });
    }
  }
  function up() {
    drag.current = null;
  }
  function whole() {
    setC({ x: 0, y: 0, w: 1, h: 1 });
  }
  function centerSquare() {
    const w = aspect >= 1 ? 1 / aspect : 1;
    const h = w * aspect;
    setC({ x: (1 - w) / 2, y: (1 - h) / 2, w, h });
  }
  const changed = JSON.stringify(round(c)) !== JSON.stringify(round(crop || { x: 0, y: 0, w: 1, h: 1 }));

  return (
    <div className="crop-editor">
      <div className="crop-stage" ref={wrap} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="Исходная вырезка" draggable={false} onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
        <div
          className="crop-frame"
          style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%`, width: `${c.w * 100}%`, height: `${c.h * 100}%` }}
          onPointerDown={down("move")}
          role="slider"
          aria-label="Рамка бутона: перетащите"
          aria-valuenow={Math.round(c.w * 100)}
        >
          <span className="crop-handle" onPointerDown={down("size")} aria-label="Изменить размер рамки" />
        </div>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn btn-sm" disabled={busy || !changed} onClick={() => onSave(round(c))}>{busy ? "Сохраняем…" : "Сохранить кадр"}</button>
        <button type="button" className="btn btn-quiet btn-sm" onClick={centerSquare}>По центру</button>
        <button type="button" className="btn btn-quiet btn-sm" onClick={whole}>Весь цветок</button>
      </div>
      <span className="hint">Перетащите рамку на бутон, уголок справа внизу меняет размер. В конструктор попадёт то, что внутри рамки</span>
    </div>
  );
}

function round(c: CropBox): CropBox {
  const r = (v: number) => Math.round(v * 10000) / 10000;
  return { x: r(c.x), y: r(c.y), w: r(c.w), h: r(c.h) };
}
