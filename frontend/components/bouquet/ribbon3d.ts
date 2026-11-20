// Объёмная лента для эскиза букета. Никаких зависимостей: петли банта, хвосты, узелок и обвязка
// задаются параметрическими поверхностями, освещаются как атлас / шёлк / органза / джут
// (рассеянный свет + анизотропный блеск вдоль нитей) и растеризуются с z-буфером в RGBA.
// PNG отдаёт маршрут /ribbon/<ключ>.png (app/ribbon/[key]/route.ts), эскиз кладёт его в SVG как <image>.
// Геометрия детерминирована, поэтому размер и положение картинки SVG знает без рендера (ribbonBox).

export type RibbonKind = "satin" | "silk" | "twine" | "organza";
/** wrap — бант на перевязке упаковки, box — лента вокруг шляпной коробки, stem — обмотка стеблей без упаковки с бантом,
 *  vase — перевязка букета в вазе с бантом, tie — технический шпагат без банта (лента не выбрана) */
export type RibbonScene = "wrap" | "box" | "stem" | "vase" | "tie";
export type RibbonSpec = { scene: RibbonScene; kind: RibbonKind; color: string; w?: number };

type V3 = [number, number, number];
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: V3): V3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const lin = (...xs: [V3, number][]): V3 => xs.reduce<V3>((s, [v, k]) => add(s, mul(v, k)), [0, 0, 0]);
const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const smooth = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const PI = Math.PI;

// ------------------------------------------------------------------ поверхности
type Surf = {
  nu: number;
  nv: number;
  /** u ∈ [0,1] — вдоль ленты, v ∈ [-1,1] — поперёк */
  P: (u: number, v: number) => V3;
  /** точка «внутри» — по ней лицевая (блестящая) сторона разворачивается наружу */
  inside: V3;
  /** длина вдоль u (для волокон джута) */
  len?: number;
  /** срез конца: u_max(v) */
  uEnd?: (v: number) => number;
  /** затенение складками и соседними деталями */
  ao?: (p: V3, u: number, v: number) => number;
  /** шпагат: v — угол вокруг жгута, края нет */
  tube?: boolean;
};

type Opt = { kind: RibbonKind; hw: number };

/** Петля банта: каплевидная осевая в наклонённой плоскости, у узла лента собрана в складки, по ширине чуть выпуклая */
function loop(sx: number, o: Opt & { L: number; H: number; tilt: number; rise: number; back: number; droop: number; at: V3; soft?: number }): Surf {
  const A = norm([sx * Math.cos(o.rise), -Math.sin(o.rise), -o.back]);
  const B0: V3 = [0, -Math.sin(o.tilt), -Math.cos(o.tilt)];
  const B = norm(sub(B0, mul(A, dot(A, B0))));
  const W = norm(cross(A, B));
  const f0 = 0.55;
  const C = (f: number): [number, number] => [(o.L * (1 - Math.cos(f))) / 2, o.H * Math.sin(f) * Math.pow((1 - Math.cos(f)) / 2, 0.55)];
  const soft = o.soft || 0;
  return {
    nu: 72,
    nv: 12,
    inside: add(o.at, mul(A, o.L * 0.55)),
    P: (u, v) => {
      const f = f0 + u * (2 * PI - 2 * f0);
      const [a, b] = C(f);
      const [a2, b2] = C(f + 0.01);
      const tin = norm(lin([A, a2 - a], [B, b2 - b]));
      const nin = norm(sub(lin([A, -(b2 - b)], [B, a2 - a]), [0, 0, 0]));
      const r = a / o.L;
      const hw = o.hw * (0.46 + 0.54 * smooth(0.02, 0.5, r));
      const gather = 1 - smooth(0.05, 0.45, r);
      const pleat = gather * 1.25 * Math.sin(v * PI * 2.6 + sx * 0.8) + (1 - v * v) * (1.1 + gather * 0.4);
      const wob = soft * Math.sin(u * 13 + v * 1.7) * smooth(0.2, 0.6, r);
      void tin;
      let p = lin([A, a], [B, b], [W, v * hw], [nin, pleat + wob]);
      p = add(p, [0, o.droop * Math.sin(PI * Math.min(1, r)) + o.droop * 0.4 * r, -1.2 * r * r * o.L * 0.08]);
      return add(o.at, p);
    },
    ao: (p, u) => {
      const r = Math.abs(u - 0.5) * 2;
      const d = Math.hypot(p[0] - o.at[0], p[1] - o.at[1]);
      return (1 - 0.5 * Math.exp(-((d / 9) ** 2))) * (0.92 + 0.08 * (1 - r));
    },
  };
}

