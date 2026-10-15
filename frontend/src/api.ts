// Thin typed client. The UI renders server values only; it never recomputes scores.

export type Gap = { id: string; title: string; weight: number; why: string; batch_ids: string[]; status: string; resolved_by?: string; created_by?: string };
export type Factors = { I: number; E: number; C: number; T: number };
export type EvidenceRec = { id: string; check_id: string; batch_id: string | null; result: string; captured_at: string; actor_id: string; actor_role: string; version: number; supersedes_id: string | null; superseded?: boolean; notes?: string | null };
export type Ranked = {
  rank: number; check_id: string; title: string; target_batch_ids: string[]; gap_ids_addressed: string[];
  factors: Factors; score: number; score_display: number; required_resources: string[]; limitations: string; provenance: string;
  raw: { addressed_weight: number; total_weight: number; addressed_count: number; total_count: number; cost: number; estimated_hours: number };
  prior_evidence: EvidenceRec[];
};
export type Excluded = { check_id: string; title: string; rule_ids: string[]; human_reason: string };
export type Action = { action_id: string; kind: string; title: string; target_batch_ids: string[]; requires_role: string; status: "ELIGIBLE" | "BLOCKED" | "APPROVED" | "NOT_APPLICABLE"; rule_ids: string[]; human_reason: string; approval_id?: string };
export type Plan = {
  incident_id: string; version: number; weights: Record<string, number>; normalizers: { reference_cost: number; reference_hours: number };
  unresolved_gaps: Gap[]; resolved_gaps: Gap[]; restrictions: { id: string; text: string; batch_ids: string[] }[];
  ranked_candidates: Ranked[]; excluded_candidates: Excluded[]; actions: Action[]; disclaimer: string;
  sensitivity: { stable_top: boolean; stable_order: boolean; runs: { weights_name: string; order: string[]; same_top: boolean; same_order: boolean }[] };
};
export type GraphNode = { id: string; type: string; label: string; status: string; trace_status?: string };
export type GraphEdge = { source: string; target: string; relation: string; status: string };
export type Thread = { version: number; nodes: GraphNode[]; edges: GraphEdge[]; unknown_relationships: { batch_id: string; detail: string }[]; excluded_runs: { id: string; reason: string }[]; scope_batch_ids: string[] };
export type Incident = {
  id: string; title: string; machine_id: string; severity: string; opened_at: string; version: number; why_it_matters: string; part_number: string;
  sensor: { record_id: string; sensor_id: string; metric: string; unit: string; threshold: number; reading: number; reading_at: string; source: string; calibration_record_id: string; last_in_tolerance_record_id: string };
  window: { start: string; end: string; basis: string }; evidence_count: number; unresolved_gap_count: number;
};
export type AuditEvent = { seq: number; event_type: string; actor_id: string; actor_role: string; simulation: boolean; action_id: string | null; check_id: string | null; previous_version: number | null; new_version: number | null; evidence_ids: string[]; justification: string | null; work_order_id: string | null; created_at: string; new_state: { ranking?: string[]; unresolved_gap_ids?: string[] } | null };
export type User = { id: string; name: string; role: string };
export type Explanation = {
  status: "ok" | "unavailable"; source: string; model: string; evidence_version: number; message?: string; reason?: string; allowed_record_ids: string[];
  stripped: { section: string; claim: string; reason: string }[];
  explanation?: { summary: string; verified_facts: { claim: string; record_ids: string[] }[]; hypotheses: { claim: string; uncertainty: string }[]; missing_evidence: { gap_id: string; why_it_matters: string }[]; recommendation_rationale: string; limitations: string };
  fallback?: { summary: string; verified_facts: { claim: string; record_ids: string[] }[]; missing_evidence: { gap_id: string; why_it_matters: string }[]; recommendation_rationale: string };
};
type StrategyResult = { inspections: number; cost: number; hours: number; policy_violations: number; infeasible_attempts: number; unresolved_gaps: number; unresolved_weight: number; log: string[] };
export type Baseline = { method: string; totals: Record<string, Omit<StrategyResult, "log">>; cases: { case_id: string; description: string; budget: number; results: Record<string, StrategyResult>; proofgap_vs: Record<string, string> }[] };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

let demoUser = "";
export const setDemoUser = (id: string) => { demoUser = id; };

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (demoUser) headers["X-Demo-User"] = demoUser;
  const res = await fetch(path, { ...init, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body.code ?? "HTTP_ERROR", body.message ?? res.statusText, body.details);
  return body as T;
}

const base = (id: string) => `/api/incidents/${encodeURIComponent(id)}`;
export const api = {
  health: () => req<{ status: string; runtime: string; store: string; gemini_configured: boolean }>("/api/health"),
  users: () => req<{ simulated: boolean; users: User[] }>("/api/users"),
  incident: (id: string) => req<Incident>(base(id)),
  thread: (id: string) => req<Thread>(`${base(id)}/thread`),
  plan: (id: string) => req<Plan>(`${base(id)}/plan`),
  audit: (id: string) => req<{ events: AuditEvent[] }>(`${base(id)}/audit`),
  baseline: () => req<Baseline>("/api/baseline"),
  evidence: (id: string, body: { check_id: string; result: string; batch_id?: string | null; expected_version: number; supersedes_id?: string | null; notes?: string }) =>
    req<{ evidence: EvidenceRec; plan: Plan }>(`${base(id)}/evidence`, { method: "POST", body: JSON.stringify(body) }),
  explain: (id: string, expected_version: number) => req<Explanation>(`${base(id)}/explain`, { method: "POST", body: JSON.stringify({ expected_version }) }),
  approve: (id: string, body: { action_id: string; expected_version: number; justification: string }) =>
    req<{ approval: { id: string; work_order_id: string }; simulated: boolean; plan: Plan }>(`${base(id)}/approve`, { method: "POST", body: JSON.stringify(body) }),
  reset: () => req<{ status: string }>("/api/admin/reset", { method: "POST" }),
};
