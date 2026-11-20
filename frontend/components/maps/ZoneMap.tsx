"use client";
// Карта с зонами доставки: полигоны зон, метка адреса (перетаскивается), клик по карте выбирает точку.
import { useEffect, useRef, useState } from "react";
import { useShop } from "@/components/ShopProvider";
import type { Ring } from "@/lib/types";
import { loadYmaps, zoneStyle, type YMaps } from "./ymaps";

export type MapZone = { id: number; name: string; color: string; polygons: Ring[]; price?: number };

type Props = {
  zones: MapZone[];
  point?: [number, number] | null;
  /** при изменении — приблизить карту к точке */
  focusKey?: number;
  onPick?: (lat: number, lon: number) => void;
  shop?: [number, number] | null;
  shopLabel?: string;
  activeZone?: number | null;
  zoom?: number;
  className?: string;
  onState?: (s: "loading" | "ready" | "error") => void;
};

export function ZoneMap(p: Props) {
  const shop = useShop();
  const box = useRef<HTMLDivElement | null>(null);
  const ym = useRef<{ api: YMaps; map: YMaps; zones: YMaps; mark: YMaps | null } | null>(null);
  const pickRef = useRef(p.onPick);
  pickRef.current = p.onPick;
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = useState("");
  const pickable = !!p.onPick;

  useEffect(() => {
    let dead = false;
    loadYmaps(shop.maps?.yandex_api_key || "")
      .then((api) => {
        if (dead || !box.current) return;
        const center = p.point || p.shop || shop.maps?.center || [57.98644, 56.11818];
        const map = new api.Map(box.current, { center, zoom: p.zoom ?? (p.point ? 14 : 11), controls: ["zoomControl"] }, { suppressMapOpenBlock: true, yandexMapDisablePoiInteractivity: true });
        map.behaviors.disable("scrollZoom");
        const zones = new api.GeoObjectCollection();
        map.geoObjects.add(zones);
        const click = (e: YMaps) => {
          const c = e.get("coords");
          if (c && pickRef.current) pickRef.current(c[0], c[1]);
        };
        if (p.onPick) {
          map.events.add("click", click);
          zones.events.add("click", click);
        }
        if (p.shop) {
          map.geoObjects.add(new api.Placemark(p.shop, { hintContent: p.shopLabel || "Магазин", balloonContent: p.shopLabel || "" }, { preset: "islands#darkGreenDotIcon" }));
        }
        ym.current = { api, map, zones, mark: null };
        setState("ready");
        p.onState?.("ready");
      })
      .catch((e) => {
        if (dead) return;
        setErr(e.message || "Карта не загрузилась");
        setState("error");
        p.onState?.("error");
      });
    return () => {
      dead = true;
      ym.current?.map.destroy();
      ym.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // зоны
  useEffect(() => {
    const m = ym.current;
    if (!m || state !== "ready") return;
    m.zones.removeAll();
    p.zones.forEach((z) =>
      z.polygons.forEach((ring) => m.zones.add(new m.api.Polygon([ring], { hintContent: z.name }, { ...zoneStyle(z.color, p.activeZone === z.id), cursor: pickable ? "pointer" : "grab" }))),
    );
  }, [p.zones, p.activeZone, state, pickable]);

  // метка адреса
  useEffect(() => {
    const m = ym.current;
    if (!m || state !== "ready") return;
    if (!p.point) {
      if (m.mark) m.map.geoObjects.remove(m.mark);
      m.mark = null;
      return;
    }
    if (!m.mark) {
      m.mark = new m.api.Placemark(p.point, {}, { preset: "islands#redDotIcon", draggable: pickable });
      m.mark.events.add("dragend", () => {
        const c = m.mark.geometry.getCoordinates();
        pickRef.current?.(c[0], c[1]);
      });
      m.map.geoObjects.add(m.mark);
    } else m.mark.geometry.setCoordinates(p.point);
  }, [p.point, state, pickable]);

  useEffect(() => {
    const m = ym.current;
    if (!m || state !== "ready" || !p.point || !p.focusKey) return;
    m.map.setCenter(p.point, Math.max(m.map.getZoom(), 15), { duration: 300 });
  }, [p.focusKey, state, p.point]);

  return (
    <div className={`map-box ${p.className || ""}`}>
      <div ref={box} className="map-fill" />
      {state === "loading" && <div className="map-msg">Загружаем карту…</div>}
      {state === "error" && <div className="map-msg">{err}. Найдите адрес через поиск, зона определится автоматически</div>}
    </div>
  );
}
