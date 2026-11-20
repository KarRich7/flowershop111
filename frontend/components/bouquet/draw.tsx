// Отрисовка букета в коде (SVG): головки цветов по видам, зелень, упаковка, лента и бумажная бирка-открытка.
// Используется в конструкторе (интерактивно), в корзине и в карточке заказа (эскиз для флориста).
import { useId, type ReactElement } from "react";
import { ribbonBox, ribbonKey, type RibbonSpec } from "./ribbon3d";
import { VaseBack, VaseFront, VaseGround, VaseWater, vaseGeom, vaseStems, type VaseIds, type VaseShape } from "./vase";
export { VASES, type VaseShape } from "./vase";

export type Kind =
  | "rose" | "peonyRose" | "sprayRose" | "tulip" | "peony" | "hydrangea" | "eustoma"
  | "chrysanthemum" | "alstroemeria" | "gerbera" | "ranunculus" | "lily"
  | "eucalyptus" | "pistachio" | "ruscus" | "gypsophila" | "leaf";

export type CatalogItem = { id: number; name: string; species: string; color_hex: string; type: string; constructor_image?: string | null };
/** Стебель на эскизе. m — место выбрал покупатель (перетащил сам): авто-раскладка его не двигает */
export type Inst = { uid: number; item_id: number; u: number; v: number; r: number; f?: boolean; m?: boolean };

export const VIEW_W = 400;
export const VIEW_H = 460;

// ------------------------------------------------------------------ цвет
export function shade(hex: string, k: number) {
  const h = (hex || "#d9a7b0").replace("#", "");
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  const ch = (s: number) => Math.max(0, Math.min(255, Math.round(((n >> s) & 255) * k)));
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}
function lum(hex: string) {
  const h = (hex || "#888888").replace("#", "");
  const n = parseInt(h.length === 6 ? h : "888888", 16);
  return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
}
/** Обводка: светлые цветы получают тёплую серую обводку, иначе — затемнённый тон */
function edge(c: string) {
  return lum(c) > 0.85 ? "rgb(168,156,138)" : shade(c, 0.72);
}

// ------------------------------------------------------------------ вид цветка по товару
export function kindOf(p: Pick<CatalogItem, "species" | "name" | "type"> | undefined): Kind {
  if (!p) return "rose";
  const s = `${p.species} ${p.name}`.toLowerCase();
  if (p.type === "greenery") {
    if (s.includes("эвкалипт")) return "eucalyptus";
    if (s.includes("фисташ") || s.includes("писташ")) return "pistachio";
    if (s.includes("рускус")) return "ruscus";
    if (s.includes("гипсофил")) return "gypsophila";
    return "leaf";
  }
  if (s.includes("пионовид")) return "peonyRose";
  if (s.includes("кустов") && s.includes("роз")) return "sprayRose";
  if (s.includes("роз")) return "rose";
  if (s.includes("тюльпан")) return "tulip";
  if (s.includes("пион")) return "peony";
  if (s.includes("гортенз")) return "hydrangea";
  if (s.includes("эустом")) return "eustoma";
  if (s.includes("хризант")) return "chrysanthemum";
  if (s.includes("альстром")) return "alstroemeria";
  if (s.includes("гербер")) return "gerbera";
  if (s.includes("ранунк")) return "ranunculus";
  if (s.includes("лили")) return "lily";
  return "rose";
}

export const isGreen = (k: Kind) => ["eucalyptus", "pistachio", "ruscus", "gypsophila", "leaf"].includes(k);

/** Базовый радиус головки (при масштабе 1) — от него зависит, сколько места занимает цветок */
export const BASE_R: Record<Kind, number> = {
  rose: 20, peonyRose: 24, sprayRose: 22, tulip: 17, peony: 27, hydrangea: 31, eustoma: 19, chrysanthemum: 22,
  alstroemeria: 21, gerbera: 22, ranunculus: 18, lily: 25, eucalyptus: 34, pistachio: 34, ruscus: 34, gypsophila: 30, leaf: 30,
};

/** Чем больше цветов, тем мельче каждая головка — букет остаётся в пределах упаковки */
export function headScale(n: number) {
  // головки заполняют ~60% раскрытия упаковки: 10 роз — плотный букет, 101 — мелкие головки
  // до 30 цветков (лимит конструктора) головки соприкасаются и чуть перекрываются — «шапка» без просветов
  return Math.max(0.45, Math.min(1.9, 5.3 / Math.sqrt(Math.max(n, 1))));
}
/** Радиус «шапки» букета (доля от раскрытия упаковки): несколько цветков стоят кучно в центре */
export function spread(n: number) {
  const R = 20 * headScale(n);
  return Math.max(0.3, Math.min(0.9, Math.sqrt((Math.max(n, 1) * Math.PI * R * R) / (0.62 * 47000))));
}

// ------------------------------------------------------------------ примитивы
function scallop(r: number, n: number, depth: number, rot = 0) {
  let d = "";
  for (let i = 0; i <= n; i++) {
    const a = rot + (i / n) * Math.PI * 2;
    const x = Math.cos(a) * r * (1 - depth * 0.35);
    const y = Math.sin(a) * r * (1 - depth * 0.35);
    if (i === 0) d += `M${x.toFixed(2)} ${y.toFixed(2)}`;
    else {
      const m = rot + ((i - 0.5) / n) * Math.PI * 2;
      d += ` Q${(Math.cos(m) * r * (1 + depth)).toFixed(2)} ${(Math.sin(m) * r * (1 + depth)).toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)}`;
    }
  }
  return d + "Z";
}
const arc = (x1: number, y1: number, r: number, x2: number, y2: number) => `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`;

