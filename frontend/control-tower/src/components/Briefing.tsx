import ReactMarkdown from "react-markdown";
import type { Investigation } from "../api/types";

export default function Briefing({ r }: { r: Investigation }) {
  return (
    <section className="briefing">
      <h3>Likely cause</h3><p>{r.cause}</p>
      <h3>Business impact</h3><p>{r.impact}</p>
      <h3>Alternatives</h3>
      <ul>{r.alternatives.map(a => <li key={a.name}><b>{a.name}</b> · {a.lead_time_days}d {a.note && `· ${a.note}`}</li>)}</ul>
      <h3>Recommendation</h3><p className="reco">{r.recommendation}</p>
      <details><summary>Full briefing</summary><ReactMarkdown>{r.briefing_md}</ReactMarkdown></details>
      <details><summary>Grounding ({r.citations.length})</summary>
        {r.citations.map((c, i) => <blockquote key={i}><cite>{c.source}</cite> {c.snippet}</blockquote>)}
      </details>
    </section>
  );
}
