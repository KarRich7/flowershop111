"use client";
import { XIcon } from "@/components/Icons";
import { useState } from "react";
import { ErrorBox, Loading, Modal, PageTop } from "@/components/admin/ui";
import { useToast } from "@/components/Toast";
import { adminApi, useAdmin } from "@/lib/admin";
import { ApiError } from "@/lib/api";
import { money } from "@/lib/format";

type Recipe = {
  id: number; bouquet_item_id: number; name: string; product_id: number | null; price: number | null; cost: number;
  can_assemble: number; assembled_available: number; made_to_order: boolean; image: string | null;
  components: { item_id: number; name: string; category: string; quantity: number; available: number }[];
};
type Item = { id: number; name: string; category: string; category_label: string; available: number };

export default function RecipesPage() {
  const toast = useToast();
  const { data, error, reload } = useAdmin<Recipe[]>("/recipes");
  const [assemble, setAssemble] = useState<Recipe | null>(null);
  const [edit, setEdit] = useState<Recipe | null>(null);
  return (
    <>
      <PageTop title="Сборка букетов" />
      <ErrorBox text={error} />
      {!data ? <Loading /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th></th><th>Букет</th><th>Рецептура</th><th className="num">Себестоимость</th><th className="num">Цена</th><th className="num">Готовых</th><th className="num">Можно собрать</th><th></th></tr></thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <td style={{ width: 56 }}>{r.image ? <img className="thumb" src={r.image} alt="" /> : null}</td>
                  <td><b>{r.name}</b>{r.made_to_order && <div className="tiny muted">под заказ</div>}</td>
                  <td className="small">
                    {r.components.map((c) => (
                      <div key={c.item_id} style={{ color: c.available < c.quantity ? "var(--red)" : undefined }}>
                        {c.name} × {c.quantity} <span className="muted">(есть {c.available})</span>
                      </div>
                    ))}
                    {!r.components.length && <span className="muted">не задана</span>}
                  </td>
                  <td className="num small">{money(r.cost)}</td>
                  <td className="num small">{money(r.price)}{r.price && r.cost ? <div className="tiny muted">наценка {Math.round(((r.price - r.cost) / r.cost) * 100)}%</div> : null}</td>
                  <td className="num">{r.assembled_available}</td>
                  <td className="num"><span className={`badge ${r.can_assemble ? "green" : "gray"}`}>{r.can_assemble}</span></td>
                  <td>
                    <div className="row" style={{ flexWrap: "nowrap" }}>
                      <button className="btn btn-xs" disabled={!r.can_assemble} onClick={() => setAssemble(r)}>Собрать</button>
                      <button className="btn btn-xs btn-ghost" onClick={() => setEdit(r)}>Состав</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {assemble && <AssembleModal r={assemble} onClose={() => setAssemble(null)} onDone={() => { reload(); setAssemble(null); }} />}
      {edit && <EditRecipe r={edit} onClose={() => setEdit(null)} onDone={() => { reload(); setEdit(null); toast("Рецептура сохранена", "ok"); }} />}
    </>
  );
}

function AssembleModal({ r, onClose, onDone }: { r: Recipe; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [n, setN] = useState(1);
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`Собрать «${r.name}»`} onClose={onClose}>
      <p className="small">Будет списано:</p>
      <ul className="small">
        {r.components.map((c) => <li key={c.item_id}>{c.name}: {c.quantity * n} (есть {c.available})</li>)}
      </ul>
      <div className="row">
        <div className="qty">
          <button className="icon-btn" onClick={() => setN(Math.max(1, n - 1))} aria-label="Меньше">−</button>
          <span>{n}</span>
          <button className="icon-btn" disabled={n >= r.can_assemble} onClick={() => setN(n + 1)} aria-label="Больше">+</button>
        </div>
        <span className="muted small">максимум {r.can_assemble}</span>
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 14 }}>
        <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
        <button
          className="btn"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await adminApi(`/recipes/${r.id}/assemble`, { body: { count: n } });
              toast(`Собрано: ${n} шт. «${r.name}»`, "ok");
              onDone();
            } catch (e) {
              toast(e instanceof ApiError ? e.message : "Ошибка", "err");
              setBusy(false);
            }
          }}
        >
          Собрать {n} шт.
        </button>
      </div>
    </Modal>
  );
}

function EditRecipe({ r, onClose, onDone }: { r: Recipe; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { data: items } = useAdmin<Item[]>("/inventory");
  const [rows, setRows] = useState(r.components.map((c) => ({ item_id: String(c.item_id), quantity: String(c.quantity) })));
  const [busy, setBusy] = useState(false);
  const materials = (items || []).filter((i) => ["flower", "greenery", "packaging", "ribbon", "card"].includes(i.category));
  return (
    <Modal title={`Рецептура «${r.name}»`} onClose={onClose} wide>
      {!items ? <Loading /> : (
        <>
          {rows.map((row, k) => (
            <div key={k} className="row" style={{ marginBottom: 8, flexWrap: "nowrap" }}>
              <select className="select" style={{ flex: 3 }} value={row.item_id} onChange={(e) => setRows(rows.map((x, i) => (i === k ? { ...x, item_id: e.target.value } : x)))}>
                <option value="">Материал</option>
                {materials.map((m) => <option key={m.id} value={m.id}>{m.category_label}: {m.name}</option>)}
              </select>
              <input className="input" style={{ flex: 1 }} type="number" min={1} value={row.quantity} onChange={(e) => setRows(rows.map((x, i) => (i === k ? { ...x, quantity: e.target.value } : x)))} />
              <button className="icon-btn" onClick={() => setRows(rows.filter((_, i) => i !== k))} aria-label="Удалить"><XIcon /></button>
            </div>
          ))}
          <button className="btn btn-sm btn-ghost" onClick={() => setRows([...rows, { item_id: "", quantity: "1" }])}>+ Материал</button>
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 14 }}>
            <button className="btn btn-ghost" onClick={onClose}>Отмена</button>
            <button
              className="btn"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await adminApi(`/recipes/${r.id}`, { method: "PUT", body: { components: rows.filter((x) => x.item_id && Number(x.quantity) > 0).map((x) => ({ item_id: Number(x.item_id), quantity: Number(x.quantity) })) } });
                  onDone();
                } catch (e) {
                  toast(e instanceof ApiError ? e.message : "Ошибка", "err");
                  setBusy(false);
                }
              }}
            >
              Сохранить
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
