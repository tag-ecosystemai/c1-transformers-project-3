import type { AgentEvent } from "./types";
import { USE_MOCK, mockStream } from "./mock";
// POST + SSE (EventSource cannot POST). Backend emits `data: {json}\n\n` per agent step.
export async function streamInvestigation(
  url: string, shipmentId: string, onEvent: (e: AgentEvent) => void, signal?: AbortSignal
) {
  if (USE_MOCK) return mockStream(onEvent, signal);
  const res = await fetch(url, { method: "POST", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shipment_id: shipmentId }) });
  if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n"); buf = frames.pop() ?? "";
    for (const f of frames) if (f.startsWith("data: ")) onEvent(JSON.parse(f.slice(6)));
  }
}