function Rose({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      <path d={scallop(R, 6, 0.12, 0.4)} fill={c} stroke={e} strokeWidth={0.9} />
      <path
        d={[arc(-0.72 * R, 0.18 * R, 0.74 * R, 0.56 * R, -0.46 * R), arc(0.64 * R, 0.24 * R, 0.64 * R, -0.36 * R, 0.58 * R),
          arc(-0.4 * R, -0.1 * R, 0.42 * R, 0.32 * R, 0.06 * R), arc(0.12 * R, 0.32 * R, 0.26 * R, -0.16 * R, -0.18 * R)].join(" ")}
        fill="none" stroke={e} strokeWidth={1.1} strokeLinecap="round" opacity={0.75}
      />
      <circle r={0.16 * R} fill={shade(c, 0.88)} />
    </g>
  );
}
function PeonyRose({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      <path d={scallop(R, 9, 0.14)} fill={c} stroke={e} strokeWidth={0.9} />
      <path d={scallop(R * 0.74, 7, 0.16, 0.3)} fill={shade(c, 0.97)} stroke={e} strokeWidth={0.8} />
      <path d={scallop(R * 0.48, 6, 0.18, 0.7)} fill={shade(c, 0.94)} stroke={e} strokeWidth={0.8} />
      <path d={arc(-0.22 * R, 0.08 * R, 0.24 * R, 0.2 * R, -0.04 * R)} fill="none" stroke={e} strokeWidth={1} />
    </g>
  );
}
function SprayRose({ R, c }: { R: number; c: string }) {
  return (
    <g>
      {([[-0.5, -0.18, 0.5], [0.46, -0.34, 0.46], [0.06, 0.46, 0.52]] as const).map(([x, y, k], i) => (
        <g key={i} transform={`translate(${x * R} ${y * R})`}><Rose R={R * k} c={c} /></g>
      ))}
      <ellipse cx={0.62 * R} cy={0.42 * R} rx={0.14 * R} ry={0.2 * R} fill={shade(c, 0.9)} stroke={edge(c)} strokeWidth={0.7} />
    </g>
  );
}
function Tulip({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      <path
        d={`M${-0.62 * R} ${-0.2 * R} C${-0.66 * R} ${0.78 * R} ${0.66 * R} ${0.78 * R} ${0.62 * R} ${-0.2 * R}
            L${0.42 * R} ${-0.86 * R} L${0.16 * R} ${-0.36 * R} L${-0.04 * R} ${-0.96 * R} L${-0.22 * R} ${-0.36 * R} L${-0.46 * R} ${-0.86 * R} Z`}
        fill={c} stroke={e} strokeWidth={0.9} strokeLinejoin="round"
      />
      <path d={`M${-0.04 * R} ${-0.5 * R} C${-0.14 * R} ${0.1 * R} ${-0.1 * R} ${0.4 * R} ${0} ${0.52 * R}`} fill="none" stroke={e} strokeWidth={0.9} opacity={0.7} />
      <path d={`M${0.3 * R} ${-0.4 * R} C${0.24 * R} ${0.1 * R} ${0.3 * R} ${0.3 * R} ${0.36 * R} ${0.42 * R}`} fill="none" stroke={e} strokeWidth={0.8} opacity={0.55} />
    </g>
  );
}
function Peony({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      <path d={scallop(R, 13, 0.16)} fill={shade(c, 0.97)} stroke={e} strokeWidth={0.9} />
      <path d={scallop(R * 0.78, 11, 0.18, 0.2)} fill={c} stroke={e} strokeWidth={0.8} />
      <path d={scallop(R * 0.56, 9, 0.2, 0.5)} fill={shade(c, 1.03)} stroke={e} strokeWidth={0.8} />
      <path d={scallop(R * 0.32, 7, 0.24, 0.1)} fill={shade(c, 0.95)} stroke={e} strokeWidth={0.7} />
    </g>
  );
}
function Hydrangea({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  const pts: [number, number, number][] = [];
  for (let ring = 0; ring < 4; ring++) {
    const n = ring === 0 ? 1 : ring * 6;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + ring * 0.4;
      pts.push([Math.cos(a) * ring * 0.27 * R, Math.sin(a) * ring * 0.27 * R, (i + ring) % 3]);
    }
  }
  return (
    <g>
      <circle r={R * 0.98} fill={shade(c, 0.9)} />
      {pts.map(([x, y, t], i) => {
        const col = shade(c, [1, 0.94, 1.05][t]);
        const f = R * 0.12;
        return (
          <g key={i} transform={`translate(${x} ${y}) rotate(${(i * 37) % 90})`}>
            <circle cx={f} cy={0} r={f} fill={col} stroke={e} strokeWidth={0.45} />
            <circle cx={-f} cy={0} r={f} fill={col} stroke={e} strokeWidth={0.45} />
            <circle cx={0} cy={f} r={f} fill={col} stroke={e} strokeWidth={0.45} />
            <circle cx={0} cy={-f} r={f} fill={col} stroke={e} strokeWidth={0.45} />
            <circle r={f * 0.4} fill={shade(c, 0.7)} />
          </g>
        );
      })}
    </g>
  );
}
function Eustoma({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      <path d={scallop(R, 5, 0.2, 0.2)} fill={c} stroke={e} strokeWidth={0.9} />
      <path d={`${arc(-0.6 * R, 0.1 * R, 0.62 * R, 0.5 * R, -0.3 * R)} ${arc(0.4 * R, 0.3 * R, 0.4 * R, -0.24 * R, 0.24 * R)}`} fill="none" stroke={e} strokeWidth={1} opacity={0.7} />
      <circle r={0.14 * R} fill="#b9c46a" opacity={0.8} />
      <ellipse cx={0.95 * R} cy={-0.55 * R} rx={0.2 * R} ry={0.34 * R} transform={`rotate(30 ${0.95 * R} ${-0.55 * R})`} fill={shade(c, 0.92)} stroke={e} strokeWidth={0.7} />
    </g>
  );
}
function Daisy({ R, c, petals, center, ring }: { R: number; c: string; petals: number; center: string; ring?: string }) {
  const e = edge(c);
  return (
    <g>
      {Array.from({ length: petals }, (_, i) => (
        <ellipse key={i} cx={0} cy={-0.56 * R} rx={(0.6 / petals) * 6 * 0.34 * R} ry={0.46 * R} fill={c} stroke={e} strokeWidth={0.6}
          transform={`rotate(${(i * 360) / petals})`} />
      ))}
      {ring && <circle r={0.34 * R} fill={ring} />}
      <circle r={0.24 * R} fill={center} />
    </g>
  );
}
function Chrysanthemum({ R, c }: { R: number; c: string }) {
  return (
    <g>
      {([[-0.48, -0.2, 0.55], [0.48, -0.26, 0.5], [0.02, 0.44, 0.56]] as const).map(([x, y, k], i) => (
        <g key={i} transform={`translate(${x * R} ${y * R})`}><Daisy R={R * k} c={c} petals={16} center="#c4c76a" /></g>
      ))}
    </g>
  );
}
function Alstroemeria({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  const one = (k: number) => (
    <g>
      {Array.from({ length: 6 }, (_, i) => (
        <ellipse key={i} cx={0} cy={-0.46 * R * k} rx={0.22 * R * k} ry={0.46 * R * k} fill={i % 2 ? shade(c, 1.04) : c} stroke={e} strokeWidth={0.6}
          transform={`rotate(${i * 60 + 15})`} />
      ))}
      {[0, 120, 240].map((a) => (
        <path key={a} d={`M0 ${-0.14 * R * k} L0 ${-0.5 * R * k}`} stroke="#7a3b4a" strokeWidth={0.9} strokeDasharray="1.2 2" transform={`rotate(${a + 15})`} />
      ))}
      <circle r={0.1 * R * k} fill="#d9c36a" />
    </g>
  );
  return (
    <g>
      <g transform={`translate(${-0.46 * R} ${-0.16 * R})`}>{one(0.62)}</g>
      <g transform={`translate(${0.48 * R} ${-0.24 * R})`}>{one(0.56)}</g>
      <g transform={`translate(${0.04 * R} ${0.46 * R})`}>{one(0.6)}</g>
    </g>
  );
}
function Ranunculus({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  return (
    <g>
      {[1, 0.82, 0.64, 0.46, 0.3].map((k, i) => (
        <circle key={k} r={R * k} fill={shade(c, i % 2 ? 0.94 : 1)} stroke={e} strokeWidth={0.8} />
      ))}
      <circle r={R * 0.12} fill="#7e8f4e" />
    </g>
  );
}
function Lily({ R, c }: { R: number; c: string }) {
  const e = edge(c);
  const petal = `M0 0 C${0.3 * R} ${-0.3 * R} ${0.22 * R} ${-0.8 * R} 0 ${-1.05 * R} C${-0.22 * R} ${-0.8 * R} ${-0.3 * R} ${-0.3 * R} 0 0 Z`;
  return (
    <g>
      {Array.from({ length: 6 }, (_, i) => (
        <g key={i} transform={`rotate(${i * 60 + (i % 2 ? 30 : 0)})`}>
          <path d={petal} fill={i % 2 ? shade(c, 0.97) : c} stroke={e} strokeWidth={0.8} transform={i % 2 ? "scale(0.86)" : undefined} />
          <path d={`M0 ${-0.12 * R} L0 ${-0.7 * R}`} stroke="#c9d39a" strokeWidth={1.2} opacity={0.8} />
        </g>
      ))}
      {Array.from({ length: 6 }, (_, i) => {
        const a = (i * 60 + 20) * (Math.PI / 180);
        return (
          <g key={`s${i}`}>
            <path d={`M0 0 L${Math.cos(a) * 0.42 * R} ${Math.sin(a) * 0.42 * R}`} stroke="#b3b77a" strokeWidth={0.8} />
            <ellipse cx={Math.cos(a) * 0.46 * R} cy={Math.sin(a) * 0.46 * R} rx={1.6} ry={2.6} fill="#9b5a2a" transform={`rotate(${i * 60 + 110} ${Math.cos(a) * 0.46 * R} ${Math.sin(a) * 0.46 * R})`} />
          </g>
        );
      })}
    </g>
  );
}

// --- зелень: веточка направлена вверх (ось −Y), длина ~2R
function Sprig({ kind, R, c }: { kind: Kind; R: number; c: string }) {
  const L = R * 2;
  const e = shade(c, 0.75);
  const stem = <path d={`M0 ${R * 0.6} C${R * 0.08} ${-L * 0.3} ${-R * 0.06} ${-L * 0.6} 0 ${-L}`} fill="none" stroke={shade(c, 0.6)} strokeWidth={1.2} />;
  const along = (n: number, f: (i: number, y: number, side: number) => ReactElement) =>
    Array.from({ length: n }, (_, i) => f(i, -L * (0.12 + (i / n) * 0.84), i % 2 ? 1 : -1));
  if (kind === "eucalyptus")
    return (
      <g>
        {stem}
        {along(7, (i, y, side) => <circle key={i} cx={side * R * 0.22} cy={y} r={R * (0.26 - i * 0.015)} fill={c} stroke={e} strokeWidth={0.7} />)}
      </g>
    );
  if (kind === "pistachio")
    return (
      <g>
        {stem}
        {along(8, (i, y, side) => (
          <ellipse key={i} cx={side * R * 0.26} cy={y} rx={R * 0.1} ry={R * 0.34} fill={c} stroke={e} strokeWidth={0.6} transform={`rotate(${side * 40} ${side * R * 0.26} ${y})`} />
        ))}
      </g>
    );
  if (kind === "ruscus")
    return (
      <g>
        {stem}
        {along(6, (i, y, side) => (
          <path key={i} d={`M0 ${y} C${side * R * 0.5} ${y - R * 0.05} ${side * R * 0.5} ${y - R * 0.45} ${side * R * 0.1} ${y - R * 0.55} Z`} fill={c} stroke={e} strokeWidth={0.6} />
        ))}
      </g>
    );
  if (kind === "gypsophila")
    return (
      <g>
        {[-0.35, 0, 0.35].map((k, j) => (
          <path key={j} d={`M0 ${R * 0.4} Q${k * R * 0.6} ${-L * 0.4} ${k * R} ${-L * 0.85}`} fill="none" stroke="#8a9a6e" strokeWidth={0.8} />
        ))}
        {Array.from({ length: 26 }, (_, i) => {
          const t = 0.35 + ((i * 37) % 100) / 160;
          const k = ((i * 53) % 100) / 100 - 0.5;
          return <circle key={i} cx={k * R * 1.4} cy={-L * t} r={2 + (i % 3) * 0.5} fill={c} stroke="rgb(176,166,150)" strokeWidth={0.4} />;
        })}
      </g>
    );
  return (
    <g>
      {stem}
      {along(6, (i, y, side) => (
        <ellipse key={i} cx={side * R * 0.24} cy={y} rx={R * 0.14} ry={R * 0.3} fill={c} stroke={e} strokeWidth={0.6} transform={`rotate(${side * 35} ${side * R * 0.24} ${y})`} />
      ))}
    </g>
  );
}

/** Спрей-формы (несколько бутонов на стебле) на фото занимают больше места */
const CLUSTER = new Set<Kind>(["sprayRose", "eustoma", "chrysanthemum", "alstroemeria"]);
export const photoSize = (kind: Kind, R: number) => R * (CLUSTER.has(kind) ? 3.2 : 2.95);

/** Настоящий цветок: фото бутона без фона + мягкая тень под ним */
function PhotoHead({ href, kind, R, shadow }: { href: string; kind: Kind; R: number; shadow: string }) {
  const S = photoSize(kind, R);
  return (
    <g>
      <ellipse cx={R * 0.1} cy={R * 0.38} rx={R * 1.4} ry={R * 1.25} fill={`url(#${shadow})`} />
      <image href={href} x={-S / 2} y={-S / 2} width={S} height={S} preserveAspectRatio="xMidYMid meet" style={{ pointerEvents: "none" }} />
    </g>
  );
}
/** Настоящая зелень: фото ветки, основание — к центру букета */
function PhotoSprig({ href, H }: { href: string; H: number }) {
  return <image href={href} x={-H / 2} y={-H * 0.9} width={H} height={H} preserveAspectRatio="xMidYMax meet" style={{ pointerEvents: "none" }} />;
}

export function Head({ kind, R, c }: { kind: Kind; R: number; c: string }) {
  switch (kind) {
    case "peonyRose": return <PeonyRose R={R} c={c} />;
    case "sprayRose": return <SprayRose R={R} c={c} />;
    case "tulip": return <Tulip R={R} c={c} />;
    case "peony": return <Peony R={R} c={c} />;
    case "hydrangea": return <Hydrangea R={R} c={c} />;
    case "eustoma": return <Eustoma R={R} c={c} />;
    case "chrysanthemum": return <Chrysanthemum R={R} c={c} />;
    case "alstroemeria": return <Alstroemeria R={R} c={c} />;
    case "gerbera": return <Daisy R={R} c={c} petals={18} center="#5a3b1e" ring="#c98a2b" />;
    case "ranunculus": return <Ranunculus R={R} c={c} />;
    case "lily": return <Lily R={R} c={c} />;
    case "eucalyptus": case "pistachio": case "ruscus": case "gypsophila": case "leaf":
      return <Sprig kind={kind} R={R} c={c} />;
    default: return <Rose R={R} c={c} />;
  }
}

/** Иконка вида для палитры и «призрака» при перетаскивании */
export function KindIcon({ kind, color, size = 44 }: { kind: Kind; color: string; size?: number }) {
  const green = isGreen(kind);
  return (
    <svg width={size} height={size} viewBox="-30 -30 60 60" aria-hidden style={{ overflow: "visible" }}>
      {green ? <g transform="translate(0 22)"><Sprig kind={kind} R={24} c={color} /></g> : <Head kind={kind} R={kind === "hydrangea" || kind === "peony" ? 24 : 21} c={color} />}
    </svg>
  );
}

// ------------------------------------------------------------------ упаковка
export type Wrap = "none" | "paper" | "film" | "felt" | "box";
type Material = Pick<CatalogItem, "name"> & { species?: string };
const WRAP_STYLE: Record<string, Wrap> = { бумага: "paper", плёнка: "film", пленка: "film", фетр: "felt", коробка: "box" };
/** Материал упаковки: сначала по полю «Стиль» (species), затем по названию */
export function wrapOf(p?: Material | null): Wrap {
  if (!p) return "none";
  const st = WRAP_STYLE[(p.species || "").trim().toLowerCase()];
  if (st) return st;
  const n = p.name.toLowerCase();
  if (n.includes("коробк")) return "box";
  if (n.includes("плёнк") || n.includes("пленк")) return "film";
  if (n.includes("фетр")) return "felt";
  return "paper";
}
export type { RibbonKind } from "./ribbon3d";
import type { RibbonKind } from "./ribbon3d";
export function ribbonOf(p?: Material | null): RibbonKind | null {
  if (!p) return null;
  const n = `${(p.species || "").toLowerCase()} ${p.name.toLowerCase()}`;
  if (n.includes("шпагат") || n.includes("джут") || n.includes("рафи")) return "twine";
  if (n.includes("органз")) return "organza";
  if (n.includes("шёлк") || n.includes("шелк")) return "silk";
  return "satin";
}

export type Area = { cx: number; cy: number; rx: number; ry: number; bx: number; by: number };
export function areaFor(wrap: Wrap): Area {
  return wrap === "box"
    ? { cx: 200, cy: 236, rx: 128, ry: 46, bx: 200, by: 300 }
    : { cx: 200, cy: 170, rx: 136, ry: 110, bx: 200, by: 322 };
}
export const toXY = (a: Area, u: number, v: number) => ({ x: a.cx + u * a.rx, y: a.cy + v * a.ry });
export function toUV(a: Area, x: number, y: number) {
  let u = (x - a.cx) / a.rx;
  let v = (y - a.cy) / a.ry;
  const d = Math.hypot(u, v);
  if (d > 0.98) {
    u = (u / d) * 0.98;
    v = (v / d) * 0.98;
  }
  return { u, v };
}

// --- геометрия листов упаковки
type Pt = [number, number];
type Cubic = [Pt, Pt, Pt, Pt];
type Sheet = { pts: Pt[]; nrm: Pt[] };
const r1 = (n: number) => Math.round(n * 10) / 10;
const poly = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${r1(p[0])} ${r1(p[1])}`).join(" ");
function cubicAt(c: Cubic, t: number): Pt {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, d = 3 * u * t * t, e = t * t * t;
  return [a * c[0][0] + b * c[1][0] + d * c[2][0] + e * c[3][0], a * c[0][1] + b * c[1][1] + d * c[2][1] + e * c[3][1]];
}
/** Верхний край листа: бумага — почти ровный, плёнка — острые «зубцы», фетр — мягкая волна */
function sheetEdge(c: Cubic, wrap: Wrap, seed: number): Sheet {
  const n = wrap === "film" ? 34 : 40;
  const pts: Pt[] = [];
  const nrm: Pt[] = [];
  for (let k = 0; k <= n; k++) {
    const t = k / n;
    const [x, y] = cubicAt(c, t);
    const p0 = cubicAt(c, Math.max(0, t - 0.01));
    const p1 = cubicAt(c, Math.min(1, t + 0.01));
    let tx = p1[0] - p0[0], ty = p1[1] - p0[1];
    const L = Math.hypot(tx, ty) || 1;
    tx /= L;
    ty /= L;
    let nx = ty, ny = -tx; // нормаль наружу — вверх по экрану
    if (ny > 0) { nx = -nx; ny = -ny; }
    const env = Math.sin(Math.PI * t);
    let o = 0;
    if (wrap === "felt") o = 3.4 * Math.sin(t * Math.PI * 12 + seed) * (0.35 + 0.65 * env);
    else if (wrap === "film") o = ((k % 2 ? -0.8 : 1) * (1 + 2.6 * seeded(seed * 31 + k)) + 1.6 * Math.sin(t * 23 + seed)) * env;
    else o = 1.1 * Math.sin(t * 19 + seed) * env;
    pts.push([x + nx * o, y + ny * o]);
    nrm.push([nx, ny]);
  }
  return { pts, nrm };
}
/** Линия на заданном расстоянии внутрь листа (под краем) */
const inset = (s: Sheet, w: (t: number) => number): Pt[] =>
  s.pts.map((p, k) => {
    const t = k / (s.pts.length - 1);
    const d = w(t);
    return [p[0] - s.nrm[k][0] * d, p[1] - s.nrm[k][1] * d];
  });
const band = (a: Pt[], b: Pt[]) => `${poly(a)} ${poly([...b].reverse()).replace(/^M/, "L")} Z`;

const BACK_TOPS: Cubic[] = [
  [[104, 66], [150, 28], [250, 28], [296, 66]],
  [[34, 214], [26, 150], [58, 82], [128, 44]],
  [[366, 214], [374, 150], [342, 82], [272, 44]],
];
const FRONT_L: Cubic = [[48, 222], [110, 248], [200, 266], [278, 256]];
const FRONT_R: Cubic = [[352, 222], [290, 248], [212, 266], [148, 262]];
type Geom = { backs: Sheet[]; backD: string[]; fl: Sheet; fr: Sheet; L: string; R: string };
const GEOM = new Map<Wrap, Geom>();
function geom(wrap: Wrap): Geom {
  const hit = GEOM.get(wrap);
  if (hit) return hit;
  const backs = BACK_TOPS.map((c, k) => sheetEdge(c, wrap, 3 + k * 2));
  const fl = sheetEdge(FRONT_L, wrap, 11);
  const fr = sheetEdge(FRONT_R, wrap, 17);
  const g: Geom = {
    backs,
    backD: backs.map((s) => `${poly(s.pts)} L200 342 Z`),
    fl,
    fr,
    // левый лист (передний): верхний край → сгиб по диагонали → «юбка» под перевязкой → левый край конуса
    L: `${poly(fl.pts)} Q236 300 220 356 L236 448 Q200 457 162 447 L176 356 Q108 302 48 222 Z`,
    R: `${poly(fr.pts)} L176 356 L162 447 Q200 457 236 448 L224 356 Q292 302 352 222 Z`,
  };
  GEOM.set(wrap, g);
  return g;
}

/** id градиентов и фильтров одной сцены (useId — чтобы несколько эскизов на странице не конфликтовали) */
type Ids = { cyl: string; back: string; tip: string; gloss: string; grain: string; pearl: string; shadow: string; rshadow: string; bed?: string };
type Tex = string | null;

/** Край листа: у бумаги — подвёрнутый «завиток» с обратной стороной, у фетра — толщина, у плёнки — блик */
function Rim({ s, wrap, c, tex, back }: { s: Sheet; wrap: Wrap; c: string; tex?: Tex; back?: boolean }) {
  if (wrap === "film")
    return (
      <g fill="none" strokeLinejoin="round">
        <path d={poly(s.pts)} stroke="rgba(255,255,255,0.9)" strokeWidth={1.5} />
        <path d={poly(inset(s, () => 3.5))} stroke="rgba(255,255,255,0.35)" strokeWidth={1} />
      </g>
    );
  if (wrap === "felt")
    return (
      <g fill="none">
        <path d={poly(s.pts)} stroke={shade(c, 0.62)} strokeWidth={1.1} />
        <path d={poly(inset(s, () => 2.4))} stroke={shade(c, 1.2)} strokeWidth={1.5} opacity={0.55} />
      </g>
    );
  const wMax = back ? 5 : 8;
  const curl = inset(s, (t) => 2.2 + wMax * Math.pow(Math.sin(Math.PI * t), 0.7));
  const d = band(s.pts, curl);
  return (
    <g>
      <path d={d} fill={tex || shade(c, 1.12)} />
      <path d={d} fill={tex ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.08)"} />
      <path d={poly(curl)} fill="none" stroke="rgba(31,27,22,0.26)" strokeWidth={1.6} strokeLinecap="round" />
      <path d={poly(s.pts)} fill="none" stroke={shade(c, 0.72)} strokeWidth={0.7} opacity={0.8} />
    </g>
  );
}

function WrapBack({ wrap, c, tex, ids }: { wrap: Wrap; c: string; tex?: Tex; ids: Ids }) {
  if (wrap === "none" || wrap === "box") return null;
  const g = geom(wrap);
  const film = wrap === "film";
  return (
    <g>
      {g.backD.map((d, k) => (
        <g key={k}>
          <path d={d} fill={tex || shade(c, k === 0 ? 0.84 : 0.93)} fillOpacity={film ? 0.32 : 1}
            stroke={film ? "rgba(255,255,255,0.55)" : shade(c, 0.66)} strokeOpacity={film ? 1 : 0.5} strokeWidth={0.8} strokeLinejoin="round" />
          {film ? <path d={d} fill={`url(#${ids.gloss})`} opacity={0.55} /> : <path d={d} fill={`url(#${ids.back})`} />}
          <Rim s={g.backs[k]} wrap={wrap} c={c} tex={tex} back />
        </g>
      ))}
      {!film && (
        <g filter={`url(#${ids.grain})`} opacity={wrap === "felt" ? 0.55 : 0.4}>
          {g.backD.map((d, k) => <path key={k} d={d} fill="#000" />)}
        </g>
      )}
    </g>
  );
}

