import { useState } from "react";
import type { Action, AuditEvent, Baseline, Explanation, Plan, Ranked, User } from "../api";

const RESULTS = ["PASS", "FAIL", "INCONCLUSIVE", "NOT_PERFORMED"] as const;
const fmt = (iso: string) => new Date(iso).toISOString().replace("T", " ").slice(0, 19) + "Z";

export function EvidenceForm({ check, busy, onSubmit, onCancel }: {
  check: Ranked; busy: boolean;
  onSubmit: (b: { result: string; batch_id: string | null; supersedes_id: string | null; notes: string }) => void;
  onCancel: () => void;
}) {
  const [result, setResult] = useState<string>("PASS");
  const [batch, setBatch] = useState<string>(check.target_batch_ids[0] ?? "");
  const [notes, setNotes] = useState("");
  const active = check.prior_evidence.filter((e) => !e.superseded && (e.batch_id ?? "") === batch);
  const supersedes = active[0]?.id ?? null;
  return (
    <form className="evidence-form" onSubmit={(e) => { e.preventDefault(); onSubmit({ result, batch_id: batch || null, supersedes_id: supersedes, notes }); }}>
      <h3>Record result · {check.check_id}</h3>
      <p className="small muted">{check.title}. Synthetic result; persisted server-side and the plan is recomputed from state.</p>
      <fieldset className="results">
        <legend className="small">Result</legend>
        {RESULTS.map((r) => (
          <label key={r} className={`chip ${result === r ? "on" : ""}`}>
            <input type="radio" name="result" value={r} checked={result === r} onChange={() => setResult(r)} />{r}
          </label>
        ))}
      </fieldset>
      {check.target_batch_ids.length > 0 && (
        <label className="field">Batch
          <select value={batch} onChange={(e) => setBatch(e.target.value)}>
            {check.target_batch_ids.map((b) => <option key={b}>{b}</option>)}
          </select>
        </label>
      )}
      <label className="field">Notes (optional)
        <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} placeholder="e.g. 5 samples, Ø within ±0.02" />
      </label>
      {supersedes && <p className="small warn">This supersedes {supersedes} (explicitly versioned).</p>}
      <div className="row">
        <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Submit evidence"}</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function Ids({ ids, allowed }: { ids: string[]; allowed: Set<string> }) {
  return <>{ids.map((id) => <span key={id} className={`id-chip ${allowed.has(id) ? "" : "bad"}`}>{id}</span>)}</>;
}

