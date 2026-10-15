import { useCallback, useEffect, useState } from "react";
import { api, ApiError, setDemoUser } from "./api";
import type { Action, AuditEvent, Baseline, Explanation, Incident, Plan, Ranked, Thread, User } from "./api";
import { TraceGraph } from "./components/TraceGraph";
import { PlanPanel } from "./components/PlanPanel";
import { ApprovalPanel, AuditTimeline, BaselinePanel, EvidenceForm, ExplainPanel } from "./components/Panels";

const INCIDENT_ID = "INC-M04-001";
const USER_KEY = "proofgap.demoUser";

function readStoredUser(): string {
  try { return localStorage.getItem(USER_KEY) ?? "u-op-1"; } catch { return "u-op-1"; }
}

type Toast = { kind: "ok" | "err"; text: string } | null;

export default function App() {
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserId] = useState(readStoredUser);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [thread, setThread] = useState<Thread | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [exp, setExp] = useState<Explanation | null>(null);
  const [recording, setRecording] = useState<Ranked | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  setDemoUser(userId);
  const user = users.find((u) => u.id === userId);

  const refresh = useCallback(async () => {
    try {
      const [i, t, p, a] = await Promise.all([api.incident(INCIDENT_ID), api.thread(INCIDENT_ID), api.plan(INCIDENT_ID), api.audit(INCIDENT_ID)]);
      setIncident(i); setThread(t); setPlan(p); setAudit(a.events); setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    api.users().then((r) => setUsers(r.users)).catch(() => {});
    api.baseline().then(setBaseline).catch(() => {});
    refresh();
  }, [refresh]);

  const changeUser = (id: string) => {
    setUserId(id);
    try { localStorage.setItem(USER_KEY, id); } catch { /* storage unavailable */ }
  };

  const run = async (label: string, fn: () => Promise<string | void>) => {
    setBusy(label);
    try {
      const msg = await fn();
      if (msg) setToast({ kind: "ok", text: msg });
    } catch (e) {
      if (e instanceof ApiError) {
        const rules = Array.isArray(e.details?.rule_ids) ? ` [${(e.details.rule_ids as string[]).join(", ")}]` : "";
        setToast({ kind: "err", text: `${e.status} ${e.code}: ${e.message}${rules}` });
      } else setToast({ kind: "err", text: String(e) });
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  const submitEvidence = (b: { result: string; batch_id: string | null; supersedes_id: string | null; notes: string }) =>
    run("evidence", async () => {
      const r = await api.evidence(INCIDENT_ID, { check_id: recording!.check_id, expected_version: plan!.version, ...b, notes: b.notes || undefined });
      setRecording(null);
      return `${r.evidence.id} saved (${r.evidence.result}). Plan recomputed at version ${r.plan.version}.`;
    });

  const approve = (a: Action, justification: string) =>
    run("approve", async () => {
      const r = await api.approve(INCIDENT_ID, { action_id: a.action_id, expected_version: plan!.version, justification });
      return `${a.action_id} approved (simulated). Work order ${r.approval.work_order_id}.`;
    });

  const explain = () => run("explain", async () => { setExp(await api.explain(INCIDENT_ID, plan!.version)); });

  const reset = () => run("reset", async () => { await api.reset(); setExp(null); setRecording(null); return "Demo data reset."; });

  if (loadError && !incident) return <main className="page"><div className="card err">Cannot reach the API: {loadError}</div></main>;
  if (!incident || !thread || !plan) return <main className="page"><p className="muted">Loading incident…</p></main>;
  const s = incident.sensor;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>◆</span> ProofGap AI
          <span className="tag">Synthetic demo · decision support only</span>
        </div>
        <div className="row">
          <label className="small">Demo identity (simulated)&nbsp;
            <select value={userId} onChange={(e) => changeUser(e.target.value)}>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.role}</option>)}
            </select>
          </label>
          {user?.role === "ADMIN" && <button onClick={reset} disabled={!!busy}>Reset demo</button>}
        </div>
      </header>

      <main className="page">
        {toast && (
          <div className={`toast ${toast.kind}`} role="status" onClick={() => setToast(null)}>{toast.text} <span className="muted small">(dismiss)</span></div>
        )}

        <section className="card incident">
          <div className="incident-main">
            <div className="small muted">{incident.id} · opened {incident.opened_at} · state version <b>v{incident.version}</b></div>
            <h1>{incident.title}</h1>
            <p>{incident.why_it_matters}</p>
          </div>
          <div className="reading">
            <div className="reading-value">{s.reading}<span> {s.unit}</span></div>
            <div className="small">threshold {s.threshold} {s.unit} · <span className="sev">{incident.severity}</span></div>
            <div className="small muted">{s.metric} at {s.reading_at}</div>
          </div>
          <dl className="provenance small">
            <div><dt>Reading</dt><dd><span className="id-chip">{s.record_id}</span> · last in-tolerance <span className="id-chip">{s.last_in_tolerance_record_id}</span></dd></div>
            <div><dt>Sensor</dt><dd>{s.sensor_id} · cal. <span className="id-chip">{s.calibration_record_id}</span></dd></div>
            <div><dt>Window</dt><dd>{incident.window.start.slice(11, 16)}–{incident.window.end.slice(11, 16)}Z · {incident.window.basis}</dd></div>
            <div><dt>Source</dt><dd>{s.source}</dd></div>
          </dl>
        </section>

        <section className="card">
          <h2>Digital thread <span className="muted small">deterministic traceability</span></h2>
          <TraceGraph thread={thread} />
          <div className="legend small">
            <span><i className="sw verified" /> verified link</span>
            <span><i className="sw unknown" /> UNKNOWN link (never treated as safe)</span>
            <span>Excluded: {thread.excluded_runs.map((r) => `${r.id} (${r.reason})`).join(", ")}</span>
          </div>
        </section>

        <div className="grid">
          <section className="card">
            <h2>Evidence gaps <span className="muted small">{plan.unresolved_gaps.length} unresolved</span></h2>
            <ul className="gaps">
              {plan.unresolved_gaps.map((g) => (
                <li key={g.id}>
                  <span className={`weight w${g.weight}`} title="Pre-assigned decision weight (1 low – 3 high), not a likelihood">{g.weight}</span>
                  <div><strong>{g.id}</strong> {g.title}{g.created_by && <span className="tag">new from {g.created_by}</span>}<div className="small muted">{g.why}</div></div>
                </li>
              ))}
            </ul>
            {plan.restrictions.map((r) => <div key={r.id} className="restriction small"><b>{r.id}</b> {r.text}</div>)}
            {plan.resolved_gaps.length > 0 && (
              <details><summary className="small">Resolved ({plan.resolved_gaps.length})</summary>
                <ul className="small">{plan.resolved_gaps.map((g) => <li key={g.id}><s>{g.id}</s> {g.title} · by {g.resolved_by}</li>)}</ul>
              </details>
            )}
          </section>

          <section className="card">
            {recording ? (
              <EvidenceForm key={recording.check_id} check={recording} busy={busy === "evidence"} onSubmit={submitEvidence} onCancel={() => setRecording(null)} />
            ) : (
              <PlanPanel plan={plan} onRecord={setRecording} />
            )}
          </section>
        </div>

        <section className="card">
          <h2>Grounded explanation <span className="muted small">Gemini</span></h2>
          <ExplainPanel plan={plan} exp={exp} busy={busy === "explain"} onExplain={explain} />
        </section>

        <div className="grid">
          <section className="card">
            <h2>Decisions</h2>
            <ApprovalPanel plan={plan} user={user} busy={busy === "approve"} onApprove={approve} />
          </section>
          <section className="card">
            <h2>Audit timeline <span className="muted small">append-only application log</span></h2>
            <AuditTimeline events={audit} />
          </section>
        </div>

        {baseline && (
          <section className="card">
            <h2>Baseline comparison <span className="muted small">synthetic, reproducible</span></h2>
            <BaselinePanel data={baseline} />
          </section>
        )}

        <footer className="small muted">
          Prototype decision support on synthetic data, not certified quality assurance, defect prediction or machine control. Manufacturing — Intelligent Operations &amp; Industrial Efficiency · AI Builder Cup 2026.
        </footer>
      </main>
    </>
  );
}