function WrapFront({ wrap, c, tex, ids }: { wrap: Wrap; c: string; tex?: Tex; ids: Ids }) {
  if (wrap === "none" || wrap === "box") return null;
  const g = geom(wrap);
  const film = wrap === "film";
  const op = film ? 0.4 : 1;
  const line = film ? "rgba(255,255,255,0.75)" : shade(c, 0.68);
  return (
    <g strokeLinejoin="round">
      {/* правый лист — под левым */}
      <path d={g.R} fill={tex || shade(c, 0.96)} fillOpacity={op} stroke={line} strokeWidth={0.8} strokeOpacity={film ? 1 : 0.6} />
      {film ? <path d={g.R} fill={`url(#${ids.gloss})`} /> : <path d={g.R} fill={`url(#${ids.cyl})`} />}
      <Rim s={g.fr} wrap={wrap} c={c} tex={tex} />
      {/* тень от переднего листа */}
      {!film && <path d={g.L} transform="translate(5 2)" fill="rgba(31,27,22,0.13)" />}
      <path d={g.L} fill={tex || c} fillOpacity={op} stroke={line} strokeWidth={0.8} strokeOpacity={film ? 1 : 0.6} />
      {film ? <path d={g.L} fill={`url(#${ids.gloss})`} /> : <path d={g.L} fill={`url(#${ids.cyl})`} />}
      {!film && <path d={g.L} fill={`url(#${ids.tip})`} />}
      {/* подсвеченный сгиб переднего листа */}
      <path d="M278 256 Q236 300 220 356" fill="none" stroke={film ? "rgba(255,255,255,0.9)" : shade(c, 1.22)} strokeWidth={1.3} opacity={0.75} />
      <Rim s={g.fl} wrap={wrap} c={c} tex={tex} />
      {/* складки «юбки» под перевязкой */}
      <path d="M186 362 L177 446 M200 364 L200 452 M213 362 L224 447" fill="none" stroke={line} strokeWidth={0.8} opacity={0.45} />
      {film && (
        <path d="M92 252 l14 22 -6 14 M300 250 l-10 24 8 12 M150 300 l10 18 M246 296 l-8 20 6 10 M120 236 l26 6"
          fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={0.9} strokeLinecap="round" />
      )}
      {!film && (
        <g filter={`url(#${ids.grain})`} opacity={wrap === "felt" ? 0.55 : 0.42}>
          <path d={g.R} fill="#000" />
          <path d={g.L} fill="#000" />
        </g>
      )}
    </g>
  );
}

