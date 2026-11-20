// Примерка букета в стеклянной вазе: профиль вазы, вода с преломлением стеблей, блики и тень стекла.
// Упаковку перед тем, как поставить букет в воду, снимают — поэтому в вазе видны стебли и перевязка.
export type VaseShape = "cylinder" | "bubble" | "cone";
export const VASES: { id: VaseShape; label: string; hint: string }[] = [
  { id: "cylinder", label: "Цилиндр", hint: "Высокая прямая ваза" },
  { id: "bubble", label: "Шар", hint: "Круглая ваза с узким горлом" },
  { id: "cone", label: "Конус", hint: "Ваза, расширяющаяся кверху" },
];

type Prof = { y0: number; y1: number; base: number; wall: number; bind: number; pts: [number, number][] };
const PROFILES: Record<VaseShape, Prof> = {
  cylinder: { y0: 298, y1: 448, base: 16, wall: 2.6, bind: 316, pts: [[298, 30], [374, 30], [448, 30]] },
  bubble: { y0: 316, y1: 448, base: 8, wall: 2.3, bind: 330, pts: [[316, 25], [324, 23.5], [336, 27.5], [354, 43], [378, 56.5], [402, 60], [424, 55], [440, 45.5], [448, 38]] },
  cone: { y0: 296, y1: 448, base: 12, wall: 2.6, bind: 316, pts: [[296, 47], [340, 39.5], [390, 32.5], [430, 28.8], [448, 28.4]] },
};
/** Наклон взгляда: окружность радиуса r видна эллипсом с полуосью r·E */
const E = 0.2;
const CX = 200;

export type VaseGeom = {
  shape: VaseShape;
  y0: number;
  y1: number;
  yb: number;
  yw: number;
  bind: number;
  wall: number;
  r: (y: number) => number;
  rIn: (y: number) => number;
  samples: [number, number][];
};

const GEO = new Map<VaseShape, VaseGeom>();
export function vaseGeom(shape: VaseShape): VaseGeom {
  const hit = GEO.get(shape);
  if (hit) return hit;
  const p = PROFILES[shape];
  // Catmull-Rom по опорным точкам профиля
  const pts = p.pts;
  const samples: [number, number][] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[i], c = pts[i + 1], d = pts[Math.min(pts.length - 1, i + 2)];
    for (let k = 0; k < 10; k++) {
      const t = k / 10, t2 = t * t, t3 = t2 * t;
      const f = (j: 0 | 1) => 0.5 * (2 * b[j] + (-a[j] + c[j]) * t + (2 * a[j] - 5 * b[j] + 4 * c[j] - d[j]) * t2 + (-a[j] + 3 * b[j] - 3 * c[j] + d[j]) * t3);
      samples.push([f(0), f(1)]);
    }
  }
  samples.push(pts[pts.length - 1]);
  const r = (y: number) => {
    if (y <= samples[0][0]) return samples[0][1];
    for (let i = 1; i < samples.length; i++)
      if (y <= samples[i][0]) {
        const [ya, ra] = samples[i - 1], [yb, rb] = samples[i];
        return ra + ((rb - ra) * (y - ya)) / Math.max(1e-6, yb - ya);
      }
    return samples[samples.length - 1][1];
  };
  const g: VaseGeom = {
    shape,
    y0: p.y0,
    y1: p.y1,
    yb: p.y1 - p.base,
    yw: p.y0 + (p.y1 - p.y0) * (shape === "bubble" ? 0.3 : 0.36),
    bind: p.bind,
    wall: p.wall,
    r,
    rIn: (y) => r(y) - p.wall,
    samples,
  };
  GEO.set(shape, g);
  return g;
}

const f1 = (n: number) => (Math.round(n * 10) / 10).toString();
const side = (g: VaseGeom, k: number, from: number, to: number, inner = false, n = 28) =>
  Array.from({ length: n + 1 }, (_, i) => {
    const y = from + ((to - from) * i) / n;
    return [CX + k * (inner ? g.rIn(y) : g.r(y)), y] as [number, number];
  });