/** Хвост: свисает и расходится, слегка закручивается (видна изнанка), конец — «ласточкин хвост» или косой срез */
function tail(sx: number, o: Opt & { len: number; spread: number; twist: number; at: V3; cut: "dove" | "diag"; wave?: number }): Surf {
  const wave = o.wave || 0;
  const C = (u: number): V3 =>
    add(o.at, [
      sx * (1 + o.spread * (0.45 * u + 0.55 * u * u) + 3.2 * Math.sin(PI * u) + wave * Math.sin(PI * 2.2 * u)),
      o.len * u - 2.5 * Math.sin(PI * u * 0.9),
      -1.5 - 5 * u + 3 * Math.sin(PI * u),
    ]);
  const notch = 8.5 / o.len;
  return {
    nu: 64,
    nv: 10,
    len: o.len,
    inside: add(C(0.4), [0, 0, -60]),
    uEnd: o.cut === "dove" ? (v) => 1 - notch * (1 - Math.abs(v)) : (v) => 1 - notch * 1.3 * ((1 + sx * v) / 2),
    P: (u, v) => {
      const c = C(u);
      const T = norm(sub(C(u + 0.004), C(u - 0.004)));
      const W0 = norm(cross(T, [0, 0, 1]));
      const th = sx * (0.35 + o.twist * Math.sin(PI * Math.min(1, u * 1.05))) + wave * 0.25 * Math.sin(PI * 3 * u);
      const Wv = add(mul(W0, Math.cos(th)), mul(cross(T, W0), Math.sin(th)));
      const N = norm(cross(T, Wv));
      const hw = o.hw * (0.5 + 0.5 * smooth(0, 0.24, u));
      const gather = 1 - smooth(0, 0.26, u);
      const pleat = gather * 1.1 * Math.sin(v * PI * 2.4 + sx) + 0.5 * (1 - v * v);
      return lin([c, 1], [Wv, v * hw], [N, pleat]);
    },
    ao: (p) => 1 - 0.55 * Math.exp(-(((p[1] - o.at[1]) / 11) ** 2)) * Math.exp(-(((p[0] - o.at[0]) / 12) ** 2)),
  };
}

/** Узелок: короткий кусок ленты, обёрнутый вокруг собранной середины, с продольными заломами */
function knot(o: Opt & { ry: number; rz: number; at: V3 }): Surf {
  const hk = o.hw * 0.78;
  return {
    nu: 36,
    nv: 14,
    inside: o.at,
    P: (u, v) => {
      const t = (u - 0.5) * PI * 1.18;
      const rad: V3 = [0, -Math.sin(t), Math.cos(t)];
      const crease = 0.55 * Math.sin(v * PI * 2.2 + 0.6) * (0.6 + 0.4 * Math.cos(t)) + 0.9 * (1 - v * v);
      const p: V3 = [v * hk * (1 + 0.1 * Math.cos(t)), -o.ry * Math.sin(t), o.rz * Math.cos(t)];
      return add(o.at, add(p, mul(norm([0, rad[1] / o.ry, rad[2] / o.rz]), crease)));
    },
    ao: (_p, u) => 0.82 + 0.18 * Math.sin(PI * u),
  };
}

/** Лента вокруг конуса упаковки (передняя половина): чуть сужается книзу, бока выше середины — вид сверху */
function band(o: Opt & { R: number; Rz: number; sag: number; taper: number; y: number; dz?: number; tilt?: number; span?: number }): Surf {
  const span = o.span || 1;
  return {
    nu: 72,
    nv: 10,
    inside: [0, o.y, -o.Rz],
    P: (u, v) => {
      const t = (u - 0.5) * PI * span;
      const k = 1 - (v * o.hw * o.taper) / o.R;
      const bulge = 0.25 * (1 - v * v);
      return [
        (o.R + bulge) * k * Math.sin(t),
        o.y + v * o.hw - o.sag * (1 - Math.cos(t)) + (o.tilt || 0) * Math.sin(t),
        (o.Rz + bulge) * k * Math.cos(t) - o.Rz + (o.dz || 0),
      ];
    },
    ao: (p) => 0.9 + 0.1 * smooth(0, 6, Math.abs(p[0])),
  };
}

