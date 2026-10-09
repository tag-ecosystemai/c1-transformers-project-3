import { useState } from "react";
import type { Shipment } from "./api/types";
import { useInvestigation } from "./hooks/useInvestigation";
import RiskQueue from "./components/RiskQueue";
import SignalRing from "./components/SignalRing";
import Trace from "./components/Trace";
import Briefing from "./components/Briefing";
import DecisionBar from "./components/DecisionBar";
import AskRag from "./components/AskRag";

export default function App() {
  const [sel, setSel] = useState<Shipment>();
  const inv = useInvestigation();
  return (
    <div className="shell">
      <header><h1>Control Tower</h1><span className="muted">Detect · Investigate · Recommend · Decide</span></header>
      <RiskQueue selected={sel?.id} onSelect={s => { setSel(s); inv.reset(); }} />
      <main className="stage">
        {!sel ? <p className="muted">Select a shipment from the watchlist.</p> : <>
          <div className="head">
            <div><h2>{sel.id}</h2><p className="muted">{sel.origin} → {sel.destination} · {sel.sku}</p></div>
            <button disabled={inv.running} onClick={() => inv.start(sel.id)}>{inv.running ? "Investigating..." : "Investigate"}</button>
          </div>
          <SignalRing id={sel.id} signals={inv.signals} />
          <Trace events={inv.trace} />
          <AskRag shipmentId={sel.id} />
        </>}
      </main>
      <section className="side">
        {inv.report && sel ? <><Briefing r={inv.report} /><DecisionBar shipmentId={sel.id} /></>
          : <p className="muted">The briefing appears here once the investigation completes.</p>}
      </section>
    </div>
  );
}
