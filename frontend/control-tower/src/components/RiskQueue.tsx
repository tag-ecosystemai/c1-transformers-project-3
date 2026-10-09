import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Shipment } from "../api/types";

// Priority = risk x urgency (delay longer than inventory cover means stockout).
const gap = (s: Shipment) => s.predicted_delay_days - s.inventory_cover_days;
const priority = (s: Shipment) => s.risk_score * (1 + Math.max(0, gap(s)) / 3);

export default function RiskQueue({ selected, onSelect }: { selected?: string; onSelect: (s: Shipment) => void }) {
  const { data = [], isLoading, isError, error } = useQuery({ queryKey: ["shipments"], queryFn: api.shipments, retry: false, refetchInterval: 30_000 });
  const rows = [...data].sort((a, b) => priority(b) - priority(a));
  return (
    <aside className="queue">
      <h2>Watchlist</h2>
      {isLoading && <p className="muted">Scanning shipments...</p>}
      {isError && <p className="warn">Can't reach the API: {String(error)}</p>}
      {rows.map(s => (
        <button key={s.id} className={`row ${s.risk_level} ${selected === s.id ? "on" : ""}`} onClick={() => onSelect(s)}>
          <span className="id">{s.id}</span>
          <span className="meta">{s.supplier} · ETA {s.eta}</span>
          <span className="bar"><i style={{ width: `${s.risk_score * 100}%` }} /></span>
          <span className="meta">+{s.predicted_delay_days}d late · {s.inventory_cover_days}d cover
            {gap(s) > 0 && <b className="warn"> · stockout risk</b>}</span>
        </button>
      ))}
    </aside>
  );
}
