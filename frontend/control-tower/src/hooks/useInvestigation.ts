import { useCallback, useRef, useState } from "react";
import { api } from "../api/client";
import { streamInvestigation } from "../api/stream";
import type { AgentEvent, Investigation, SignalKey } from "../api/types";

export type SignalState = Record<SignalKey, "idle" | "running" | "done">;
const idle: SignalState = { shipment: "idle", weather: "idle", inventory: "idle", supplier: "idle", news: "idle" };
// Which signal a tool feeds, so the ring lights up on tool_call before the result arrives.
const TOOL_SIGNAL: Record<string, SignalKey> = {
  get_shipment_status: "shipment", get_weather: "weather", get_inventory: "inventory",
  find_alternative_supplier: "supplier", search_news: "news",
};

export function useInvestigation() {
  const [signals, setSignals] = useState<SignalState>(idle);
  const [trace, setTrace] = useState<AgentEvent[]>([]);
  const [report, setReport] = useState<Investigation | null>(null);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const reset = useCallback(() => { abort.current?.abort(); setSignals(idle); setTrace([]); setReport(null); setRunning(false); }, []);

  const start = useCallback(async (shipmentId: string) => {
    reset(); abort.current = new AbortController(); setRunning(true);
    try {
      await streamInvestigation(api.investigateUrl, shipmentId, e => {
        setTrace(t => [...t, e]);
        if (e.type === "tool_call" && TOOL_SIGNAL[e.tool]) setSignals(s => ({ ...s, [TOOL_SIGNAL[e.tool]]: "running" }));
        if (e.type === "tool_result") setSignals(s => ({ ...s, [e.signal]: "done" }));
        if (e.type === "final") setReport(e.report);
      }, abort.current.signal);
    } finally { setRunning(false); }
  }, [reset]);
  return { signals, trace, report, running, start, reset };
}
