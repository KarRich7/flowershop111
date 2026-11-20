"use client";
// Редактор границ зон доставки (админка): перетаскивание вершин, новый контур, перерисовка.
import { useEffect, useRef, useState } from "react";
import { useShop } from "@/components/ShopProvider";
import type { Ring } from "@/lib/types";
import { loadYmaps, zoneStyle, type YMaps } from "./ymaps";

export type EditZone = { id: number; name: string; color: string; polygons: Ring[]; is_active?: boolean };

export function ZoneEditor({ zones, editingId, onSave, onCancel, busy }: { zones: EditZone[]; editingId: number | null; onSave: (rings: Ring[]) => void; onCancel: () => void; busy?: boolean }) {
  const shop = useShop();
  const box = useRef<HTMLDivElement | null>(null);
  const ym = useRef<{ api: YMaps; map: YMaps; layer: YMaps; editable: YMaps[] } | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = useState("");
  const [drawing, setDrawing] = useState(false);

  useEffect(() => {
    let dead = false;
    loadYmaps(shop.maps?.yandex_api_key || "")
      .then((api) => {
        if (dead || !box.current) return;
        const map = new api.Map(box.current, { center: shop.maps?.center || [57.98644, 56.11818], zoom: 11, controls: ["zoomControl"] }, { suppressMapOpenBlock: true });
        const layer = new api.GeoObjectCollection();
        map.geoObjects.add(layer);
        ym.current = { api, map, layer, editable: [] };
        setState("ready");
      })
      .catch((e) => {
        if (!dead) {
          setErr(e.message || "Карта не загрузилась");
          setState("error");
        }
      });
    return () => {
      dead = true;
      ym.current?.map.destroy();
      ym.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = ym.current;
    if (!m || state !== "ready") return;
    m.editable.forEach((pl) => pl.editor?.stopEditing?.());
    m.layer.removeAll();
    m.editable = [];
    setDrawing(false);
    zones.forEach((z) => {
      const edit = z.id === editingId;
      z.polygons.forEach((ring) => {
        const style = zoneStyle(z.color, edit);
        const pl = new m.api.Polygon([ring], { hintContent: z.name }, { ...style, fillOpacity: edit ? 0.3 : editingId ? 0.06 : z.is_active === false ? 0.04 : 0.16, strokeOpacity: editingId && !edit ? 0.35 : 0.85 });
        m.layer.add(pl);
        if (edit) {
          m.editable.push(pl);
          pl.editor.startEditing();
        }
      });
    });
    if (editingId) {
      const target = zones.find((z) => z.id === editingId);
      if (target && !target.polygons.length) {
        // у новой зоны ещё нет границ — сразу включаем рисование
        const pl = new m.api.Polygon([], {}, { ...zoneStyle(target.color, true), fillOpacity: 0.3, editorDrawingCursor: "crosshair" });
        m.layer.add(pl);
        m.editable.push(pl);
        pl.editor.startDrawing();
        setDrawing(true);
      }
      if (target?.polygons.length) {
        const b = m.layer.getBounds?.();
        const own = m.editable[0]?.geometry.getBounds();
        if (own) m.map.setBounds(own, { checkZoomRange: true, zoomMargin: 40 });
        else if (b) m.map.setBounds(b, { checkZoomRange: true });
      }
    }
  }, [zones, editingId, state]);

  const addContour = () => {
    const m = ym.current;
    const z = zones.find((x) => x.id === editingId);
    if (!m || !z) return;
    const pl = new m.api.Polygon([], {}, { ...zoneStyle(z.color, true), fillOpacity: 0.3, editorDrawingCursor: "crosshair" });
    m.layer.add(pl);
    m.editable.push(pl);
    pl.editor.startDrawing();
    setDrawing(true);
  };
  const redraw = () => {
    const m = ym.current;
    if (!m) return;
    m.editable.forEach((pl) => {
      pl.editor.stopEditing();
      m.layer.remove(pl);
    });
    m.editable = [];
    addContour();
  };
  const save = () => {
    const m = ym.current;
    if (!m) return;
    const rings: Ring[] = m.editable
      .map((pl) => (pl.geometry.getCoordinates()[0] || []) as Ring)
      .map((r) => r.map((p) => [Number(p[0].toFixed(6)), Number(p[1].toFixed(6))] as [number, number]))
      .filter((r) => r.length >= 3);
    onSave(rings);
  };

  const editing = zones.find((z) => z.id === editingId);
  return (
    <div>
      {editing ? (
        <div className="row-between" style={{ marginBottom: 8 }}>
          <span className="small">
            Границы зоны <b style={{ fontWeight: 600 }}>{editing.name}</b>: перетаскивайте вершины, клик по вершине открывает меню удаления
            {drawing ? ". Кликайте по карте, чтобы поставить точки нового контура, двойной клик завершает" : ""}
          </span>
          <span className="row" style={{ gap: 8 }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={addContour} disabled={state !== "ready"}>Добавить контур</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={redraw} disabled={state !== "ready"}>Нарисовать заново</button>
            <button type="button" className="btn btn-quiet btn-sm" onClick={onCancel}>Отмена</button>
            <button type="button" className="btn btn-sm" onClick={save} disabled={state !== "ready" || busy}>{busy ? "Сохраняем…" : "Сохранить границы"}</button>
          </span>
        </div>
      ) : (
        <p className="hint" style={{ margin: "0 0 8px" }}>«Границы» — изменить контур района на карте.</p>
      )}
      <div className="map-box lg" style={{ marginTop: 0 }}>
        <div ref={box} className="map-fill" />
        {state === "loading" && <div className="map-msg">Загружаем карту…</div>}
        {state === "error" && <div className="map-msg">{err}. Границы можно задать через API: PATCH /admin/delivery-zones/id, поле polygons</div>}
      </div>
    </div>
  );
}