function BoxBack({ c, tex }: { c: string; tex?: Tex }) {
  return (
    <g>
      <ellipse cx={200} cy={262} rx={152} ry={44} fill={tex || shade(c, 0.55)} stroke={shade(c, 0.5)} strokeWidth={1} />
      {tex && <ellipse cx={200} cy={262} rx={152} ry={44} fill="rgba(31,27,22,0.42)" />}
    </g>
  );
}
function BoxFront({ c, tex, ids }: { c: string; tex?: Tex; ids: Ids }) {
  const body = "M48 262 L48 392 A152 30 0 0 0 352 392 L352 262 A152 44 0 0 1 48 262 Z";
  return (
    <g>
      <path d={body} fill={tex || c} stroke={shade(c, 0.7)} strokeWidth={1} />
      <path d={body} fill={`url(#${ids.cyl})`} />
      <path d="M48 262 A152 44 0 0 0 352 262" fill="none" stroke={shade(c, 1.15)} strokeWidth={2.4} opacity={0.75} />
    </g>
  );
}

// --- лента и банты
/** Куда отдаёт картинки ленты маршрут app/ribbon/[key]/route.ts (для офлайн-превью можно подменить) */
let RIBBON_BASE = "/ribbon/";
export const setRibbonBase = (b: string) => {
  RIBBON_BASE = b;
};
/** Объёмная лента (бант, обвязка, обмотка стеблей): PNG из программного 3D-рендера, привязанный к точке (x, y) */
function Ribbon3D({ spec, x, y, ids }: { spec: RibbonSpec; x: number; y: number; ids: Ids }) {
  const b = ribbonBox(spec);
  return (
    <image
      href={`${RIBBON_BASE}${ribbonKey(spec)}.png`}
      x={x + b.x}
      y={y + b.y}
      width={b.w}
      height={b.h}
      preserveAspectRatio="none"
      filter={`url(#${ids.rshadow})`}
      data-ribbon={spec.scene}
      style={{ pointerEvents: "none" }}
    />
  );
}
/** Без упаковки: стебли собраны в пучок и видны до среза */
function StemBundle({ n }: { n: number }) {
  const k = Math.max(5, Math.min(16, n));
  const tones = ["#5f7f47", "#6f9152", "#557341", "#678a4c"];
  return (
    <g strokeLinecap="round">
      {Array.from({ length: k }, (_, i) => {
        const o = i - (k - 1) / 2;
        const x0 = 200 + o * 1.7, x1 = 200 + o * 3.4 + Math.sin(i * 2.3) * 1.2;
        return <path key={i} d={`M${r1(x0)} 322 Q${r1(200 + o * 2.2)} 390 ${r1(x1)} 446`} stroke={tones[i % 4]} strokeWidth={2.6} fill="none" />;
      })}
      {Array.from({ length: k }, (_, i) => {
        const o = i - (k - 1) / 2;
        return <ellipse key={`c${i}`} cx={r1(200 + o * 3.4 + Math.sin(i * 2.3) * 1.2)} cy={446.5} rx={1.4} ry={0.7} fill="#b9cf9a" />;
      })}
    </g>
  );
}
/** Полуширина пучка стеблей на уровне перевязки */
const bundleW = (n: number) => Math.round((Math.max(5, Math.min(16, n)) - 1) * 0.9 + 6);
/** Перевязка стеблей без упаковки и в вазе: лента — витками вокруг пучка и бантом спереди, шпагат — тоже с бантиком */
function StemTie({ kind, c, n, ids, y = 354, scene = "stem" }: { kind: RibbonKind | null; c?: string; n: number; ids: Ids; y?: number; scene?: "stem" | "vase" }) {
  const w = bundleW(n);
  const spec: RibbonSpec = kind && c ? { scene, kind, color: c, w } : { scene: "tie", kind: "twine", color: "#b8a07a", w };
  return <Ribbon3D spec={spec} x={200} y={y} ids={ids} />;
}
/** Подпись: бумажная бирка (открытка) на нитке */
function Tag({ x, y, text, from }: { x: number; y: number; text: string; from: [number, number] }) {
  const words = (text || "Открытка").split(/\s+/);
  const lines: string[] = [];
  for (const w of words) {
    const last = lines[lines.length - 1];
    if (last && (last + " " + w).length <= 14) lines[lines.length - 1] = last + " " + w;
    else lines.push(w);
  }
  return (
    <g>
      <path d={`M${from[0]} ${from[1]} Q${(from[0] + x) / 2} ${Math.max(from[1], y) + 18} ${x - 30} ${y - 14}`} fill="none" stroke="#8a7a62" strokeWidth={1} />
      <g transform={`translate(${x} ${y}) rotate(-7)`}>
        <path d="M-40 -22 L32 -22 L44 0 L32 22 L-40 22 Z" fill="#f6efe2" stroke="#b8a888" strokeWidth={1} />
        <circle cx={-30} cy={0} r={3.2} fill="#efe9df" stroke="#b8a888" strokeWidth={0.8} />
        {lines.slice(0, 3).map((l, i, arr) => (
          <text key={i} x={4} y={(i - (arr.length - 1) / 2) * 11 + 3.5} textAnchor="middle" fontSize={9.5} fill="#5e554a" style={{ fontFamily: "var(--font-sans)" }}>
            {i === 2 && lines.length > 3 ? l + "…" : l}
          </text>
        ))}
      </g>
    </g>
  );
}

