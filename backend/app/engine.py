"""Deterministic ProofGap engine.

Pure functions over a scenario dict (the seeded reference data) and the ordered
list of persisted events (evidence + approvals). Nothing here touches the
database or the AI layer, so every number the UI shows can be reproduced from
the fixture and the event log alone.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

RESULTS = ("PASS", "FAIL", "INCONCLUSIVE", "NOT_PERFORMED")

DEFAULT_WEIGHTS = {"impact": 0.40, "coverage": 0.30, "cost": 0.20, "time": 0.10}
REFERENCE_COST = 1000.0
REFERENCE_HOURS = 8.0

SENSITIVITY_WEIGHTS = {
    "default": DEFAULT_WEIGHTS,
    "impact_heavy": {"impact": 0.50, "coverage": 0.20, "cost": 0.20, "time": 0.10},
    "coverage_heavy": {"impact": 0.25, "coverage": 0.45, "cost": 0.20, "time": 0.10},
    "cost_heavy": {"impact": 0.30, "coverage": 0.20, "cost": 0.35, "time": 0.15},
}

RULES = {
    "F01": "Already shipped; use customer/quality escalation workflow instead.",
    "F02": "Mandatory quality review outstanding.",
    "F03": "Required resource unavailable in the simulated scenario.",
    "F04": "No verified traceability relationship to this incident.",
    "F05": "Status unknown; escalate for verification, do not assume safe.",
    "F06": "Prohibited by mandatory quality constraint.",
    "F07": "No current decision value; do not rank.",
}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def affected_runs(scenario: dict) -> list[dict]:
    inc = scenario["incident"]
    start, end = _ts(inc["window"]["start"]), _ts(inc["window"]["end"])
    return [
        r
        for r in scenario["production_runs"]
        if r["machine_id"] == inc["machine_id"] and _ts(r["start"]) < end and _ts(r["end"]) > start
    ]


def scope_batch_ids(scenario: dict) -> list[str]:
    run_ids = {r["id"] for r in affected_runs(scenario)}
    return sorted(b["id"] for b in scenario["batches"] if b["run_id"] in run_ids)


def build_thread(scenario: dict, state: "DerivedState") -> dict:
    """Typed node/edge graph from sensor reading to shipments.

    A missing link becomes an explicit UNKNOWN node and edge; it is never
    rendered as safe.
    """
    inc = scenario["incident"]
    nodes: list[dict] = []
    edges: list[dict] = []
    unknowns: list[dict] = []
    sensor = inc["sensor"]
    machine = next(m for m in scenario["machines"] if m["id"] == inc["machine_id"])

    nodes.append({"id": sensor["record_id"], "type": "SENSOR_READING",
                  "label": f"{sensor['reading']} {sensor['unit']} > {sensor['threshold']}",
                  "status": "ALARM"})
    nodes.append({"id": machine["id"], "type": "MACHINE", "label": machine["name"], "status": "SUSPECT"})
    edges.append({"source": sensor["record_id"], "target": machine["id"], "relation": "MEASURED_ON", "status": "VERIFIED"})

    runs = affected_runs(scenario)
    run_ids = {r["id"] for r in runs}
    for r in runs:
        nodes.append({"id": r["id"], "type": "RUN", "label": f"{r['start'][11:16]}–{r['end'][11:16]}Z", "status": "IN_WINDOW"})
        edges.append({"source": machine["id"], "target": r["id"], "relation": "PRODUCED", "status": "VERIFIED"})

    orders = {o["id"]: o for o in scenario["orders"]}
    shipments_by_order: dict[str, list[dict]] = {}
    for s in scenario["shipments"]:
        shipments_by_order.setdefault(s["order_id"], []).append(s)
    seen_orders: set[str] = set()

    for b in scenario["batches"]:
        if b["run_id"] not in run_ids:
            continue
        status = state.batch_status[b["id"]]
        trace = "UNKNOWN" if not b.get("order_id") else "LINKED"
        nodes.append({"id": b["id"], "type": "BATCH", "label": f"{b['qty']} pcs", "status": status, "trace_status": trace})
        edges.append({"source": b["run_id"], "target": b["id"], "relation": "OUTPUT", "status": "VERIFIED"})
        if not b.get("order_id"):
            unknown_id = f"UNKNOWN-ORDER-{b['id']}"
            nodes.append({"id": unknown_id, "type": "UNKNOWN", "label": "Order link missing", "status": "UNKNOWN"})
            edges.append({"source": b["id"], "target": unknown_id, "relation": "ALLOCATED_TO", "status": "UNKNOWN"})
            unknowns.append({"batch_id": b["id"], "relation": "ALLOCATED_TO", "detail": "No order record links this batch; downstream exposure is UNKNOWN, not SAFE."})
            continue
        order = orders[b["order_id"]]
        if order["id"] not in seen_orders:
            seen_orders.add(order["id"])
            nodes.append({"id": order["id"], "type": "ORDER", "label": order["customer"], "status": order["status"]})
            for s in shipments_by_order.get(order["id"], []):
                nodes.append({"id": s["id"], "type": "SHIPMENT", "label": f"shipped {s['shipped_at'][11:16]}Z", "status": s["status"]})
                edges.append({"source": order["id"], "target": s["id"], "relation": "FULFILLED_BY", "status": "VERIFIED"})
        edges.append({"source": b["id"], "target": order["id"], "relation": "ALLOCATED_TO", "status": "VERIFIED"})

    excluded_runs = [
        {"id": r["id"], "machine_id": r["machine_id"],
         "reason": "Different machine" if r["machine_id"] != inc["machine_id"] else "Outside anomaly window"}
        for r in scenario["production_runs"] if r["id"] not in run_ids
    ]
    excluded_batches = [
        {"id": b["id"], "run_id": b["run_id"]} for b in scenario["batches"] if b["run_id"] not in run_ids
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "unknown_relationships": unknowns,
        "scope_batch_ids": scope_batch_ids(scenario),
        "excluded_runs": excluded_runs,
        "excluded_batches": excluded_batches,
        "shipments": [s for s in scenario["shipments"] if s["order_id"] in seen_orders],
    }


# ---------------------------------------------------------------------------
# State derivation from the event log
# ---------------------------------------------------------------------------


@dataclass
class DerivedState:
    gaps: dict[str, dict]
    restrictions: dict[str, dict]
    batch_status: dict[str, str]
    approved_actions: dict[str, str] = field(default_factory=dict)  # action_id -> approval id
    evidence_by_check: dict[str, list[dict]] = field(default_factory=dict)


def derive_state(scenario: dict, evidence: Iterable[dict] = (), approvals: Iterable[dict] = ()) -> DerivedState:
    """Replay persisted events (ordered by incident version) onto the seed."""
    gaps = {g["id"]: copy.deepcopy(g) for g in scenario["gaps"]}
    restrictions: dict[str, dict] = {}
    batch_status = {b["id"]: b["status"] for b in scenario["batches"]}
    candidates = {c["check_id"]: c for c in scenario["candidates"]}
    actions = {a["action_id"]: a for a in scenario.get("actions", [])}

    evidence = list(evidence)
    superseded = {e["supersedes_id"] for e in evidence if e.get("supersedes_id")}
    events = [("evidence", e) for e in evidence if e["id"] not in superseded]
    events += [("approval", a) for a in approvals]
    events.sort(key=lambda ev: ev[1]["version"])

    state = DerivedState(gaps=gaps, restrictions=restrictions, batch_status=batch_status)
    for e in evidence:
        state.evidence_by_check.setdefault(e["check_id"], []).append(
            {**e, "superseded": e["id"] in superseded})

    for kind, ev in events:
        if kind == "evidence":
            effect = candidates[ev["check_id"]].get("on_result", {}).get(ev["result"], {})
            for gid in effect.get("resolves", []):
                if gid in gaps and gaps[gid]["status"] == "UNRESOLVED":
                    gaps[gid]["status"] = "RESOLVED"
                    gaps[gid]["resolved_by"] = ev["id"]
            for gid in effect.get("creates", []):
                if gid not in gaps:
                    gaps[gid] = {**copy.deepcopy(scenario["gap_templates"][gid]),
                                 "status": "UNRESOLVED", "created_by": ev["id"]}
            for rid in effect.get("restricts", []):
                restrictions.setdefault(rid, {**scenario["restriction_templates"][rid], "created_by": ev["id"]})
        else:
            action = actions[ev["action_id"]]
            state.approved_actions[action["action_id"]] = ev["id"]
            eff = action.get("effect", {})
            if "batch_status" in eff:
                for b in action["target_batch_ids"]:
                    batch_status[b] = eff["batch_status"]
            for rid in eff.get("clears_restrictions", []):
                restrictions.pop(rid, None)
    return state


def relevant_unresolved_gaps(scenario: dict, state: DerivedState) -> list[dict]:
    scope = set(scope_batch_ids(scenario))
    return [
        g for g in state.gaps.values()
        if g["status"] == "UNRESOLVED" and g.get("decision_relevant", True)
        and set(g.get("batch_ids", [])) <= scope
    ]


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------


def _reason(rule_ids: list[str]) -> str:
    return " ".join(RULES[r] for r in rule_ids)


def check_feasibility(scenario: dict, state: DerivedState, candidate: dict) -> list[str]:
    scope = set(scope_batch_ids(scenario))
    resources = {r["id"]: r for r in scenario["resources"]}
    relevant = {g["id"] for g in relevant_unresolved_gaps(scenario, state)}
    rules: set[str] = set()
    for b in candidate.get("target_batch_ids", []):
        if b not in scope:
            rules.add("F04")
            continue
        allowed = candidate.get("allowed_statuses") or []
        status = state.batch_status[b]
        if allowed and status not in allowed:
            rules.add("F01" if status == "SHIPPED" else "F06")
    if any(not resources.get(r, {}).get("available", False) for r in candidate.get("required_resources", [])):
        rules.add("F03")
    if candidate.get("violates_rules"):
        rules.add("F06")
    if "F04" not in rules and not (set(candidate["gap_ids_addressable"]) & relevant):
        rules.add("F07")
    return sorted(rules)


def evaluate_action(scenario: dict, state: DerivedState, action: dict) -> dict:
    scope = set(scope_batch_ids(scenario))
    batches = {b["id"]: b for b in scenario["batches"]}
    unresolved = [g for g in state.gaps.values() if g["status"] == "UNRESOLVED"]
    rules: set[str] = set()

    if action["action_id"] in state.approved_actions:
        return {"status": "APPROVED", "rule_ids": [], "human_reason": "Already approved.",
                "approval_id": state.approved_actions[action["action_id"]]}

    for b in action["target_batch_ids"]:
        if b not in scope:
            rules.add("F04")
            continue
        if action["kind"] == "HOLD" and state.batch_status[b] == "SHIPPED":
            rules.add("F01")
        if action["kind"] in ("RELEASE", "SHIP"):
            if not batches[b].get("order_id"):
                rules.add("F05")
            blocking = [g for g in unresolved if b in g.get("batch_ids", [])]
            restricted = [r for r in state.restrictions.values() if b in r["batch_ids"]]
            if action["kind"] == "RELEASE" and (blocking or restricted):
                rules.add("F02")
    if action.get("violates_rules"):
        rules.add("F06")
    if action.get("requires_restriction") and action["requires_restriction"] not in state.restrictions:
        rules.add("F07")

    rule_ids = sorted(rules)
    if rule_ids == ["F07"]:
        return {"status": "NOT_APPLICABLE", "rule_ids": rule_ids, "human_reason": _reason(rule_ids)}
    if rule_ids:
        return {"status": "BLOCKED", "rule_ids": rule_ids, "human_reason": _reason(rule_ids)}
    return {"status": "ELIGIBLE", "rule_ids": [], "human_reason": "Feasible; requires authorized approval."}


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def score_candidate(candidate: dict, relevant: list[dict], weights: dict = DEFAULT_WEIGHTS,
                    reference_cost: float = REFERENCE_COST, reference_hours: float = REFERENCE_HOURS) -> dict:
    relevant_ids = {g["id"] for g in relevant}
    addressed = sorted(set(candidate["gap_ids_addressable"]) & relevant_ids)
    total_weight = sum(g["weight"] for g in relevant)
    addressed_weight = sum(g["weight"] for g in relevant if g["id"] in addressed)
    impact = _clamp(min(1.0, addressed_weight / max(1, total_weight)))
    coverage = _clamp(len(addressed) / max(1, len(relevant)))
    cost = _clamp(max(0.0, candidate["cost"]) / reference_cost)
    time = _clamp(max(0.0, candidate["estimated_hours"]) / reference_hours)
    score = 100 * (weights["impact"] * impact + weights["coverage"] * coverage
                   - weights["cost"] * cost - weights["time"] * time)
    return {
        "gap_ids_addressed": addressed,
        "factors": {"I": impact, "E": coverage, "C": cost, "T": time},
        "raw": {"addressed_weight": addressed_weight, "total_weight": total_weight,
                "addressed_count": len(addressed), "total_count": len(relevant),
                "cost": candidate["cost"], "estimated_hours": candidate["estimated_hours"]},
        "score": score,
        "score_display": round(score, 1),
    }


def rank_candidates(scenario: dict, state: DerivedState, weights: dict = DEFAULT_WEIGHTS) -> tuple[list[dict], list[dict]]:
    relevant = relevant_unresolved_gaps(scenario, state)
    ranked, excluded = [], []
    for c in scenario["candidates"]:
        rules = check_feasibility(scenario, state, c)
        if rules:
            excluded.append({"check_id": c["check_id"], "title": c["title"], "rule_ids": rules,
                             "human_reason": _reason(rules)})
            continue
        ranked.append({**_public_candidate(c), **score_candidate(c, relevant, weights),
                       "prior_evidence": state.evidence_by_check.get(c["check_id"], [])})
    ranked.sort(key=lambda r: (-r["score"], r["raw"]["cost"], r["raw"]["estimated_hours"], r["check_id"]))
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked, excluded


def _public_candidate(c: dict) -> dict:
    keys = ("check_id", "title", "gap_ids_addressable", "cost", "estimated_hours", "required_resources",
            "target_batch_ids", "allowed_statuses", "expected_result_schema", "limitations", "provenance")
    return {k: c.get(k) for k in keys}


def sensitivity(scenario: dict, state: DerivedState) -> dict:
    orders = {name: [r["check_id"] for r in rank_candidates(scenario, state, w)[0]]
              for name, w in SENSITIVITY_WEIGHTS.items()}
    base = orders["default"]
    runs = [{"weights_name": n, "weights": SENSITIVITY_WEIGHTS[n], "order": o,
             "same_top": bool(o and base and o[0] == base[0]), "same_order": o == base}
            for n, o in orders.items()]
    return {"stable_top": all(r["same_top"] for r in runs), "stable_order": all(r["same_order"] for r in runs), "runs": runs}


def build_plan(scenario: dict, state: DerivedState, version: int, weights: dict = DEFAULT_WEIGHTS) -> dict:
    ranked, excluded = rank_candidates(scenario, state, weights)
    relevant = relevant_unresolved_gaps(scenario, state)
    actions = [{"action_id": a["action_id"], "kind": a["kind"], "title": a["title"],
                "target_batch_ids": a["target_batch_ids"], "requires_role": a["requires_role"],
                **evaluate_action(scenario, state, a)} for a in scenario["actions"]]
    return {
        "incident_id": scenario["incident"]["id"],
        "version": version,
        "weights": weights,
        "normalizers": {"reference_cost": REFERENCE_COST, "reference_hours": REFERENCE_HOURS},
        "unresolved_gaps": sorted(relevant, key=lambda g: g["id"]),
        "resolved_gaps": sorted((g for g in state.gaps.values() if g["status"] == "RESOLVED"), key=lambda g: g["id"]),
        "restrictions": sorted(state.restrictions.values(), key=lambda r: r["id"]),
        "ranked_candidates": ranked,
        "excluded_candidates": excluded,
        "actions": actions,
        "sensitivity": sensitivity(scenario, state),
        "disclaimer": ("Scores are a documented deterministic heuristic for comparing checks under the same "
                       "normalizers. They are not probabilities or validated information gain. "
                       "A high rank does not authorize execution."),
    }
