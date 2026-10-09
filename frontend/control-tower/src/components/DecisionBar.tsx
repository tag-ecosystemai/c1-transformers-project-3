import { useState } from "react";
import { api } from "../api/client";
import type { Decision } from "../api/types";

export default function DecisionBar({ shipmentId }: { shipmentId: string }) {
  const [done, setDone] = useState<Decision | null>(null);
  const [note, setNote] = useState("");
  const send = async (d: Decision) => { await api.decide(shipmentId, d, note); setDone(d); };
  if (done) return <p className="muted">Decision logged: {done}</p>;
  return (
    <div className="decide">
      <input placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} />
      <button onClick={() => send("approve")}>Approve recommendation</button>
      <button className="ghost" onClick={() => send("override")}>Override</button>
      <button className="ghost" onClick={() => send("dismiss")}>Dismiss</button>
    </div>
  );
}