// ------------------------------------------------------------------ сцена
export type CanvasProps = {
  catalog: Map<number, CatalogItem>;
  insts: Inst[];
  packaging?: CatalogItem | null;
  ribbon?: CatalogItem | null;
  card?: { text: string } | null;
  selected?: number | null;
  dragging?: number | null;
  removing?: boolean;
  dropHint?: boolean;
  empty?: string;
  onInstDown?: (e: React.PointerEvent, uid: number) => void;
  svgRef?: React.Ref<SVGSVGElement>;
  className?: string;
  label?: string;
  /** Примерка в вазе: упаковка снята, стебли в воде (для шляпной коробки не применяется) */
  vase?: VaseShape | null;
};

const sceneScale = (insts: Inst[], catalog: Map<number, CatalogItem>) => {
  const fl = insts.filter((i) => !isGreen(kindOf(catalog.get(i.item_id)))).length;
  return headScale(fl + (insts.length - fl) * 0.4);
};
/** Центр и радиус выбранного стебля в координатах холста — для панели «Отразить / Повернуть / Убрать» */
export function instBox(catalog: Map<number, CatalogItem>, insts: Inst[], packaging: CatalogItem | null | undefined, uid: number) {
  const it = insts.find((i) => i.uid === uid);
  if (!it) return null;
  const a = areaFor(wrapOf(packaging));
  const item = catalog.get(it.item_id);
  const kind = kindOf(item);
  const s = sceneScale(insts, catalog);
  const { x, y } = toXY(a, it.u, it.v);
  if (isGreen(kind)) return { x, y, r: BASE_R[kind] * Math.max(0.75, s) * 0.9 };
  const R = BASE_R[kind] * s * (0.9 + 0.1 * ((it.v + 1) / 2));
  return { x, y, r: item?.constructor_image ? photoSize(kind, R) * 0.46 : R };
}