/** Жгут шпагата вдоль кривой */
function tube(C: (u: number) => V3, r: number | ((u: number) => number), len: number, nu = 60): Surf {
  const R = typeof r === "number" ? () => r : r;
  return {
    nu,
    nv: 10,
    len,
    tube: true,
    inside: C(0.5),
    P: (u, v) => {
      const c = C(u);
      const T = norm(sub(C(u + 0.003), C(u - 0.003)));
      let Bn = cross(T, [0, 0, 1]);
      if (Math.hypot(...Bn) < 1e-3) Bn = cross(T, [0, 1, 0]);
      Bn = norm(Bn);
      const N = cross(Bn, T);
      const a = v * PI;
      return lin([c, 1], [N, R(u) * Math.cos(a)], [Bn, R(u) * Math.sin(a)]);
    },
  };
}

// ------------------------------------------------------------------ сцены
function satinBow(kind: RibbonKind, at: V3, s: number, hw: number, back = 0.32, tailK = 1): Surf[] {
  const silk = kind === "silk";
  const o = { kind, hw: hw * s };
  const lp = (sx: number) =>
    loop(sx, { ...o, L: (silk ? 50 : 47) * s, H: (silk ? 15.5 : 19) * s, tilt: silk ? 0.74 : 0.86, rise: silk ? 0.08 : 0.12, back, droop: (silk ? 4.5 : 2.5) * s, at: add(at, [sx * 1.5 * s, 0, 1]), soft: silk ? 0.9 : 0 });
  const tl = (sx: number) =>
    tail(sx, { ...o, len: (silk ? 92 : 80) * s * tailK, spread: (silk ? 22 : 18) * s, twist: silk ? 0.72 : 0.62, at: add(at, [sx * 1.5 * s, 3 * s, 0]), cut: silk ? "diag" : "dove", wave: silk ? 2.2 * s : 0 });
  return [lp(-1), lp(1), tl(-1), tl(1), knot({ ...o, ry: 7.4 * s, rz: 5.4 * s, at: add(at, [0, 0.5 * s, 1.5 * s]) })];
}

function twineWraps(R: number, Rz: number, sag: number, ys: number[], r: number): Surf[] {
  return ys.map((y, k) =>
    tube((u) => {
      const t = (u - 0.5) * PI;
      return [R * Math.sin(t), y - sag * (1 - Math.cos(t)) + (k % 2 ? 1 : -1) * 0.8 * Math.sin(t), Rz * Math.cos(t) - Rz + r];
    }, r, R * PI, 70),
  );
}
function twineBow(at: V3, s: number, r: number): Surf[] {
  const out: Surf[] = [];
  for (const sx of [-1, 1]) {
    const A = norm([sx, -0.42, -0.25]);
    const B = norm(sub([0, -0.55, -0.83], mul(A, dot(A, [0, -0.55, -0.83]))));
    const L = 17 * s, H = 7.5 * s;
    out.push(
      tube((u) => {
        const f = 0.35 + u * (2 * PI - 0.7);
        return add(add(at, [sx * 1.2, 0, 1.5]), lin([A, (L * (1 - Math.cos(f))) / 2], [B, H * Math.sin(f) * Math.pow((1 - Math.cos(f)) / 2, 0.5)]));
      }, r, L * 2.4, 60),
    );
    const end = (u: number): V3 => add(at, [sx * (1.5 + 7 * u * s + 3 * Math.sin(PI * u) * s), (3 + 36 * u) * s, 1.5 - 3 * u]);
    out.push(tube(end, (u) => r * (1 - 0.15 * smooth(0.85, 1, u)), 40 * s, 50));
    // распушённый кончик: несколько тонких волокон
    for (let k = 0; k < 4; k++) {
      const e0 = end(0.92);
      const dir: V3 = [sx * (0.6 + 0.5 * k) - 0.8, 4.5 + k * 0.6, 0.3 * k - 0.5];
      out.push(tube((u) => add(e0, [dir[0] * u + 0.6 * Math.sin(u * 3 + k), dir[1] * u, dir[2] * u]), 0.32, 6, 8));
    }
  }
  // узелок
  out.push(tube((u) => {
    const t = (u - 0.5) * PI * 1.6;
    return add(at, [0.6 * Math.sin(t * 2), -3.2 * Math.sin(t), 2.8 * Math.cos(t) + 1.5]);
  }, r * 1.15, 10, 24));
  return out;
}

