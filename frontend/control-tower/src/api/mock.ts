import type { AgentEvent, Shipment, Investigation } from "./types";

export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false"; // mock is the default
const wait = (ms: number) => new Promise(r => setTimeout(r, ms));

export const mockShipments: Shipment[] = [
  { id: "SHP1042", sku: "SKU-4471", supplier: "Swift Freight", origin: "Mombasa", destination: "Kigali", eta: "Oct 3", risk_score: 0.87, risk_level: "high", predicted_delay_days: 2, inventory_cover_days: 3 },
  { id: "SHP1077", sku: "SKU-2210", supplier: "Nova Textiles", origin: "Dar es Salaam", destination: "Kigali", eta: "Oct 6", risk_score: 0.58, risk_level: "medium", predicted_delay_days: 1, inventory_cover_days: 6 },
  { id: "SHP1103", sku: "SKU-9034", supplier: "Apex Components", origin: "Lagos", destination: "Kigali", eta: "Oct 8", risk_score: 0.44, risk_level: "medium", predicted_delay_days: 1, inventory_cover_days: 9 },
  { id: "SHP0991", sku: "SKU-1180", supplier: "Greenline", origin: "Nairobi", destination: "Kigali", eta: "Oct 5", risk_score: 0.14, risk_level: "low", predicted_delay_days: 0, inventory_cover_days: 12 },
];

const report: Investigation = {
  cause: "Severe weather at Mombasa is suspending berth work and compounding port congestion.",
  impact: "Inventory cover is about 3 days. A 2 day delay leaves almost no buffer and risks a stockout.",
  alternatives: [
    { kind: "supplier", name: "Supplier C", lead_time_days: 2, note: "expedite available" },
    { kind: "route", name: "Reroute via Dar es Salaam", lead_time_days: 3, note: "+1 day vs plan" },
  ],
  recommendation: "Consider expediting Supplier C to close the projected inventory gap.",
  citations: [
    { source: "expedite-procedure.pdf", snippet: "Expedites above tier 2 need ops manager sign-off." },
    { source: "supplier-c-terms.md", snippet: "Rush orders ship within 24h, 15% surcharge." },
  ],
  briefing_md: "## Disruption briefing\n\n**SHP1042** is at high risk of arriving 2 days late.\n\n- Cause: cyclone warning at Mombasa\n- Impact: stockout in about 3 days\n- Action: expedite Supplier C",
};

const script: [string, Record<string, unknown>, string, string][] = [
  ["get_shipment_status", { id: "SHP1042" }, "shipment", "ETA slipped Oct 3 to Oct 5, port dwell up 36h"],
  ["get_weather", { place: "Mombasa" }, "weather", "Cyclone warning, winds 62 km/h, berth work suspended"],
  ["get_inventory", { sku: "SKU-4471" }, "inventory", "3.0 days of cover at current burn rate"],
  ["find_alternative_supplier", { sku: "SKU-4471" }, "supplier", "Supplier C can deliver in 2 days"],
  ["search_news", { q: "Mombasa port" }, "news", "Congestion reported, 2 vessels waiting at anchor"],
];

export async function mockStream(onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
  for (const [tool, args, signalKey, summary] of script) {
    if (signal?.aborted) return;
    onEvent({ type: "tool_call", tool, args }); await wait(700);
    onEvent({ type: "tool_result", tool, signal: signalKey as never, summary }); await wait(400);
  }
  onEvent({ type: "final", report });
}