export function BouquetCanvas(p: CanvasProps) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const ids: Ids = {
    cyl: `bqc-${uid}`, back: `bqb-${uid}`, tip: `bqt-${uid}`, gloss: `bqg-${uid}`, grain: `bqn-${uid}`,
    pearl: `bqp-${uid}`, shadow: `bqsh-${uid}`, rshadow: `bqrs-${uid}`, bed: `bqbd-${uid}`,
  };
  const texId = `bqtx-${uid}`;
  const texUrl = p.packaging?.constructor_image || null;
  const tex = texUrl ? `url(#${texId})` : null;
  const wrap = wrapOf(p.packaging);
  const vz = p.vase && wrap !== "box" ? vaseGeom(p.vase) : null;
  const a = vz ? { ...areaFor("none"), by: vz.bind } : areaFor(wrap);
  const vids: VaseIds = { body: `bqvb-${uid}`, hl: `bqvh-${uid}`, shadow: `bqvs-${uid}`, caustic: `bqvc-${uid}`, water: `bqvw-${uid}`, table: `bqvt-${uid}`, clipW: `bqvcw-${uid}`, clipA: `bqvca-${uid}` };
  const packColor = p.packaging?.color_hex || "#c49a6c";
  const rKind = ribbonOf(p.ribbon);
  const ribbonColor = p.ribbon?.color_hex || (rKind === "twine" ? "#b8a07a" : undefined);
  const flowers = p.insts.filter((i) => !isGreen(kindOf(p.catalog.get(i.item_id))));
  const greens = p.insts.filter((i) => isGreen(kindOf(p.catalog.get(i.item_id))));
  const s = sceneScale(p.insts, p.catalog);
  const sorted = [...flowers].sort((x, y) => x.v - y.v);
  const bow = wrap === "box" ? { x: 200, y: 364 } : wrap === "none" ? { x: 200, y: 346 } : { x: 200, y: 354 };
  const flip = (i: Inst) => (i.f ? "scale(-1 1)" : undefined);

  const head = (i: Inst, interactive: boolean) => {
    const item = p.catalog.get(i.item_id);
    const kind = kindOf(item);
    const { x, y } = toXY(a, i.u, i.v);
    const depth = 0.9 + 0.1 * ((i.v + 1) / 2);
    // одинаковые фото не должны выглядеть «наклейками»: размер ±7% и зеркальность — от uid (стабильно)
    const R = BASE_R[kind] * s * depth * (0.93 + 0.14 * seeded(i.uid * 7 + 3));
    const mirror = !!i.f !== seeded(i.uid * 3 + 1) > 0.55;
    const sel = p.selected === i.uid;
    const drag = p.dragging === i.uid;
    return (
      <g
        key={i.uid}
        transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${i.r})`}
        className={interactive ? "bq-head" : undefined}
        opacity={drag && p.removing ? 0.35 : 1}
        onPointerDown={interactive ? (e) => p.onInstDown?.(e, i.uid) : undefined}
        data-uid={i.uid}
        data-item={i.item_id}
        data-flip={i.f ? 1 : undefined}
      >
        <g transform={mirror ? "scale(-1 1)" : undefined}>
          {item?.constructor_image ? (
            <PhotoHead href={item.constructor_image} kind={kind} R={R} shadow={ids.shadow} />
          ) : (
            <Head kind={kind} R={R} c={item?.color_hex || "#d9a7b0"} />
          )}
        </g>
        {interactive && <circle r={Math.max(R, 14)} fill="transparent" />}
        {sel && <circle r={(item?.constructor_image ? photoSize(kind, R) * 0.46 : R) + 5} fill="none" stroke="var(--green)" strokeWidth={1.5} strokeDasharray="4 3" />}
      </g>
    );
  };

  const sprig = (i: Inst, interactive: boolean) => {
    const item = p.catalog.get(i.item_id);
    const kind = kindOf(item);
    const { x, y } = toXY(a, i.u, i.v);
    const ang = (Math.atan2(y - a.by, x - a.bx) * 180) / Math.PI + 90;
    const photo = item?.constructor_image;
    const R = BASE_R[kind] * (photo ? Math.min(1.3, Math.max(0.75, s)) : Math.max(0.75, s));
    const rot = ang * 0.8 + i.r * 0.6;
    // фото-ветка не должна вылезать за край холста: длина — по свободному месту в направлении роста
    let H = R * 2.7;
    if (photo) {
      const t = (rot * Math.PI) / 180;
      const dx = Math.sin(t), dy = -Math.cos(t);
      const room = Math.min(dy < -0.05 ? (y - 4) / -dy : 1e3, dx < -0.05 ? (x - 4) / -dx : 1e3, dx > 0.05 ? (VIEW_W - 4 - x) / dx : 1e3);
      H = Math.max(R * 1.5, Math.min(H, (room + R * 0.5) / 0.92));
    }
    const drag = p.dragging === i.uid;
    return (
      <g key={i.uid} transform={`translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${rot.toFixed(1)})`}
        className={interactive ? "bq-head" : undefined} opacity={drag && p.removing ? 0.35 : 1}
        onPointerDown={interactive ? (e) => p.onInstDown?.(e, i.uid) : undefined} data-uid={i.uid} data-item={i.item_id} data-flip={i.f ? 1 : undefined}>
        <g transform={flip(i)}>
          {item?.constructor_image ? (
            <g transform={`translate(0 ${R * 0.5})`}><PhotoSprig href={item.constructor_image} H={H} /></g>
          ) : (
            <g transform={`translate(0 ${R * 0.8})`}><Sprig kind={kind} R={R} c={item?.color_hex || "#7d9a6f"} /></g>
          )}
        </g>
        {interactive && <circle r={R * 0.8} fill="transparent" />}
        {p.selected === i.uid && <circle r={R * 0.9} fill="none" stroke="var(--green)" strokeWidth={1.5} strokeDasharray="4 3" />}
      </g>
    );
  };

  const interactive = !!p.onInstDown;
  // «Глубина» плотного букета: мягкая тень под головками — просветы между цветами читаются как тень
  // внутри букета (листья, стебли), а не как бумага насквозь
  const bed = sorted.length > 2 && (
    <g filter={`url(#${ids.bed})`} opacity={vz || wrap === "none" ? 0.2 : 0.38} style={{ pointerEvents: "none" }}>
      {sorted.map((i) => {
        const { x, y } = toXY(a, i.u, i.v);
        const R = BASE_R[kindOf(p.catalog.get(i.item_id))] * s;
        return <circle key={`bd${i.uid}`} cx={x.toFixed(1)} cy={(y + R * 0.35).toFixed(1)} r={(R * 1.05).toFixed(1)} fill="#2a2a1a" />;
      })}
    </g>
  );

  return (
    <svg ref={p.svgRef} viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className={p.className} role="img" aria-label={p.label || "Эскиз букета"}>
      <defs>
        <radialGradient id={ids.shadow}>
          <stop offset="0.45" stopColor="#1f1b16" stopOpacity="0.26" />
          <stop offset="1" stopColor="#1f1b16" stopOpacity="0" />
        </radialGradient>
        {/* цилиндрическая светотень конуса: края темнее, блик левее центра */}
        <linearGradient id={ids.cyl} gradientUnits="userSpaceOnUse" x1={40} y1={0} x2={360} y2={0}>
          <stop offset="0" stopColor="#1f1b16" stopOpacity="0.34" />
          <stop offset="0.2" stopColor="#1f1b16" stopOpacity="0.1" />
          <stop offset="0.38" stopColor="#fff" stopOpacity="0.18" />
          <stop offset="0.52" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.78" stopColor="#1f1b16" stopOpacity="0.12" />
          <stop offset="1" stopColor="#1f1b16" stopOpacity="0.36" />
        </linearGradient>
        <linearGradient id={ids.back} gradientUnits="userSpaceOnUse" x1={0} y1={340} x2={0} y2={30}>
          <stop offset="0" stopColor="#1f1b16" stopOpacity="0.42" />
          <stop offset="0.55" stopColor="#1f1b16" stopOpacity="0.16" />
          <stop offset="1" stopColor="#1f1b16" stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id={ids.tip} gradientUnits="userSpaceOnUse" x1={0} y1={250} x2={0} y2={452}>
          <stop offset="0" stopColor="#1f1b16" stopOpacity="0" />
          <stop offset="0.55" stopColor="#1f1b16" stopOpacity="0.1" />
          <stop offset="1" stopColor="#1f1b16" stopOpacity="0.2" />
        </linearGradient>
        <linearGradient id={ids.gloss} x1={0} y1={0} x2={1} y2={0.35}>
          <stop offset="0.12" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.2" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="0.25" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.52" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.57" stopColor="#fff" stopOpacity="0.32" />
          <stop offset="0.61" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.8" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.86" stopColor="#fff" stopOpacity="0.42" />
          <stop offset="0.9" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        {/* зерно бумаги / ворс фетра */}
        <filter id={ids.grain} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency={wrap === "felt" ? 1.3 : 0.85} numOctaves={2} seed={7} result="n" />
          <feColorMatrix in="n" type="matrix" values="0 0 0 0 0.12  0 0 0 0 0.1  0 0 0 0 0.08  1.7 0 0 0 -0.62" result="g" />
          <feComposite in="g" in2="SourceGraphic" operator="in" />
        </filter>
        <filter id={ids.rshadow} x="-15%" y="-15%" width="130%" height="140%">
          <feDropShadow dx={0.6} dy={1.8} stdDeviation={1.5} floodColor="#1f1b16" floodOpacity={0.3} />
        </filter>
        <filter id={ids.bed} x="-25%" y="-25%" width="150%" height="150%">
          <feGaussianBlur stdDeviation={5} />
        </filter>
        <radialGradient id={ids.pearl} fx={0.35} fy={0.3}>
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.55" stopColor="#f1ece4" />
          <stop offset="1" stopColor="#c9bfae" />
        </radialGradient>
        {texUrl && (
          <pattern id={texId} patternUnits="userSpaceOnUse" width={128} height={128}>
            <image href={texUrl} width={128} height={128} preserveAspectRatio="none" />
          </pattern>
        )}
      </defs>
      {vz ? <VaseGround g={vz} ids={vids} /> : <ellipse cx={200} cy={wrap === "box" ? 414 : 450} rx={wrap === "box" ? 164 : wrap === "none" ? 34 : 54} ry={wrap === "box" ? 12 : 6} fill="rgba(31,27,22,0.1)" />}
      {vz ? <VaseBack g={vz} ids={vids} /> : wrap === "box" ? <BoxBack c={packColor} tex={tex} /> : <WrapBack wrap={wrap} c={packColor} tex={tex} ids={ids} />}
      {p.dropHint && <ellipse cx={a.cx} cy={a.cy} rx={a.rx + 6} ry={a.ry + 6} fill="rgba(62,91,54,0.06)" stroke="var(--green)" strokeWidth={1.5} strokeDasharray="6 5" />}
      {!p.insts.length && !p.dropHint && (
        <g>
          <ellipse cx={a.cx} cy={a.cy} rx={a.rx} ry={a.ry} fill="none" stroke="rgba(31,27,22,0.18)" strokeWidth={1.2} strokeDasharray="5 5" />
          <text x={a.cx} y={a.cy + 4} textAnchor="middle" fontSize={13} fill="#7b7266" style={{ fontFamily: "var(--font-sans)" }}>{p.empty || "Перетащите цветы сюда"}</text>
        </g>
      )}
      {(vz || wrap === "none") && greens.length > 0 && (
        <g fill="none" stroke="#6d8b58" strokeWidth={1.2} strokeLinecap="round" opacity={0.8}>
          {greens.map((g) => {
            const { x, y } = toXY(a, g.u, g.v);
            return <path key={`gs${g.uid}`} d={`M${x.toFixed(1)} ${y.toFixed(1)} Q${((x + a.bx) / 2).toFixed(1)} ${((y + a.by) / 2 + 8).toFixed(1)} ${a.bx} ${a.by}`} />;
          })}
        </g>
      )}
      {greens.map((g) => sprig(g, interactive))}
      {vz && sorted.length > 0 && (() => {
        const low = vaseStems(vz, sorted.map((i) => ({ ...toXY(a, i.u, i.v), w: p.catalog.get(i.item_id)?.constructor_image ? 2.2 : 1.6, key: String(i.uid) })), Math.round(greens.length / 2));
        return (
          <g strokeLinecap="round" fill="none">
            <g clipPath={`url(#${vids.clipA})`}>{low.map((s) => <path key={s.key} d={s.d} stroke="#5c7a45" strokeWidth={s.w} opacity={0.9} />)}</g>
            <g clipPath={`url(#${vids.clipW})`}>
              <g transform="matrix(1.12 0 0 1 -24 0)">
                {low.map((s) => <path key={s.key} d={s.d} stroke="#557d52" strokeWidth={s.w * 1.1} opacity={0.88} />)}
                {low.map((s) => <ellipse key={`c${s.key}`} cx={s.xe} cy={s.ye + 0.4} rx={s.w * 0.6} ry={0.6} fill="#b9cf9a" stroke="none" />)}
              </g>
            </g>
            <VaseWater g={vz} ids={vids} />
          </g>
        );
      })()}
      {!vz && (wrap === "none" || wrap === "film") && sorted.length > 0 && <StemBundle n={sorted.length + Math.round(greens.length / 2)} />}
      {wrap !== "box" &&
        sorted.map((i) => {
          const { x, y } = toXY(a, i.u, i.v);
          return <path key={`st${i.uid}`} d={`M${x.toFixed(1)} ${y.toFixed(1)} Q${((x + a.bx) / 2).toFixed(1)} ${((y + a.by) / 2 + 10).toFixed(1)} ${a.bx} ${a.by}`} fill="none" stroke="#5c7a45" strokeWidth={p.catalog.get(i.item_id)?.constructor_image ? 2.2 : 1.4} opacity={0.85} strokeLinecap="round" />;
        })}
      {vz ? (
        <>
          {sorted.length > 0 && <StemTie kind={rKind} c={ribbonColor} n={sorted.length + Math.round(greens.length / 2)} ids={ids} y={vz.bind} scene="vase" />}
          <VaseFront g={vz} ids={vids} />
          {bed}
          {sorted.map((i) => head(i, interactive))}
        </>
      ) : (
        <>
          {bed}
          {sorted.map((i) => head(i, interactive))}
          {wrap === "box" ? <BoxFront c={packColor} tex={tex} ids={ids} /> : <WrapFront wrap={wrap} c={packColor} tex={tex} ids={ids} />}
          {wrap === "none" && sorted.length > 0 && <StemTie kind={rKind} c={ribbonColor} n={sorted.length + Math.round(greens.length / 2)} ids={ids} />}
          {wrap !== "none" && ribbonColor && rKind && <Ribbon3D spec={{ scene: wrap === "box" ? "box" : "wrap", kind: rKind, color: ribbonColor }} x={bow.x} y={bow.y} ids={ids} />}
        </>
      )}
      {p.card && <Tag x={318} y={wrap === "box" && !vz ? 380 : 372} text={p.card.text} from={vz ? [200 + vz.r(vz.y0 + 6) * 0.8, vz.y0 + 8] : [bow.x + 8, bow.y + 6]} />}
    </svg>
  );
}