/** Набор поверхностей сцены и масштаб растра (пикселей на единицу SVG) */
function scene(spec: RibbonSpec): { surfs: Surf[]; S: number } {
  const { kind, scene: sc } = spec;
  const twine = kind === "twine";
  const hw = kind === "silk" ? 8.5 : kind === "organza" ? 8 : 7.2;
  const o = { kind, hw };
  if (sc === "box") {
    // лента по боку шляпной коробки + бант по центру (якорь — середина ленты спереди)
    if (twine) return { surfs: [...twineWraps(152, 152, 38, [-2.6, 0, 2.6], 1.2), ...twineBow([0, 0, 2], 1.1, 1.2)], S: 2.5 };
    return { surfs: [band({ ...o, hw: 8, R: 152, Rz: 152, sag: 38, taper: 0, y: 0 }), ...satinBow(kind, [0, 0, 9], 1, hw, 0.3, 0.62)], S: 2.5 };
  }
  if (sc === "wrap") {
    if (twine) return { surfs: [...twineWraps(28.5, 22, 4.6, [-3.4, -0.9, 1.6, 4.1], 1.15), ...twineBow([0, 0, 2], 1, 1.15)], S: 3 };
    return { surfs: [band({ ...o, hw: hw * 0.8, R: 28.5, Rz: 22, sag: 4.6, taper: 0.22, y: 0.8 }), ...satinBow(kind, [0, 0, 1.5], 1, hw)], S: 3 };
  }
  // обмотка стеблей: якорь — центр обмотки, w — полуширина пучка
  const w = Math.max(6, Math.min(24, spec.w || 12));
  const turns = sc === "vase" ? 2 : sc === "tie" ? 3 : 4;
  if (twine || sc === "tie") {
    const ys = Array.from({ length: turns + 1 }, (_, k) => (k - turns / 2) * 2.5);
    const wraps = twineWraps(w + 1, (w + 1) * 0.82, 1.6, ys, 1.1);
    return { surfs: sc === "tie" ? wraps : [...wraps, ...twineBow([0, -1, 2], 0.85, 1.1)], S: 3 };
  }
  // атлас / шёлк / органза: несколько витков вокруг пучка и бант спереди — как на упаковке, только меньше
  const surfs: Surf[] = [];
  const n = sc === "vase" ? 2 : 3;
  const step = hw * 1.45;
  for (let k = 0; k < n; k++) {
    const y = (k - (n - 1) / 2) * step;
    surfs.push(band({ ...o, R: w + 0.6 + k * 0.35, Rz: (w + 0.6) * 0.82 + k * 0.35, sag: 1.8, taper: 0.06, y, dz: k * 0.35, tilt: 1.6 }));
  }
  const s = Math.max(0.55, Math.min(0.8, (w + 10) / 30));
  surfs.push(...satinBow(kind, [0, 0, 1.6 + n * 0.35], s, hw, 0.32, 0.85));
  return { surfs, S: 3 };
}

// ------------------------------------------------------------------ свет и материалы
const Lk = norm([-0.42, -0.62, 0.66]);
const L2 = norm([0.62, -0.12, 0.78]);
const Hk = norm(add(Lk, [0, 0, 1]));
const toLin = (x: number) => Math.pow(x, 2.2);
function hexLin(hex: string): V3 {
  const h = /^#?([0-9a-f]{6})$/i.exec(hex.trim())?.[1] || "c9918f";
  return [0, 2, 4].map((i) => toLin(parseInt(h.slice(i, i + 2), 16) / 255)) as V3;
}
const hash = (x: number, y: number) => {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
};