const pl = (pts: [number, number][], first = "M") => pts.map((q, i) => `${i ? "L" : first}${f1(q[0])} ${f1(q[1])}`).join(" ");
/** Силуэт вазы: левый бок вниз, передний край дна, правый бок вверх, задний край горла */
export function vaseOutline(g: VaseGeom) {
  const rb = g.r(g.y1), r0 = g.r(g.y0);
  return `${pl(side(g, -1, g.y0, g.y1))} A${f1(rb)} ${f1(rb * E)} 0 0 0 ${f1(CX + rb)} ${f1(g.y1)} ${pl(side(g, 1, g.y1, g.y0), "L")} A${f1(r0)} ${f1(r0 * E)} 0 0 0 ${f1(CX - r0)} ${f1(g.y0)} Z`;
}
/** Вода: от поверхности (задняя половина эллипса) до толстого дна */
export function waterOutline(g: VaseGeom) {
  const rw = g.rIn(g.yw), rb = g.rIn(g.yb);
  return `${pl(side(g, -1, g.yw, g.yb, true, 20))} A${f1(rb)} ${f1(rb * E)} 0 0 0 ${f1(CX + rb)} ${f1(g.yb)} ${pl(side(g, 1, g.yb, g.yw, true, 20), "L")} A${f1(rw)} ${f1(rw * E)} 0 0 0 ${f1(CX - rw)} ${f1(g.yw)} Z`;
}
/** Блик-полоса вдоль профиля между долями радиуса k1..k2 */
function streak(g: VaseGeom, k1: number, k2: number, from: number, to: number) {
  const n = 24;
  const a = Array.from({ length: n + 1 }, (_, i) => {
    const y = from + ((to - from) * i) / n;
    return [CX + k1 * g.r(y), y] as [number, number];
  });
  const b = Array.from({ length: n + 1 }, (_, i) => {
    const y = to - ((to - from) * i) / n;
    return [CX + k2 * g.r(y), y] as [number, number];
  });
  return `${pl(a)} ${pl(b, "L")} Z`;
}

export type VaseIds = { body: string; hl: string; shadow: string; caustic: string; water: string; table: string; clipW: string; clipA: string };

/** Фон сцены: поверхность стола, тень и каустика от стекла */
export function VaseGround({ g, ids }: { g: VaseGeom; ids: VaseIds }) {
  const rb = g.r(g.y1);
  return (
    <g data-vase={g.shape}>
      <defs>
        <radialGradient id={ids.table} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#cdbb9f" stopOpacity="0.42" />
          <stop offset="0.7" stopColor="#cdbb9f" stopOpacity="0.16" />
          <stop offset="1" stopColor="#cdbb9f" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={ids.shadow}>
          <stop offset="0" stopColor="#3b3328" stopOpacity="0.3" />
          <stop offset="0.6" stopColor="#3b3328" stopOpacity="0.12" />
          <stop offset="1" stopColor="#3b3328" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={ids.caustic}>
          <stop offset="0" stopColor="#fffbe8" stopOpacity="0.85" />
          <stop offset="1" stopColor="#fffbe8" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={CX} cy={g.y1 + 2} rx={196} ry={16} fill={`url(#${ids.table})`} />
      <ellipse cx={CX + rb * 0.55} cy={g.y1 + 1.5} rx={rb * 1.75} ry={rb * E * 1.25 + 3} fill={`url(#${ids.shadow})`} />
      <ellipse cx={CX + rb * 0.7} cy={g.y1 + 2} rx={rb * 0.6} ry={rb * E * 0.45 + 1.2} fill={`url(#${ids.caustic})`} />
    </g>
  );
}

