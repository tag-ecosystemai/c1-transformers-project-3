import type { SignalState } from "../hooks/useInvestigation";
import type { SignalKey } from "../api/types";

const ORDER: SignalKey[] = ["shipment", "weather", "inventory", "supplier", "news"];
const R = 120, C = 170;

// Signature view: five signals orbit the shipment and light up as the agent calls each tool.
export default function SignalRing({ id, signals }: { id: string; signals: SignalState }) {
  return (
    <svg viewBox="0 0 340 340" className="ring" role="img" aria-label="Agent signal status">
      <circle cx={C} cy={C} r={R} className="orbit" />
      {ORDER.map((k, i) => {
        const a = (i / ORDER.length) * Math.PI * 2 - Math.PI / 2;
        const x = C + R * Math.cos(a), y = C + R * Math.sin(a);
        return (
          <g key={k} className={`node ${signals[k]}`}>
            <line x1={C} y1={C} x2={x} y2={y} />
            <circle cx={x} cy={y} r={18} />
            <text x={x} y={y + 34} textAnchor="middle">{k}</text>
          </g>
        );
      })}
      <circle cx={C} cy={C} r={34} className="core" />
      <text x={C} y={C + 4} textAnchor="middle" className="coreText">{id}</text>
    </svg>
  );
}