type Mat = { kind: RibbonKind; base: V3; sheen: V3 };
function material(kind: RibbonKind, color: string): Mat {
  const base = hexLin(color);
  const w: V3 = [1, 1, 1];
  const k = kind === "satin" ? 0.42 : kind === "silk" ? 0.55 : 0.3;
  return { kind, base, sheen: lin([w, 1 - k], [base, k]) };
}

/** Освещение фрагмента → [r, g, b, a] в линейном пространстве */
function shade(m: Mat, nx: number, ny: number, nz: number, tx: number, ty: number, tz: number, e: number, ao: number, fu: number, fv: number, px: number, py: number): [number, number, number, number] {
  let n: V3 = norm([nx, ny, nz]);
  let back = false;
  if (n[2] < 0) {
    n = [-n[0], -n[1], -n[2]];
    back = true;
  }
  let t: V3 = [tx, ty, tz];
  t = norm(sub(t, mul(n, dot(n, t))));
  const b = cross(n, t);
  const ndl = dot(n, Lk);
  const ndv = Math.max(0, n[2]);
  const diff = 0.3 + 0.78 * clamp01((ndl + 0.28) / 1.28) + 0.2 * Math.max(0, dot(n, L2));
  let base = m.base;
  let a = 1;
  let ks = 0, ax = 0.2, ay = 0.5, soft = 0, fres = 0;
  if (m.kind === "twine") {
    const stripe = 0.5 + 0.5 * Math.cos(2 * PI * (fu / 1.9 + fv * 1.5));
    const fib = 0.64 + 0.46 * Math.pow(stripe, 0.8) + (hash(Math.floor(px * 1.7), Math.floor(py * 1.7)) - 0.5) * 0.16;
    base = mul(base, fib);
    soft = 0.05;
  } else {
    if (m.kind === "satin") [ks, ax, ay, soft, fres] = back ? [0.05, 0.3, 0.6, 0.02, 0.05] : [0.85, 0.12, 0.55, 0.1, 0.22];
    else if (m.kind === "silk") [ks, ax, ay, soft, fres] = back ? [0.08, 0.3, 0.6, 0.03, 0.12] : [0.36, 0.24, 0.62, 0.09, 0.3];
    else [ks, ax, ay, soft, fres] = [0.5, 0.18, 0.5, 0.08, 0.35];
    if (back) base = mul(base, m.kind === "satin" ? 0.82 : 0.9);
    // кромка ленты: плотнее и чуть темнее
    if (e > 0.9) base = mul(base, 0.86 + 0.14 * (1 - smooth(0.9, 0.97, e)));
    if (m.kind === "organza") a = 0.42 + 0.42 * smooth(0.86, 0.95, e);
    if (m.kind === "silk" && e > 0.96) a = 1 - (hash(Math.floor(px), Math.floor(py)) > 0.6 ? 0.5 : 0) * smooth(0.96, 1, e);
  }
  let col = mul(base, diff * ao);
  const hn = dot(Hk, n);
  if (ks > 0 && hn > 0) {
    const ht = dot(Hk, t), hb = dot(Hk, b);
    const sp = ks * Math.exp(-((ht / ax) ** 2 + (hb / ay) ** 2) / (hn * hn)) * Math.sqrt(clamp01(ndl + 0.1));
    col = add(col, mul(m.sheen, sp * (0.5 + 0.5 * ao)));
  }
  if (soft > 0 && hn > 0) col = add(col, mul(m.sheen, soft * Math.pow(hn, 6) * ao));
  if (fres > 0) col = add(col, mul(m.sheen, fres * Math.pow(1 - ndv, 3) * ao * 0.6));
  return [col[0], col[1], col[2], a];
}

// ------------------------------------------------------------------ растр
type Raster = { rgba: Uint8ClampedArray; w: number; h: number };
type Box = { x: number; y: number; w: number; h: number };

