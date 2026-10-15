"""Persistence + state transitions. Every write is one transaction that bumps the
incident version under an optimistic lock and appends an audit event."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import engine as eng
from .config import settings
from .db import Approval, AuditEvent, Evidence, Incident, User


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@dataclass(frozen=True)
class Actor:
    id: str
    name: str
    role: str
    simulation: bool = True


@lru_cache(maxsize=4)
def load_scenario(path: str | None = None) -> dict:
    with open(path or settings.scenario_path, encoding="utf-8") as f:
        return json.load(f)


def _fresh(session: Session) -> Session:
    """Close any read-only autobegun transaction so the write gets its own."""
    if session.in_transaction():
        session.commit()
    return session


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; values are always stored as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed(session: Session, scenario: dict, reset: bool = False) -> None:
    inc_id = scenario["incident"]["id"]
    with _fresh(session).begin():
        if reset:
            for model in (AuditEvent, Approval, Evidence):
                session.query(model).filter_by(incident_id=inc_id).delete()
            session.query(Incident).filter_by(id=inc_id).delete()
        for u in scenario["users"]:
            session.merge(User(id=u["id"], name=u["name"], role=u["role"]))
        if session.get(Incident, inc_id) is None:
            session.add(Incident(id=inc_id, scenario_id=scenario["scenario_id"], version=1, updated_at=utcnow()))
            session.add(AuditEvent(incident_id=inc_id, event_type="INCIDENT_SEEDED", actor_id="system",
                                   actor_role="SYSTEM", new_version=1, created_at=utcnow(),
                                   justification=f"Seeded synthetic scenario {scenario['scenario_id']}"))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _incident(session: Session, incident_id: str) -> Incident:
    inc = session.get(Incident, incident_id)
    if inc is None:
        raise ApiError(404, "INCIDENT_NOT_FOUND", f"Incident {incident_id} not found")
    return inc


def _evidence_dict(e: Evidence) -> dict:
    return {"id": e.id, "check_id": e.check_id, "batch_id": e.batch_id, "result": e.result, "notes": e.notes,
            "captured_at": iso(e.captured_at), "actor_id": e.actor_id, "actor_role": e.actor_role,
            "version": e.version, "supersedes_id": e.supersedes_id}


def _approval_dict(a: Approval) -> dict:
    return {"id": a.id, "action_id": a.action_id, "actor_id": a.actor_id, "actor_role": a.actor_role,
            "simulation": a.simulation, "justification": a.justification, "work_order_id": a.work_order_id,
            "version": a.version, "created_at": iso(a.created_at)}


def load_state(session: Session, incident_id: str, scenario: dict) -> tuple[Incident, eng.DerivedState, list[dict], list[dict]]:
    inc = _incident(session, incident_id)
    evidence = [_evidence_dict(e) for e in session.scalars(
        select(Evidence).where(Evidence.incident_id == incident_id).order_by(Evidence.version))]
    approvals = [_approval_dict(a) for a in session.scalars(
        select(Approval).where(Approval.incident_id == incident_id).order_by(Approval.version))]
    return inc, eng.derive_state(scenario, evidence, approvals), evidence, approvals


def incident_summary(session: Session, incident_id: str, scenario: dict) -> dict:
    inc, state, evidence, approvals = load_state(session, incident_id, scenario)
    s = scenario["incident"]
    return {**s, "version": inc.version, "updated_at": iso(inc.updated_at),
            "synthetic": scenario.get("synthetic", True),
            "evidence_count": len(evidence), "approval_count": len(approvals),
            "unresolved_gap_count": len(eng.relevant_unresolved_gaps(scenario, state))}


def thread(session: Session, incident_id: str, scenario: dict) -> dict:
    inc, state, *_ = load_state(session, incident_id, scenario)
    return {"incident_id": incident_id, "version": inc.version, **eng.build_thread(scenario, state)}


def plan(session: Session, incident_id: str, scenario: dict) -> dict:
    inc, state, *_ = load_state(session, incident_id, scenario)
    return eng.build_plan(scenario, state, inc.version)


def audit(session: Session, incident_id: str) -> list[dict]:
    _incident(session, incident_id)
    rows = session.scalars(select(AuditEvent).where(AuditEvent.incident_id == incident_id).order_by(AuditEvent.seq))
    return [{"seq": r.seq, "event_type": r.event_type, "actor_id": r.actor_id, "actor_role": r.actor_role,
             "simulation": r.simulation, "action_id": r.action_id, "check_id": r.check_id,
             "previous_version": r.previous_version, "new_version": r.new_version,
             "previous_state": r.previous_state, "new_state": r.new_state, "evidence_ids": r.evidence_ids or [],
             "justification": r.justification, "work_order_id": r.work_order_id, "created_at": iso(r.created_at)}
            for r in rows]


def _snapshot(scenario: dict, state: eng.DerivedState) -> dict:
    ranked, _ = eng.rank_candidates(scenario, state)
    return {"unresolved_gap_ids": sorted(g["id"] for g in eng.relevant_unresolved_gaps(scenario, state)),
            "restriction_ids": sorted(state.restrictions),
            "batch_status": {b: state.batch_status[b] for b in eng.scope_batch_ids(scenario)},
            "ranking": [r["check_id"] for r in ranked]}


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _bump_version(session: Session, incident_id: str, expected_version: int) -> int:
    res = session.execute(update(Incident).where(Incident.id == incident_id, Incident.version == expected_version)
                          .values(version=expected_version + 1, updated_at=utcnow()))
    if res.rowcount != 1:
        current = session.get(Incident, incident_id).version
        raise ApiError(409, "STALE_VERSION", "Incident changed since you loaded it; reload and retry.",
                       {"expected_version": expected_version, "current_version": current})
    return expected_version + 1


def _next_id(session: Session, model, prefix: str) -> str:
    n = session.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{n + 1:04d}"


def record_evidence(session: Session, incident_id: str, scenario: dict, actor: Actor, *, check_id: str,
                    result: str, expected_version: int, batch_id: str | None = None,
                    supersedes_id: str | None = None, notes: str | None = None) -> dict:
    candidates = {c["check_id"]: c for c in scenario["candidates"]}
    with _fresh(session).begin():
        inc, state, evidence, _ = load_state(session, incident_id, scenario)
        cand = candidates.get(check_id)
        if cand is None:
            raise ApiError(422, "UNKNOWN_CHECK", f"Unknown check {check_id}")
        if batch_id is not None and batch_id not in cand["target_batch_ids"]:
            raise ApiError(422, "BATCH_NOT_IN_CHECK", f"{batch_id} is not a target of {check_id}",
                           {"allowed": cand["target_batch_ids"]})
        if inc.version != expected_version:
            raise ApiError(409, "STALE_VERSION", "Incident changed since you loaded it; reload and retry.",
                           {"expected_version": expected_version, "current_version": inc.version})
        rules = eng.check_feasibility(scenario, state, cand)
        if rules:
            raise ApiError(409, "CHECK_NOT_ELIGIBLE", "Check is excluded by feasibility rules.",
                           {"rule_ids": rules, "human_reason": " ".join(eng.RULES[r] for r in rules)})
        superseded = {e["supersedes_id"] for e in evidence if e.get("supersedes_id")}
        active = [e for e in evidence if e["check_id"] == check_id and e["batch_id"] == batch_id
                  and e["id"] not in superseded]
        if supersedes_id is None and active:
            raise ApiError(409, "DUPLICATE_EVIDENCE", "A result already exists for this check; submit it as superseding.",
                           {"existing_evidence_ids": [e["id"] for e in active]})
        if supersedes_id is not None and supersedes_id not in {e["id"] for e in active}:
            raise ApiError(422, "INVALID_SUPERSEDES", "supersedes_id must reference the current result for this check.",
                           {"active_evidence_ids": [e["id"] for e in active]})

        before = _snapshot(scenario, state)
        new_version = _bump_version(session, incident_id, expected_version)
        ev = Evidence(id=_next_id(session, Evidence, "EV"), incident_id=incident_id, check_id=check_id,
                      batch_id=batch_id, result=result, notes=notes, captured_at=utcnow(), actor_id=actor.id,
                      actor_role=actor.role, version=new_version, supersedes_id=supersedes_id)
        session.add(ev)
        session.flush()
        new_state = eng.derive_state(scenario, evidence + [_evidence_dict(ev)],
                                     [_approval_dict(a) for a in session.scalars(
                                         select(Approval).where(Approval.incident_id == incident_id))])
        session.add(AuditEvent(incident_id=incident_id, event_type="EVIDENCE_RECORDED", actor_id=actor.id,
                               actor_role=actor.role, simulation=actor.simulation, check_id=check_id,
                               previous_version=expected_version, new_version=new_version,
                               previous_state=before, new_state=_snapshot(scenario, new_state),
                               evidence_ids=[ev.id], justification=notes, created_at=utcnow()))
        evidence_out = _evidence_dict(ev)
    return {"evidence": evidence_out, "plan": plan(session, incident_id, scenario)}


def approve(session: Session, incident_id: str, scenario: dict, actor: Actor, *, action_id: str,
            expected_version: int, justification: str) -> dict:
    actions = {a["action_id"]: a for a in scenario["actions"]}
    with _fresh(session).begin():
        inc, state, evidence, approvals = load_state(session, incident_id, scenario)
        action = actions.get(action_id)
        if action is None:
            raise ApiError(422, "UNKNOWN_ACTION", f"Unknown action {action_id}")
        if actor.role not in (action["requires_role"], "ADMIN"):
            raise ApiError(403, "FORBIDDEN_ROLE", f"Role {actor.role} cannot approve {action_id}.",
                           {"required_role": action["requires_role"]})
        if inc.version != expected_version:
            raise ApiError(409, "STALE_VERSION", "Incident changed since you loaded it; reload and retry.",
                           {"expected_version": expected_version, "current_version": inc.version})
        verdict = eng.evaluate_action(scenario, state, action)
        if verdict["status"] != "ELIGIBLE":
            raise ApiError(409, "ACTION_NOT_ELIGIBLE", verdict["human_reason"],
                           {"status": verdict["status"], "rule_ids": verdict["rule_ids"]})

        before = _snapshot(scenario, state)
        new_version = _bump_version(session, incident_id, expected_version)
        ap = Approval(id=_next_id(session, Approval, "AP"), incident_id=incident_id, action_id=action_id,
                      actor_id=actor.id, actor_role=actor.role, simulation=actor.simulation,
                      justification=justification, work_order_id=_next_id(session, Approval, "WO"),
                      version=new_version, created_at=utcnow())
        session.add(ap)
        session.flush()
        new_state = eng.derive_state(scenario, evidence, approvals + [_approval_dict(ap)])
        superseded = {e["supersedes_id"] for e in evidence if e.get("supersedes_id")}
        session.add(AuditEvent(incident_id=incident_id, event_type="APPROVAL_RECORDED", actor_id=actor.id,
                               actor_role=actor.role, simulation=actor.simulation, action_id=action_id,
                               previous_version=expected_version, new_version=new_version,
                               previous_state=before, new_state=_snapshot(scenario, new_state),
                               evidence_ids=[e["id"] for e in evidence if e["id"] not in superseded],
                               justification=justification, work_order_id=ap.work_order_id, created_at=utcnow()))
        out = _approval_dict(ap)
    return {"approval": out, "simulated": actor.simulation, "plan": plan(session, incident_id, scenario)}