/** Задняя стенка и задний край горлышка (за стеблями) */
export function VaseBack({ g, ids }: { g: VaseGeom; ids: VaseIds }) {
  const r0 = g.r(g.y0), ri = g.rIn(g.y0);
  return (
    <g>
      <defs>
        <clipPath id={ids.clipW}>
          <path d={waterOutline(g)} />
        </clipPath>
        <clipPath id={ids.clipA}>
          <rect x={0} y={0} width={400} height={g.yw + 0.5} />
        </clipPath>
        <linearGradient id={ids.water} x1={0} y1={0} x2={1} y2={0}>
          <stop offset="0" stopColor="#7fa79c" stopOpacity="0.34" />
          <stop offset="0.22" stopColor="#c4ddd6" stopOpacity="0.1" />
          <stop offset="0.72" stopColor="#c4ddd6" stopOpacity="0.07" />
          <stop offset="1" stopColor="#7fa79c" stopOpacity="0.36" />
        </linearGradient>
      </defs>
      <path d={vaseOutline(g)} fill="rgba(226,236,233,0.18)" />
      <path d={`M${f1(CX - r0)} ${g.y0} A${f1(r0)} ${f1(r0 * E)} 0 0 1 ${f1(CX + r0)} ${g.y0}`} fill="none" stroke="rgba(92,112,108,0.32)" strokeWidth={1.2} />
      <path d={`M${f1(CX - ri)} ${g.y0} A${f1(ri)} ${f1(ri * E)} 0 0 1 ${f1(CX + ri)} ${g.y0}`} fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={0.9} />
    </g>
  );
}

/** Вода поверх подводной части стеблей: тонировка, поверхность с мениском */
export function VaseWater({ g, ids }: { g: VaseGeom; ids: VaseIds }) {
  const rw = g.rIn(g.yw);
  return (
    <g>
      <path d={waterOutline(g)} fill={`url(#${ids.water})`} />
      <ellipse cx={CX} cy={g.yw} rx={rw} ry={rw * E} fill="rgba(236,246,243,0.22)" stroke="rgba(255,255,255,0.8)" strokeWidth={0.9} />
      <path d={`M${f1(CX - rw)} ${f1(g.yw)} A${f1(rw)} ${f1(rw * E)} 0 0 0 ${f1(CX + rw)} ${f1(g.yw)}`} fill="none" stroke="rgba(96,128,120,0.35)" strokeWidth={1.1} />
    </g>
  );
}