// ------------------------------------------------------------------ авторасстановка
const GOLD = 2.39996;
export function spiralSpot(k: number, n: number) {
  const r = spread(n) * Math.sqrt((k + 0.5) / Math.max(n, 1));
  const t = k * GOLD;
  const u = r * Math.cos(t);
  const v = r * Math.sin(t);
  // купол чуть выше центра раскрытия и уже внизу — нижние головки не свисают за край конуса упаковки
  return { u: u * (1 - 0.18 * Math.max(0, v)), v: v * 0.95 - 0.03 };
}
function seeded(i: number) {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}
export function arrange(insts: Inst[], catalog: Map<number, CatalogItem>): Inst[] {
  const fl = insts.filter((i) => !isGreen(kindOf(catalog.get(i.item_id))));
  const gr = insts.filter((i) => isGreen(kindOf(catalog.get(i.item_id))));
  // чередуем сорта, чтобы букет смотрелся «миксом», а не секторами
  const order = fl.map((x, i) => ({ x, k: (i * 7919) % 101 })).sort((a, b) => a.k - b.k).map((o) => o.x);
  const placed = order.map((x, k) => ({ ...x, ...spiralSpot(k, order.length), r: Math.round((seeded(x.uid) - 0.5) * 40), m: undefined }));
  const gR = Math.min(0.86, spread(fl.length) + 0.14);
  const ring = gr.map((x, k) => {
    const t = (k / Math.max(gr.length, 1)) * Math.PI * 2 + 0.4;
    return { ...x, u: Math.cos(t) * gR, v: Math.sin(t) * gR, r: Math.round((seeded(x.uid) - 0.5) * 20) };
  });
  return [...ring, ...placed];
}
/**
 * Плотная раскладка «шапкой»: цветы, добавленные кнопкой «+», встают по золотой спирали от центра
 * (в порядке добавления), без дыр и без выхода за упаковку. Стебли, которые покупатель
 * поставил сам (m), остаются на месте — спираль обходит их.
 */