const VCACHE = new Map<string, { verts: Float32Array[]; box: Box; S: number; surfs: Surf[] }>();
function hex6(c: string) {
  const h = (c || "").trim().replace(/^#/, "").toLowerCase();
  if (/^[0-9a-f]{6}$/.test(h)) return h;
  if (/^[0-9a-f]{3}$/.test(h)) return h.split("").map((x) => x + x).join("");
  return "c9918f";
}
/** Ключ картинки: он же имя файла в /ribbon/<ключ>.png */
export const ribbonKey = (s: RibbonSpec) => `${s.scene}-${s.kind}-${hex6(s.color)}-${Math.max(0, Math.min(99, Math.round(s.w || 0)))}-v3`;

/** Сетка вершин: x, y, z, nx, ny, nz, tx, ty, tz, edge, ao, fu, fv */
function build(spec: RibbonSpec) {
  const key = `${spec.scene}-${spec.kind}-${Math.round(spec.w || 0)}`;
  const hit = VCACHE.get(key);
  if (hit) return hit;
  const { surfs, S } = scene(spec);
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  const verts = surfs.map((sf) => {
    const { nu, nv } = sf;
    const out = new Float32Array((nu + 1) * (nv + 1) * 13);
    const ue = sf.uEnd || (() => 1);
    const at = (u: number, v: number) => sf.P(u * ue(v), v);
    // ориентация: лицевая сторона — от точки inside
    const pm = at(0.5, 0);
    const nm = cross(sub(at(0.502, 0), at(0.498, 0)), sub(at(0.5, 0.01), at(0.5, -0.01)));
    const sg = dot(nm, sub(pm, sf.inside)) < 0 ? -1 : 1;
    let k = 0;
    for (let i = 0; i <= nu; i++) {
      for (let j = 0; j <= nv; j++) {
        const u = i / nu, v = -1 + (2 * j) / nv;
        const p = at(u, v);
        const du = sub(at(Math.min(1, u + 0.002), v), at(Math.max(0, u - 0.002), v));
        const dv = sub(at(u, Math.min(1, v + 0.01)), at(u, Math.max(-1, v - 0.01)));
        const n = norm(mul(cross(du, dv), sg));
        const t = norm(du);
        const ao = sf.ao ? sf.ao(p, u, v) : 1;
        out.set([p[0], p[1], p[2], n[0], n[1], n[2], t[0], t[1], t[2], sf.tube ? 0 : Math.abs(v), ao, u * (sf.len || 0), v], k);
        k += 13;
        if (p[0] < x0) x0 = p[0];
        if (p[0] > x1) x1 = p[0];
        if (p[1] < y0) y0 = p[1];
        if (p[1] > y1) y1 = p[1];
      }
    }
    return out;
  });
  const box = { x: Math.floor(x0 - 3), y: Math.floor(y0 - 3), w: 0, h: 0 };
  box.w = Math.ceil(x1 + 3) - box.x;
  box.h = Math.ceil(y1 + 3) - box.y;
  const r = { verts, box, S, surfs };
  VCACHE.set(key, r);
  return r;
}

/** Положение картинки ленты относительно точки привязки (единицы SVG) */
export function ribbonBox(spec: RibbonSpec): Box {
  return build(spec).box;
}

/** RGBA-растр сцены (суперсэмплинг 2×2, два слоя глубины — для полупрозрачной органзы) */
export function renderRibbon(spec: RibbonSpec): Raster {
  const { verts, box, S, surfs } = build(spec);
  const m = material(spec.kind, spec.color);
  const SS = 2;
  const sc = S * SS;
  const W = Math.round(box.w * S), H = Math.round(box.h * S);
  const w2 = W * SS, h2 = H * SS;
  const z1 = new Float32Array(w2 * h2).fill(-1e9);
  const z2 = new Float32Array(w2 * h2).fill(-1e9);
  const c1 = new Float32Array(w2 * h2 * 4);
  const c2 = new Float32Array(w2 * h2 * 4);
  const A = new Float32Array(13 * 3);
  const tri = (va: Float32Array, ia: number, ib: number, ic: number) => {
    A.set(va.subarray(ia, ia + 13), 0);
    A.set(va.subarray(ib, ib + 13), 13);
    A.set(va.subarray(ic, ic + 13), 26);
    const X0 = (A[0] - box.x) * sc, Y0 = (A[1] - box.y) * sc;
    const X1 = (A[13] - box.x) * sc, Y1 = (A[14] - box.y) * sc;
    const X2 = (A[26] - box.x) * sc, Y2 = (A[27] - box.y) * sc;
    const area = (X1 - X0) * (Y2 - Y0) - (X2 - X0) * (Y1 - Y0);
    if (Math.abs(area) < 1e-6) return;
    const minX = Math.max(0, Math.floor(Math.min(X0, X1, X2))), maxX = Math.min(w2 - 1, Math.ceil(Math.max(X0, X1, X2)));
    const minY = Math.max(0, Math.floor(Math.min(Y0, Y1, Y2))), maxY = Math.min(h2 - 1, Math.ceil(Math.max(Y0, Y1, Y2)));
    const ia2 = 1 / area;
    for (let py = minY; py <= maxY; py++) {
      const cy = py + 0.5;
      for (let px = minX; px <= maxX; px++) {
        const cx = px + 0.5;
        const b0 = ((X1 - cx) * (Y2 - cy) - (X2 - cx) * (Y1 - cy)) * ia2;
        const b1 = ((X2 - cx) * (Y0 - cy) - (X0 - cx) * (Y2 - cy)) * ia2;
        const b2 = 1 - b0 - b1;
        if (b0 < -1e-5 || b1 < -1e-5 || b2 < -1e-5) continue;
        const z = b0 * A[2] + b1 * A[15] + b2 * A[28];
        const q = py * w2 + px;
        if (z <= z2[q]) continue;
        const I = (k: number) => b0 * A[k] + b1 * A[13 + k] + b2 * A[26 + k];
        const c = shade(m, I(3), I(4), I(5), I(6), I(7), I(8), I(9), I(10), I(11), I(12), px / SS, py / SS);
        if (z > z1[q]) {
          z2[q] = z1[q];
          c2.set(c1.subarray(q * 4, q * 4 + 4), q * 4);
          z1[q] = z;
          c1.set(c, q * 4);
        } else {
          z2[q] = z;
          c2.set(c, q * 4);
        }
      }
    }
  };
  surfs.forEach((sf, s) => {
    const va = verts[s];
    const row = sf.nv + 1;
    for (let i = 0; i < sf.nu; i++)
      for (let j = 0; j < sf.nv; j++) {
        const a = (i * row + j) * 13, b = ((i + 1) * row + j) * 13, c = ((i + 1) * row + j + 1) * 13, d = (i * row + j + 1) * 13;
        tri(va, a, b, c);
        tri(va, a, c, d);
      }
  });
  const rgba = new Uint8ClampedArray(W * H * 4);
  const tone = (x: number) => {
    if (x > 0.82) x = 0.82 + 0.18 * (1 - Math.exp(-(x - 0.82) / 0.18));
    return Math.pow(Math.max(0, x), 1 / 2.2);
  };
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      let r = 0, g = 0, bb = 0, al = 0;
      for (let dy = 0; dy < SS; dy++)
        for (let dx = 0; dx < SS; dx++) {
          const q = (y * SS + dy) * w2 + x * SS + dx;
          const a1 = z1[q] > -1e8 ? c1[q * 4 + 3] : 0;
          const a2 = z2[q] > -1e8 ? c2[q * 4 + 3] * (1 - a1) : 0;
          if (a1 + a2 <= 0) continue;
          r += tone(c1[q * 4]) * a1 + tone(c2[q * 4]) * a2;
          g += tone(c1[q * 4 + 1]) * a1 + tone(c2[q * 4 + 1]) * a2;
          bb += tone(c1[q * 4 + 2]) * a1 + tone(c2[q * 4 + 2]) * a2;
          al += a1 + a2;
        }
      const o = (y * W + x) * 4;
      if (al > 0) {
        rgba[o] = (r / al) * 255;
        rgba[o + 1] = (g / al) * 255;
        rgba[o + 2] = (bb / al) * 255;
        rgba[o + 3] = (al / (SS * SS)) * 255;
      }
    }
  return { rgba, w: W, h: H };
}

/** Разбор ключа из URL: wrap-satin-c9918f-0-v2 */
export function parseRibbonKey(key: string): RibbonSpec | null {
  const m = /^(wrap|box|stem|vase|tie)-(satin|silk|twine|organza)-([0-9a-f]{6})-(\d{1,2})-v\d+$/.exec(key);
  if (!m) return null;
  return { scene: m[1] as RibbonScene, kind: m[2] as RibbonKind, color: `#${m[3]}`, w: Number(m[4]) };
}
