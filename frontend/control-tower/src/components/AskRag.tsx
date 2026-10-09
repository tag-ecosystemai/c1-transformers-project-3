import { useState } from "react";
import { api } from "../api/client";
// Procedure / supplier Q&A against the RAG index, scoped to the selected shipment.
export default function AskRag({ shipmentId }: { shipmentId?: string }) {
  const [q, setQ] = useState(""); const [a, setA] = useState<{ answer: string; sources: string[] } | null>(null);
  return (
    <div className="ask">
      <form onSubmit={async e => { e.preventDefault(); setA(await api.ask(q, shipmentId)); }}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about expedite procedure, supplier terms..." />
      </form>
      {a && <p>{a.answer} <small className="muted">{a.sources.join(" · ")}</small></p>}
    </div>
  );
}
