"use client";
// Адрес доставки: поиск по кнопке или Enter, выбор точки на карте, проверка зоны.
import { useMemo, useRef, useState } from "react";
import { CheckIcon, PinIcon, SearchIcon, XIcon } from "@/components/Icons";
import { ZoneMap } from "@/components/maps/ZoneMap";
import { ApiError, request } from "@/lib/api";
import { money } from "@/lib/format";
import type { GeoAddress, Zone, ZoneShort } from "@/lib/types";

export type AddressValue = {
  query: string;
  lat: number | null;
  lon: number | null;
  token: string | null;
  tokenFor: string;
  zone: ZoneShort | null;
  house: boolean;
  checked: boolean;
};
export const EMPTY_ADDRESS: AddressValue = { query: "", lat: null, lon: null, token: null, tokenFor: "", zone: null, house: false, checked: false };

type Reverse = { result: GeoAddress | null; zone: ZoneShort | null; geocoder: boolean };

/** Запасной поиск адреса по точке прямо в браузере через уже загруженную карту Яндекса
 *  (если серверный геокодер не нашёл дом или недоступен). Зону всё равно определяет сервер. */
async function addressFromMap(lat: number, lon: number): Promise<{ address: string; house: boolean } | null> {
  const api = typeof window !== "undefined" ? window.ymaps : undefined;
  if (!api?.geocode) return null;
  try {
    const res = await api.geocode([lat, lon], { kind: "house", results: 1 });
    const o = res?.geoObjects?.get(0);
    if (!o) return null;
    const street: string = o.getThoroughfare?.() || "";
    const house: string = o.getPremiseNumber?.() || "";
    const locality: string = (o.getLocalities?.() || [])[0] || "";
    const address = [locality, street, house].filter(Boolean).join(", ") || o.getAddressLine?.() || "";
    const [olat, olon] = o.geometry.getCoordinates();
    const dist = Math.hypot((olat - lat) * 111_000, (olon - lon) * 111_000 * Math.cos((lat * Math.PI) / 180));
    return address ? { address, house: !!house && dist <= 120 } : null;
  } catch {
    return null;
  }
}