export function ExplainPanel({ plan, exp, busy, onExplain }: { plan: Plan; exp: Explanation | null; busy: boolean; onExplain: () => void }) {
  const stale = exp && exp.evidence_version !== plan.version;
  const allowed = new Set(exp?.allowed_record_ids ?? []);
  return (
    <div>
      <div className="row between">
        <p className="small muted">Gemini explains the backend plan from a curated payload. The explanation separates cited facts from hypotheses, shows missing evidence and ranking rationale, and cannot change records, scores or approvals. Unknown IDs are stripped.</p>
        <button className="primary" onClick={onExplain} disabled={busy}>{busy ? "Asking Gemini…" : exp ? "Regenerate" : "Generate grounded explanation"}</button>
      </div>
      {stale && <p className="warn small">Explanation is for version {exp!.evidence_version}; plan is now version {plan.version}. Regenerate.</p>}
      {exp?.status === "ok" && exp.explanation && (
        <div className="explanation">
          <p className="small muted">Source: {exp.model} · evidence version {exp.evidence_version}</p>
          <p>{exp.explanation.summary}</p>
          <h4>Verified facts</h4>
          <ul>{exp.explanation.verified_facts.map((f, i) => <li key={i}>{f.claim} <Ids ids={f.record_ids} allowed={allowed} /></li>)}</ul>
          <h4>Hypotheses (unverified)</h4>
          <ul>{exp.explanation.hypotheses.map((h, i) => <li key={i}>{h.claim} <span className="muted small">— {h.uncertainty}</span></li>)}</ul>
          <h4>Missing evidence</h4>
          <ul>{exp.explanation.missing_evidence.map((m) => <li key={m.gap_id}><span className="id-chip">{m.gap_id}</span> {m.why_it_matters}</li>)}</ul>
          <h4>Why this ranking</h4>
          <p>{exp.explanation.recommendation_rationale}</p>
          <p className="small muted"><b>Limitations:</b> {exp.explanation.limitations}</p>
          {exp.stripped.length > 0 && (
            <details><summary className="small warn">{exp.stripped.length} unsupported claim(s) removed by validator</summary>
              <ul className="small">{exp.stripped.map((s, i) => <li key={i}><s>{s.claim}</s> — {s.reason}</li>)}</ul>
            </details>
          )}
        </div>
      )}
      {exp?.status === "unavailable" && (
        <div className="explanation fallback">
          <p><b>{exp.message}</b></p>
          <p className="small muted">{exp.reason}</p>
          {exp.fallback && (
            <>
              <h4>Deterministic summary (no AI)</h4>
              <p>{exp.fallback.summary}</p>
              <ul>{exp.fallback.missing_evidence.map((m) => <li key={m.gap_id}><span className="id-chip">{m.gap_id}</span> {m.why_it_matters}</li>)}</ul>
              <p>{exp.fallback.recommendation_rationale}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ApprovalPanel({ plan, user, busy, onApprove }: { plan: Plan; user: User | undefined; busy: boolean; onApprove: (a: Action, justification: string) => void }) {
  const [just, setJust] = useState<Record<string, string>>({});
  const shown = plan.actions.filter((a) => a.status !== "BLOCKED");
  return (
    <div>
      <div className="sim-banner" role="note">
        SIMULATED APPROVAL: demo identities, not a security control. The server looks up the role for the selected demo user, and every record is stored with simulation = true.
      </div>
      <ul className="actions">
        {shown.map((a) => (
          <li key={a.action_id} className={`action status-${a.status.toLowerCase()}`}>
            <div>
              <strong>{a.action_id}</strong> {a.title}
              <div className="small muted">{a.status} · requires {a.requires_role} · {a.human_reason}</div>
            </div>
            {a.status === "ELIGIBLE" && (
              <form className="row" onSubmit={(e) => { e.preventDefault(); onApprove(a, just[a.action_id] ?? ""); }}>
                <input aria-label={`Justification for ${a.action_id}`} placeholder="Justification" value={just[a.action_id] ?? ""}
                  onChange={(e) => setJust({ ...just, [a.action_id]: e.target.value })} minLength={3} required />
                <button className="primary" disabled={busy} title={user?.role === "OPERATOR" ? "The server will reject this role (403)" : ""}>Approve as {user?.name ?? "?"}</button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <p className="small muted">Blocked actions are listed under “Excluded before scoring”. A high check rank never authorizes an action.</p>
    </div>
  );
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  return (
    <ol className="audit">
      {[...events].reverse().map((e) => (
        <li key={e.seq}>
          <span className="mono small">#{e.seq} · {fmt(e.created_at)}</span>
          <div>
            <strong>{e.event_type}</strong> {e.check_id ?? e.action_id ?? ""} {e.work_order_id && <span className="id-chip">{e.work_order_id}</span>}
            {e.simulation && <span className="tag">simulated</span>}
          </div>
          <div className="small muted">
            {e.actor_id} ({e.actor_role}) · v{e.previous_version ?? "–"} → v{e.new_version ?? "–"}
            {e.evidence_ids.length > 0 && <> · evidence {e.evidence_ids.join(", ")}</>}
            {e.new_state?.ranking && <> · ranking {e.new_state.ranking.join(" › ") || "∅"}</>}
          </div>
          {e.justification && <div className="small">“{e.justification}”</div>}
        </li>
      ))}
    </ol>
  );
}

const STRATS: [string, string][] = [["proofgap", "ProofGap"], ["naive_all_batches", "Naive all-batches"], ["severity_first", "Severity-first"]];

export function BaselinePanel({ data }: { data: Baseline }) {
  const proofgap = data.totals.proofgap;
  const naive = data.totals.naive_all_batches;
  return (
    <div>
      <p className="small muted">{data.method}</p>
      <p className="baseline-summary">
        Across {data.cases.length} synthetic cases, ProofGap used {proofgap.inspections} inspections vs {naive.inspections} for naive all-batches, cost {proofgap.cost} vs {naive.cost} synthetic units, left unresolved gap weight {proofgap.unresolved_weight} vs {naive.unresolved_weight}, and had {proofgap.policy_violations} vs {naive.policy_violations} policy violations.
        <span className="small muted"> Synthetic comparison only; these are not real-world savings.</span>
      </p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Strategy (6 cases)</th><th>Inspections</th><th>Cost</th><th>Hours</th><th>Policy violations</th><th>Unresolved gaps (weight)</th></tr></thead>
          <tbody>
            {STRATS.map(([k, label]) => {
              const t = data.totals[k];
              return <tr key={k}><td>{label}</td><td>{t.inspections}</td><td>{t.cost}</td><td>{t.hours}</td><td>{t.policy_violations}</td><td>{t.unresolved_gaps} ({t.unresolved_weight})</td></tr>;
            })}
          </tbody>
        </table>
      </div>
      <details>
        <summary className="small">Per-case results, including cases where ProofGap does not win</summary>
        <div className="table-scroll">
          <table className="small">
            <thead><tr><th>Case</th><th>Budget</th><th>vs naive</th><th>vs severity</th><th>ProofGap sequence</th></tr></thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.case_id}>
                  <td title={c.description}>{c.case_id} <span className="muted">{c.description}</span></td>
                  <td>{c.budget}</td>
                  <td className={`v-${c.proofgap_vs.naive_all_batches}`}>{c.proofgap_vs.naive_all_batches}</td>
                  <td className={`v-${c.proofgap_vs.severity_first}`}>{c.proofgap_vs.severity_first}</td>
                  <td className="mono">{c.results.proofgap.log.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