/** Передняя стенка: френель по краям, блики, толстое дно, передний край горлышка */
export function VaseFront({ g, ids }: { g: VaseGeom; ids: VaseIds }) {
  const r0 = g.r(g.y0), ri0 = g.rIn(g.y0), rb = g.r(g.y1), rib = g.rIn(g.yb);
  const top = g.y0 + r0 * E * 0.6;
  return (
    <g style={{ pointerEvents: "none" }}>
      <defs>
        <linearGradient id={ids.body} x1={0} y1={0} x2={1} y2={0}>
          <stop offset="0" stopColor="#5f7a76" stopOpacity="0.34" />
          <stop offset="0.06" stopColor="#ffffff" stopOpacity="0.34" />
          <stop offset="0.16" stopColor="#ffffff" stopOpacity="0.07" />
          <stop offset="0.5" stopColor="#ffffff" stopOpacity="0.02" />
          <stop offset="0.84" stopColor="#ffffff" stopOpacity="0.06" />
          <stop offset="0.94" stopColor="#ffffff" stopOpacity="0.26" />
          <stop offset="1" stopColor="#5f7a76" stopOpacity="0.36" />
        </linearGradient>
        <linearGradient id={ids.hl} x1={0} y1={0} x2={0} y2={1}>
          <stop offset="0" stopColor="#fff" stopOpacity="0.15" />
          <stop offset="0.25" stopColor="#fff" stopOpacity="0.8" />
          <stop offset="0.75" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#fff" stopOpacity="0.05" />
        </linearGradient>
      </defs>
      <path d={vaseOutline(g)} fill={`url(#${ids.body})`} />
      {/* толщина стенок */}
      <path d={pl(side(g, -1, top, g.yb, true))} fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth={1.1} />
      <path d={pl(side(g, 1, top, g.yb, true))} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth={1.1} />
      {/* блики окна слева и отражение справа */}
      <path d={streak(g, -0.74, -0.56, top + 4, g.yb - 2)} fill={`url(#${ids.hl})`} />
      <path d={streak(g, -0.46, -0.41, top + 10, g.yb - 10)} fill={`url(#${ids.hl})`} opacity={0.6} />
      <path d={streak(g, 0.62, 0.7, top + 8, g.yb - 6)} fill={`url(#${ids.hl})`} opacity={0.42} />
      {/* толстое стеклянное дно */}
      <path d={`M${f1(CX - rib)} ${f1(g.yb)} A${f1(rib)} ${f1(rib * E)} 0 0 0 ${f1(CX + rib)} ${f1(g.yb)} L${f1(CX + rb)} ${f1(g.y1)} A${f1(rb)} ${f1(rb * E)} 0 0 1 ${f1(CX - rb)} ${f1(g.y1)} Z`} fill="rgba(214,232,228,0.42)" />
      <ellipse cx={CX} cy={g.yb} rx={rib} ry={rib * E} fill="rgba(240,248,246,0.25)" stroke="rgba(255,255,255,0.75)" strokeWidth={0.9} />
      <path d={`M${f1(CX - rb * 0.86)} ${f1(g.y1 - 3)} A${f1(rb * 0.86)} ${f1(rb * E * 0.8)} 0 0 0 ${f1(CX + rb * 0.86)} ${f1(g.y1 - 3)}`} fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={1.2} />
      {/* контур и передний край горлышка */}
      <path d={vaseOutline(g)} fill="none" stroke="rgba(74,96,92,0.42)" strokeWidth={0.9} />
      <path d={`M${f1(CX - r0)} ${g.y0} A${f1(r0)} ${f1(r0 * E)} 0 0 0 ${f1(CX + r0)} ${g.y0}`} fill="none" stroke="rgba(74,96,92,0.45)" strokeWidth={1} />
      <path d={`M${f1(CX - ri0)} ${f1(g.y0 + 0.6)} A${f1(ri0)} ${f1(ri0 * E)} 0 0 0 ${f1(CX + ri0)} ${f1(g.y0 + 0.6)}`} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth={1.6} />
    </g>
  );
}

/** Подводные стебли: продолжение линии стебля за точкой перевязки, внутри стенок; в воде — с увеличением 1.12 */
export function vaseStems(g: VaseGeom, heads: { x: number; y: number; w: number; key: string }[], extra: number, seed = 1) {
  const yEnd = g.yb - 3;
  const list = [...heads];
  for (let k = 0; k < extra; k++) {
    const t = Math.sin((k + seed) * 91.7) * 0.5 + 0.5;
    list.push({ x: CX + (t - 0.5) * 220, y: 170 + Math.cos(k * 3.1) * 60, w: 1.6, key: `e${k}` });
  }
  const n = Math.max(1, list.length);
  return list.map((s, i) => {
    const slope = (CX - s.x) / Math.max(20, g.bind - s.y);
    const x0 = CX + (i - (n - 1) / 2) * Math.min(1.5, 30 / n);
    const ym = (g.bind + yEnd) / 2;
    const lim = (y: number, x: number) => {
      const r = g.rIn(y) - 2.5 - s.w / 2;
      return Math.max(CX - r, Math.min(CX + r, x));
    };
    const xm = lim(ym, x0 + slope * (ym - g.bind) * 0.9);
    const xe = lim(yEnd, x0 + slope * (yEnd - g.bind) * 0.75 + Math.sin(i * 2.3) * 3);
    return { key: s.key, d: `M${f1(x0)} ${g.bind} Q${f1(xm)} ${f1(ym)} ${f1(xe)} ${f1(yEnd)}`, w: s.w, xe, ye: yEnd };
  });
}