export function pack(insts: Inst[], catalog: Map<number, CatalogItem>): Inst[] {
  const fl = insts.filter((i) => !isGreen(kindOf(catalog.get(i.item_id))));
  const auto = fl.filter((i) => !i.m);
  if (!auto.length) return insts;
  const manual = fl.filter((i) => i.m);
  const n = fl.length;
  const step = (1.9 * spread(n)) / Math.sqrt(n); // типичное расстояние между соседями на спирали
  const slots: { u: number; v: number }[] = [];
  for (let k = 0; slots.length < auto.length && k < n * 4 + 8; k++) {
    const c = spiralSpot(k, n);
    if (manual.some((m) => Math.hypot(m.u - c.u, m.v - c.v) < step * 0.62)) continue;
    slots.push(c);
  }
  for (let k = n * 4 + 8; slots.length < auto.length; k++) slots.push(spiralSpot(k % n, n));
  const at = new Map(auto.map((i, j) => [i.uid, slots[j]]));
  return insts.map((i) => {
    const c = at.get(i.uid);
    return c ? { ...i, u: +c.u.toFixed(4), v: +c.v.toFixed(4) } : i;
  });
}
/** Свободное место для нового стебля: точка спирали дальше всего от уже стоящих */
export function freeSpot(insts: Inst[], green: boolean, seed: number) {
  if (green) {
    const t = seeded(seed) * Math.PI * 2;
    const r = Math.min(0.86, spread(insts.length) + 0.14);
    return { u: Math.cos(t) * r, v: Math.sin(t) * r };
  }
  const n = insts.length + 1;
  let best = spiralSpot(0, n);
  let bestD = -1;
  for (let k = 0; k < Math.max(12, n * 2); k++) {
    const c = spiralSpot(k, n);
    const d = insts.reduce((m, i) => Math.min(m, Math.hypot(i.u - c.u, (i.v - c.v) * 0.9)), 9);
    if (d > bestD + 0.02) {
      best = c;
      bestD = d;
    }
    if (bestD > 0.3) break;
  }
  return best;
}
