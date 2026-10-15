import { useState } from "react";
import type { Plan, Ranked } from "../api";

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

function FactorRow({ label, value, weight, sign, raw }: { label: string; value: number; weight: number; sign: 1 | -1; raw: string }) {
  return (
    <div className="factor">
      <span className="factor-name">{label}</span>
      <span className="bar"><span className={`bar-fill ${sign < 0 ? "neg" : ""}`} style={{ width: pct(value) }} /></span>
      <span className="mono">{value.toFixed(3)}</span>
      <span className="mono muted">{sign > 0 ? "+" : "−"}{weight.toFixed(2)}×</span>
      <span className="muted small">{raw}</span>
    </div>
  );
}

function CandidateCard({ c, plan, onRecord }: { c: Ranked; plan: Plan; onRecord: (c: Ranked) => void }) {
  const [open, setOpen] = useState(c.rank === 1);
  const w = plan.weights;
  const active = c.prior_evidence.filter((e) => !e.superseded);
  return (
    <li className="candidate">
      <div className="candidate-head">
        <span className="rank">#{c.rank}</span>
        <div className="candidate-title">
          <strong>{c.check_id}</strong> {c.title}
          <div className="muted small">
            Targets {c.target_batch_ids.length ? c.target_batch_ids.join(", ") : "machine"} · addresses {c.gap_ids_addressed.join(", ")} · {c.raw.cost} units · {c.raw.estimated_hours} h
          </div>
        </div>
        <span className="score" title="Comparative heuristic score, not a probability">{c.score_display.toFixed(1)}</span>
      </div>
      {active.length > 0 && (
        <div className="small prior">Prior result: {active.map((e) => `${e.id} ${e.result}`).join(", ")}</div>
      )}
      <div className="candidate-actions">
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide" : "Show"} score breakdown</button>
        <button className="primary" onClick={() => onRecord(c)}>Record result</button>
      </div>
      {open && (
        <div className="breakdown">
          <FactorRow label="I impact" value={c.factors.I} weight={w.impact} sign={1} raw={`${c.raw.addressed_weight}/${c.raw.total_weight} gap weight`} />
          <FactorRow label="E coverage" value={c.factors.E} weight={w.coverage} sign={1} raw={`${c.raw.addressed_count}/${c.raw.total_count} gaps`} />
          <FactorRow label="C cost" value={c.factors.C} weight={w.cost} sign={-1} raw={`${c.raw.cost}/${plan.normalizers.reference_cost}`} />
          <FactorRow label="T time" value={c.factors.T} weight={w.time} sign={-1} raw={`${c.raw.estimated_hours}/${plan.normalizers.reference_hours} h`} />
          <div className="mono small formula">
            100 × ({w.impact}·{c.factors.I.toFixed(3)} + {w.coverage}·{c.factors.E.toFixed(3)} − {w.cost}·{c.factors.C.toFixed(3)} − {w.time}·{c.factors.T.toFixed(3)}) = {c.score.toFixed(2)}
          </div>
          <div className="small"><b>Limitations:</b> {c.limitations}</div>
          <div className="small muted"><b>Provenance:</b> {c.provenance} · Resources: {c.required_resources.join(", ") || "none"}</div>
        </div>
      )}
    </li>
  );
}

export function PlanPanel({ plan, onRecord }: { plan: Plan; onRecord: (c: Ranked) => void }) {
  const blockedActions = plan.actions.filter((a) => a.status === "BLOCKED");
  return (
    <div className="plan">
      <h3>Ranked feasible checks</h3>
      {plan.ranked_candidates.length === 0 ? <p className="muted">No feasible check currently adds decision value.</p> : (
        <ol className="candidates">
          {plan.ranked_candidates.map((c) => <CandidateCard key={c.check_id} c={c} plan={plan} onRecord={onRecord} />)}
        </ol>
      )}
      <p className="small muted">
        {plan.disclaimer}{" "}
        Weight sensitivity: top choice {plan.sensitivity.stable_top ? "stable" : "changes"} and full order {plan.sensitivity.stable_order ? "stable" : "changes"} across {plan.sensitivity.runs.length} weight sets.
      </p>
      <details className="sensitivity">
        <summary className="small">Sensitivity detail</summary>
        <table className="small">
          <tbody>
            {plan.sensitivity.runs.map((r) => (
              <tr key={r.weights_name}><td>{r.weights_name}</td><td className="mono">{r.order.join(" › ")}</td><td>{r.same_order ? "same" : r.same_top ? "same top" : "different top"}</td></tr>
            ))}
          </tbody>
        </table>
      </details>

      <h3>Excluded before scoring</h3>
      <ul className="excluded">
        {plan.excluded_candidates.map((e) => (
          <li key={e.check_id}>
            <span className="rules">{e.rule_ids.map((r) => <span key={r} className="rule">{r}</span>)}</span>
            <span><strong>{e.check_id}</strong> {e.title}<br /><span className="muted small">{e.human_reason}</span></span>
          </li>
        ))}
        {blockedActions.map((a) => (
          <li key={a.action_id}>
            <span className="rules">{a.rule_ids.map((r) => <span key={r} className="rule">{r}</span>)}</span>
            <span><strong>{a.action_id}</strong> {a.title}<br /><span className="muted small">{a.human_reason}</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}
