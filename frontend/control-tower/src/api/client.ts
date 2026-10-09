import type { Shipment, Decision } from "./types";
import { USE_MOCK, mockShipments } from "./mock";
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
const post = (path: string, body: unknown) =>
  fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  shipments: () => USE_MOCK ? Promise.resolve(mockShipments) : fetch(`${BASE}/shipments?status=in_transit`).then(r => j<Shipment[]>(r)),
  ask: (q: string, shipment_id?: string) => USE_MOCK
    ? Promise.resolve({ answer: "Tier 2 expedites need ops manager sign-off; Supplier C ships rush orders in 24h.", sources: ["expedite-procedure.pdf"] })
    : post("/rag/ask", { q, shipment_id }).then(r => j<{ answer: string; sources: string[] }>(r)),
  decide: (shipment_id: string, decision: Decision, note?: string) => USE_MOCK
    ? Promise.resolve({ ok: true as const })
    : post("/decisions", { shipment_id, decision, note }).then(r => j<{ ok: true }>(r)),
  investigateUrl: `${BASE}/agent/investigate`,
};
