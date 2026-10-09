// Contract with the FastAPI backend. Adjust field names here only.
export type SignalKey = "shipment" | "weather" | "inventory" | "supplier" | "news";
export type RiskLevel = "low" | "medium" | "high";

export interface Shipment {
  id: string; sku: string; supplier: string; origin: string; destination: string;
  eta: string; risk_score: number; risk_level: RiskLevel;
  predicted_delay_days: number; inventory_cover_days: number;
}
export interface Alternative { kind: "supplier" | "route"; name: string; lead_time_days: number; note?: string }
export interface Citation { source: string; snippet: string }
export interface Investigation {
  cause: string; impact: string; alternatives: Alternative[];
  recommendation: string; citations: Citation[]; briefing_md: string;
}
export type AgentEvent =
  | { type: "tool_call"; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; tool: string; signal: SignalKey; summary: string }
  | { type: "final"; report: Investigation };
export type Decision = "approve" | "dismiss" | "override";
