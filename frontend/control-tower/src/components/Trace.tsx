import type { AgentEvent } from "../api/types";
export default function Trace({ events }: { events: AgentEvent[] }) {
  return (
    <ol className="trace">
      {events.map((e, i) => e.type === "final" ? null : (
        <li key={i} className={e.type}>
          {e.type === "tool_call" ? <><code>{e.tool}</code>({Object.values(e.args).join(", ")})</> : <span>{e.summary}</span>}
        </li>
      ))}
    </ol>
  );
}
