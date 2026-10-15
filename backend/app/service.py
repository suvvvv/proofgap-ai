"""State transitions. Each write is decided in pure Python from the event log and
applied atomically by the store (version bump + record + audit event)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from . import engine as eng
from .config import settings
from .stores.base import ApiError, Commit, IncidentData, Store, stale, utcnow_iso

__all__ = ["ApiError", "Actor", "load_scenario"]


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


def derive(scenario: dict, data: IncidentData) -> eng.DerivedState:
    return eng.derive_state(scenario, data.evidence, data.approvals)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def incident_summary(store: Store, incident_id: str, scenario: dict) -> dict:
    data = store.load(incident_id)
    state = derive(scenario, data)
    return {**scenario["incident"], "version": data.version, "updated_at": data.updated_at,
            "synthetic": scenario.get("synthetic", True),
            "evidence_count": len(data.evidence), "approval_count": len(data.approvals),
            "unresolved_gap_count": len(eng.relevant_unresolved_gaps(scenario, state))}


def thread(store: Store, incident_id: str, scenario: dict, data: IncidentData | None = None) -> dict:
    data = data or store.load(incident_id)
    return {"incident_id": incident_id, "version": data.version, **eng.build_thread(scenario, derive(scenario, data))}


def plan(store: Store, incident_id: str, scenario: dict, data: IncidentData | None = None) -> dict:
    data = data or store.load(incident_id)
    return eng.build_plan(scenario, derive(scenario, data), data.version)


def _snapshot(scenario: dict, state: eng.DerivedState) -> dict:
    ranked, _ = eng.rank_candidates(scenario, state)
    return {"unresolved_gap_ids": sorted(g["id"] for g in eng.relevant_unresolved_gaps(scenario, state)),
            "restriction_ids": sorted(state.restrictions),
            "batch_status": {b: state.batch_status[b] for b in eng.scope_batch_ids(scenario)},
            "ranking": [r["check_id"] for r in ranked]}


def _active_evidence(evidence: list[dict]) -> list[dict]:
    superseded = {e["supersedes_id"] for e in evidence if e.get("supersedes_id")}
    return [e for e in evidence if e["id"] not in superseded]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def record_evidence(store: Store, incident_id: str, scenario: dict, actor: Actor, *, check_id: str,
                    result: str, expected_version: int, batch_id: str | None = None,
                    supersedes_id: str | None = None, notes: str | None = None) -> dict:
    cand = next((c for c in scenario["candidates"] if c["check_id"] == check_id), None)
    if cand is None:
        raise ApiError(422, "UNKNOWN_CHECK", f"Unknown check {check_id}")
    if batch_id is not None and batch_id not in cand["target_batch_ids"]:
        raise ApiError(422, "BATCH_NOT_IN_CHECK", f"{batch_id} is not a target of {check_id}",
                       {"allowed": cand["target_batch_ids"]})

    def decide(data: IncidentData) -> Commit:
        if data.version != expected_version:
            raise stale(expected_version, data.version)
        state = derive(scenario, data)
        rules = eng.check_feasibility(scenario, state, cand)
        if rules:
            raise ApiError(409, "CHECK_NOT_ELIGIBLE", "Check is excluded by feasibility rules.",
                           {"rule_ids": rules, "human_reason": " ".join(eng.RULES[r] for r in rules)})
        active = [e for e in _active_evidence(data.evidence) if e["check_id"] == check_id and e["batch_id"] == batch_id]
        if supersedes_id is None and active:
            raise ApiError(409, "DUPLICATE_EVIDENCE", "A result already exists for this check; submit it as superseding.",
                           {"existing_evidence_ids": [e["id"] for e in active]})
        if supersedes_id is not None and supersedes_id not in {e["id"] for e in active}:
            raise ApiError(422, "INVALID_SUPERSEDES", "supersedes_id must reference the current result for this check.",
                           {"active_evidence_ids": [e["id"] for e in active]})
        new_version = data.version + 1
        now = utcnow_iso()
        ev = {"id": f"EV-{len(data.evidence) + 1:04d}", "check_id": check_id, "batch_id": batch_id, "result": result,
              "notes": notes, "captured_at": now, "actor_id": actor.id, "actor_role": actor.role,
              "version": new_version, "supersedes_id": supersedes_id}
        after = eng.derive_state(scenario, data.evidence + [ev], data.approvals)
        audit = {"event_type": "EVIDENCE_RECORDED", "actor_id": actor.id, "actor_role": actor.role,
                 "simulation": actor.simulation, "action_id": None, "check_id": check_id,
                 "previous_version": data.version, "new_version": new_version,
                 "previous_state": _snapshot(scenario, state), "new_state": _snapshot(scenario, after),
                 "evidence_ids": [ev["id"]], "justification": notes, "work_order_id": None, "created_at": now}
        return Commit(new_version=new_version, audit=audit, evidence=ev, result=ev)

    evidence = store.commit(incident_id, decide)
    return {"evidence": evidence, "plan": plan(store, incident_id, scenario)}


def approve(store: Store, incident_id: str, scenario: dict, actor: Actor, *, action_id: str,
            expected_version: int, justification: str) -> dict:
    action = next((a for a in scenario["actions"] if a["action_id"] == action_id), None)
    if action is None:
        raise ApiError(422, "UNKNOWN_ACTION", f"Unknown action {action_id}")
    if actor.role not in (action["requires_role"], "ADMIN"):
        raise ApiError(403, "FORBIDDEN_ROLE", f"Role {actor.role} cannot approve {action_id}.",
                       {"required_role": action["requires_role"]})

    def decide(data: IncidentData) -> Commit:
        if data.version != expected_version:
            raise stale(expected_version, data.version)
        state = derive(scenario, data)
        verdict = eng.evaluate_action(scenario, state, action)
        if verdict["status"] != "ELIGIBLE":
            raise ApiError(409, "ACTION_NOT_ELIGIBLE", verdict["human_reason"],
                           {"status": verdict["status"], "rule_ids": verdict["rule_ids"]})
        new_version = data.version + 1
        now = utcnow_iso()
        n = len(data.approvals) + 1
        ap = {"id": f"AP-{n:04d}", "action_id": action_id, "actor_id": actor.id, "actor_role": actor.role,
              "simulation": actor.simulation, "justification": justification, "work_order_id": f"WO-{n:04d}",
              "version": new_version, "created_at": now}
        after = eng.derive_state(scenario, data.evidence, data.approvals + [ap])
        audit = {"event_type": "APPROVAL_RECORDED", "actor_id": actor.id, "actor_role": actor.role,
                 "simulation": actor.simulation, "action_id": action_id, "check_id": None,
                 "previous_version": data.version, "new_version": new_version,
                 "previous_state": _snapshot(scenario, state), "new_state": _snapshot(scenario, after),
                 "evidence_ids": [e["id"] for e in _active_evidence(data.evidence)],
                 "justification": justification, "work_order_id": ap["work_order_id"], "created_at": now}
        return Commit(new_version=new_version, audit=audit, approval=ap, result=ap)

    approval = store.commit(incident_id, decide)
    return {"approval": approval, "simulated": actor.simulation, "plan": plan(store, incident_id, scenario)}