export function AddressPicker({ zones, value, onChange, itemsTotal }: { zones: Zone[]; value: AddressValue; onChange: (v: AddressValue) => void; itemsTotal: number }) {
  const [results, setResults] = useState<GeoAddress[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [focus, setFocus] = useState(0);
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");
  const seq = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;
  const mapZones = useMemo(() => zones.map((z) => ({ id: z.id, name: z.name, color: z.color, polygons: z.polygons })), [zones]);

  async function search() {
    const q = value.query.trim();
    if (q.length < 3) {
      setMsg("Введите улицу и номер дома");
      return;
    }
    setBusy(true);
    setMsg("");
    const my = ++seq.current;
    try {
      const r = await request<{ results: GeoAddress[] }>(`/delivery/geocode?q=${encodeURIComponent(q)}`);
      if (my !== seq.current) return;
      setResults(r.results);
      if (!r.results.length) setMsg("Ничего не нашли. Проверьте улицу и дом или отметьте точку на карте");
    } catch (e) {
      if (my !== seq.current) return;
      setResults(null);
      setMsg(e instanceof ApiError && e.code === "geocoder_unavailable" ? "Поиск адреса временно недоступен. Отметьте точку на карте" : e instanceof ApiError ? e.message : "Не удалось найти адрес");
    } finally {
      if (my === seq.current) setBusy(false);
    }
  }

  function choose(r: GeoAddress) {
    setResults(null);
    setMsg(r.house ? "" : "Уточните номер дома: без него курьер не найдёт адрес");
    onChange({ query: r.address, lat: r.lat, lon: r.lon, token: r.token, tokenFor: r.address, zone: r.zone, house: r.house, checked: true });
    setFocus((f) => f + 1);
  }

  async function pick(lat: number, lon: number) {
    const my = ++seq.current;
    setResults(null);
    setMsg("");
    onChange({ ...valueRef.current, lat, lon, token: null, tokenFor: "", checked: false });
    setMsg("Определяем адрес…");
    try {
      const r = await request<Reverse>(`/delivery/reverse?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`);
      if (my !== seq.current) return;
      // сервер не нашёл дом — пробуем геокодер карты прямо в браузере
      const alt = !r.result || !r.result.house ? await addressFromMap(lat, lon) : null;
      if (my !== seq.current) return;
      const cur = valueRef.current;
      if (r.result && (r.result.house || !alt?.house)) {
        onChange({ query: r.result.address, lat, lon, token: r.result.token, tokenFor: r.result.address, zone: r.zone, house: r.result.house, checked: true });
        setMsg(r.result.house ? "" : /\d/.test(r.result.address) ? "Метка стоит не на доме — проверьте номер дома" : "Допишите номер дома: без него курьер не найдёт адрес");
      } else if (alt) {
        onChange({ query: alt.address, lat, lon, token: null, tokenFor: "", zone: r.zone, house: alt.house, checked: true });
        setMsg(alt.house ? "" : "Допишите номер дома: без него курьер не найдёт адрес");
      } else {
        onChange({ ...cur, lat, lon, token: null, tokenFor: "", zone: r.zone, house: false, checked: true });
        setMsg(r.geocoder ? "Не нашли адрес в этой точке. Впишите улицу и дом" : "Поиск адреса недоступен. Впишите улицу и дом, точку на карте сохраним");
      }
    } catch (e) {
      if (my !== seq.current) return;
      setMsg(e instanceof ApiError ? e.message : "Не удалось проверить точку");
    }
  }

  const z = value.zone;
  const point: [number, number] | null = value.lat != null && value.lon != null ? [value.lat, value.lon] : null;
  const cost = z ? (z.free_from && itemsTotal >= z.free_from ? 0 : z.price) : null;

  return (
    <div>
      <label className="field">
        <span>Адрес доставки *</span>
        <div className="addr-search">
          <input
            className="input"
            value={value.query}
            placeholder="Например: Красавинская 8 или Пермь, Ленина 50"
            autoComplete="street-address"
            onChange={(e) => onChange({ ...value, query: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                search();
              }
            }}
          />
          <button type="button" className="btn btn-ghost" onClick={search} disabled={busy}>
            <SearchIcon size={16} /> {busy ? "Ищем…" : "Найти"}
          </button>
        </div>
      </label>
      {results && results.length > 0 && (
        <div className="geo-results" role="listbox" aria-label="Найденные адреса">
          {results.map((r, i) => (
            <button type="button" key={`${r.lat}-${r.lon}-${i}`} onClick={() => choose(r)} role="option" aria-selected={false}>
              <span>
                {r.address}
                {!r.house && <span className="muted small"> · без номера дома</span>}
              </span>
              <span className="small muted nowrap">{r.zone ? r.zone.name : "вне зоны"}</span>
            </button>
          ))}
        </div>
      )}
      {msg && <div className="hint" style={{ marginTop: 8 }}>{msg}</div>}

      <ZoneMap zones={mapZones} point={point} focusKey={focus} onPick={pick} activeZone={z?.id ?? null} onState={setMapState} />
      {mapState !== "error" && <div className="hint" style={{ marginTop: 8 }}>Нажмите на карту или перетащите метку, адрес подставится сам</div>}

      {point && value.checked && (
        z ? (
          <div className="zone-status ok">
            <CheckIcon />
            <div>
              <b>Доставляем: {z.name}</b>
              <div className="small">
                {cost === 0 ? "Доставка бесплатно" : `Доставка ${money(z.price)}`}
                {z.free_from && cost !== 0 ? `, бесплатно от ${money(z.free_from)}` : ""}
              </div>
            </div>
          </div>
        ) : (
          <div className="zone-status bad">
            <XIcon size={16} />
            <div>
              <b>Сюда мы не доставляем</b>
              <div className="small">Выберите адрес внутри цветных зон на карте или оформите самовывоз</div>
            </div>
          </div>
        )
      )}
      {!point && (
        <div className="zone-status">
          <PinIcon size={16} />
          <div className="small">Найдите адрес или отметьте точку на карте, чтобы рассчитать доставку</div>
        </div>
      )}
      <div className="zone-legend" aria-label="Зоны доставки">
        {zones.map((zz) => (
          <span key={zz.id}>
            <i style={{ background: zz.color }} />
            {zz.name} <span className="muted num">{money(zz.price)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function addressProblem(v: AddressValue): string | null {
  if (v.lat == null || v.lon == null) return "Отметьте адрес доставки на карте или найдите его через поиск";
  if (!v.checked) return "Проверяем адрес…";
  if (!v.zone) return "По этому адресу мы не доставляем. Выберите адрес в зоне доставки или самовывоз";
  if (!v.query.trim()) return "Укажите адрес доставки";
  return null;
}
