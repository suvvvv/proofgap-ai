"""T08 baseline: ProofGap planner vs. naive strategies on fixed synthetic cases.

Every case is synthetic with seeded ground-truth inspection outcomes. Each
strategy spends the same fixed budget; we report inspections, synthetic cost,
synthetic hours, mandatory-policy violations and unresolved evidence left.
Cases where ProofGap does not beat a baseline are kept in the report.

Run: python -m app.baseline
"""

from __future__ import annotations

import json

from . import engine as eng

WINDOW = {"start": "2026-10-14T06:00:00Z", "end": "2026-10-14T10:00:00Z", "basis": "synthetic"}


def make_case(case_id: str, description: str, budget: float, batches: list[tuple], gaps: list[tuple],
              checks: list[dict]) -> dict:
    """batches: (id, in_window, status, has_order); gaps: (id, weight, batch_ids)."""
    scenario = {
        "scenario_id": case_id,
        "incident": {"id": f"INC-{case_id}", "machine_id": "M-X", "window": WINDOW},
        "machines": [{"id": "M-X", "name": "Synthetic machine"}],
        "production_runs": [
            {"id": "R-IN", "machine_id": "M-X", "start": "2026-10-14T06:00:00Z", "end": "2026-10-14T10:00:00Z"},
            {"id": "R-OUT", "machine_id": "M-X", "start": "2026-10-14T02:00:00Z", "end": "2026-10-14T05:55:00Z"},
        ],
        "batches": [{"id": b, "run_id": "R-IN" if inw else "R-OUT", "qty": 100, "status": st,
                     "order_id": f"SO-{b}" if has_order else None} for b, inw, st, has_order in batches],
        "resources": [{"id": "OK", "available": True}, {"id": "DOWN", "available": False}],
        "gaps": [{"id": g, "title": g, "weight": w, "decision_relevant": True, "batch_ids": bs, "status": "UNRESOLVED"}
                 for g, w, bs in gaps],
        "gap_templates": {}, "restriction_templates": {}, "actions": [],
        "candidates": [],
    }
    truth = {}
    for c in checks:
        scenario["candidates"].append({
            "check_id": c["id"], "title": c["id"], "gap_ids_addressable": c["gaps"], "cost": c["cost"],
            "estimated_hours": c["hours"], "required_resources": ["DOWN" if c.get("down") else "OK"],
            "target_batch_ids": c.get("targets", []), "allowed_statuses": ["IN_WAREHOUSE", "WIP", "ON_HOLD"] if c.get("targets") else [],
            "violates_rules": ["QR-SYN"] if c.get("violates") else [],
            "on_result": {"PASS": {"resolves": c["gaps"]}, "FAIL": {"resolves": c["gaps"]}},
        })
        truth[c["id"]] = c.get("truth", "PASS")
    return {"id": case_id, "description": description, "budget": budget, "scenario": scenario, "truth": truth}


CASES = [
    make_case("S1", "M-04-like: shipped batch, one missing order link, overlapping checks", 700,
              [("B1", True, "SHIPPED", True), ("B2", True, "IN_WAREHOUSE", True), ("B3", True, "IN_WAREHOUSE", True),
               ("B4", True, "WIP", False), ("B0", False, "IN_WAREHOUSE", True)],
              [("G1", 3, []), ("G2", 3, ["B1", "B2"]), ("G3", 2, ["B3", "B4"]), ("G4", 1, ["B4"])],
              [{"id": "K1", "gaps": ["G2", "G3"], "cost": 450, "hours": 3, "targets": ["B2", "B3"], "truth": "FAIL"},
               {"id": "K2", "gaps": ["G2"], "cost": 120, "hours": 1, "targets": ["B2"]},
               {"id": "K3", "gaps": ["G1"], "cost": 200, "hours": 1.5},
               {"id": "K4", "gaps": ["G4"], "cost": 50, "hours": 0.5, "targets": ["B4"]},
               {"id": "K5", "gaps": ["G3"], "cost": 800, "hours": 6, "targets": ["B3"], "down": True},
               {"id": "K0", "gaps": ["G2"], "cost": 300, "hours": 2, "targets": ["B0"]}]),
    make_case("S2", "Out-of-window decoy batches dominate the naive list", 600,
              [("B0", False, "IN_WAREHOUSE", True), ("B1", False, "IN_WAREHOUSE", True), ("B5", True, "IN_WAREHOUSE", True),
               ("B6", True, "IN_WAREHOUSE", True)],
              [("G1", 3, ["B5"]), ("G2", 2, ["B6"])],
              [{"id": "K0", "gaps": ["G1"], "cost": 200, "hours": 2, "targets": ["B0"]},
               {"id": "K1", "gaps": ["G1"], "cost": 200, "hours": 2, "targets": ["B1"]},
               {"id": "K5", "gaps": ["G1"], "cost": 200, "hours": 2, "targets": ["B5"]},
               {"id": "K6", "gaps": ["G2"], "cost": 150, "hours": 1, "targets": ["B6"]}]),
    make_case("S3", "Severity-first picks an unavailable and a prohibited check", 500,
              [("B1", True, "IN_WAREHOUSE", True), ("B2", True, "IN_WAREHOUSE", True)],
              [("G1", 3, ["B1"]), ("G2", 2, ["B2"]), ("G3", 1, [])],
              [{"id": "K1", "gaps": ["G1"], "cost": 300, "hours": 4, "targets": ["B1"], "down": True},
               {"id": "K2", "gaps": ["G1", "G2"], "cost": 250, "hours": 2, "targets": ["B1", "B2"], "violates": True},
               {"id": "K3", "gaps": ["G1"], "cost": 220, "hours": 2, "targets": ["B1"]},
               {"id": "K4", "gaps": ["G2"], "cost": 100, "hours": 1, "targets": ["B2"]},
               {"id": "K5", "gaps": ["G3"], "cost": 80, "hours": 1}]),
    make_case("S4", "Single machine-level gap; every strategy needs one check", 400,
              [("B1", True, "IN_WAREHOUSE", True)],
              [("G1", 3, [])],
              [{"id": "K1", "gaps": ["G1"], "cost": 150, "hours": 1},
               {"id": "K2", "gaps": ["G1"], "cost": 200, "hours": 1}]),
    make_case("S5", "Inconclusive first result on the cheapest check", 600,
              [("B1", True, "IN_WAREHOUSE", True), ("B2", True, "WIP", True)],
              [("G1", 2, ["B1"]), ("G2", 2, ["B2"]), ("G3", 1, [])],
              [{"id": "K1", "gaps": ["G1", "G2"], "cost": 100, "hours": 1, "targets": ["B1", "B2"], "truth": "INCONCLUSIVE"},
               {"id": "K2", "gaps": ["G1"], "cost": 150, "hours": 1, "targets": ["B1"]},
               {"id": "K3", "gaps": ["G2"], "cost": 150, "hours": 1, "targets": ["B2"]},
               {"id": "K4", "gaps": ["G3"], "cost": 300, "hours": 3}]),
    make_case("S6", "Expensive comprehensive check vs. cheap partial checks", 900,
              [("B1", True, "IN_WAREHOUSE", True), ("B2", True, "IN_WAREHOUSE", True), ("B3", True, "SHIPPED", True)],
              [("G1", 2, ["B1"]), ("G2", 2, ["B2"]), ("G3", 2, ["B3"])],
              [{"id": "K1", "gaps": ["G1", "G2"], "cost": 700, "hours": 6, "targets": ["B1", "B2"]},
               {"id": "K2", "gaps": ["G1"], "cost": 250, "hours": 2, "targets": ["B1"]},
               {"id": "K3", "gaps": ["G2"], "cost": 250, "hours": 2, "targets": ["B2"]},
               {"id": "K4", "gaps": ["G3"], "cost": 300, "hours": 2}]),
]


def _execute(case: dict, order_fn, blanket_hold: bool = False, feasible_only: bool = False) -> dict:
    sc, truth, budget = case["scenario"], case["truth"], case["budget"]
    evidence: list[dict] = []
    done: set[str] = set()
    spent = hours = 0.0
    violations = infeasible_attempts = 0
    log: list[str] = []
    if blanket_hold:
        for b in sc["batches"]:
            if b["status"] == "SHIPPED":
                violations += 1  # F01: on-site hold on shipped inventory
                log.append(f"HOLD {b['id']} (violates F01)")
    while True:
        state = eng.derive_state(sc, evidence)
        pick = None
        for cid in order_fn(sc, state):
            c = next(x for x in sc["candidates"] if x["check_id"] == cid)
            if cid in done or spent + c["cost"] > budget:
                continue
            pick = c
            break
        if pick is None:
            break
        done.add(pick["check_id"])
        rules = eng.check_feasibility(sc, state, pick)
        if feasible_only:
            assert not rules
        if "F03" in rules:
            infeasible_attempts += 1
            log.append(f"{pick['check_id']} not executable (F03)")
            continue
        if "F06" in rules:
            violations += 1
        spent += pick["cost"]
        hours += pick["estimated_hours"]
        evidence.append({"id": f"E{len(evidence) + 1}", "check_id": pick["check_id"], "result": truth[pick["check_id"]],
                         "version": len(evidence) + 2})
        log.append(f"{pick['check_id']} -> {truth[pick['check_id']]}" + (f" (rules {rules})" if rules else ""))
    final = eng.derive_state(sc, evidence)
    left = eng.relevant_unresolved_gaps(sc, final)
    return {"inspections": len(evidence), "cost": spent, "hours": hours, "policy_violations": violations,
            "infeasible_attempts": infeasible_attempts, "unresolved_gaps": len(left),
            "unresolved_weight": sum(g["weight"] for g in left), "log": log}


def _proofgap_order(sc, state):
    return [r["check_id"] for r in eng.rank_candidates(sc, state)[0]]


def _naive_order(sc, state):
    def key(c):
        return (0, c["target_batch_ids"][0]) if c["target_batch_ids"] else (1, c["check_id"])
    return [c["check_id"] for c in sorted(sc["candidates"], key=key)]


def _severity_order(sc, state):
    weights = {g["id"]: g["weight"] for g in sc["gaps"]}
    return [c["check_id"] for c in sorted(sc["candidates"],
                                          key=lambda c: (-max(weights[g] for g in c["gap_ids_addressable"]), c["check_id"]))]


STRATEGIES = {
    "proofgap": lambda case: _execute(case, _proofgap_order, feasible_only=True),
    "naive_all_batches": lambda case: _execute(case, _naive_order, blanket_hold=True),
    "severity_first": lambda case: _execute(case, _severity_order),
}


def run() -> dict:
    rows = []
    for case in CASES:
        results = {name: fn(case) for name, fn in STRATEGIES.items()}
        pg = results["proofgap"]
        verdicts = {}
        for name in ("naive_all_batches", "severity_first"):
            b = results[name]
            pg_key = (pg["policy_violations"], pg["unresolved_weight"], pg["cost"])
            b_key = (b["policy_violations"], b["unresolved_weight"], b["cost"])
            verdicts[name] = "better" if pg_key < b_key else "tie" if pg_key == b_key else "worse"
        rows.append({"case_id": case["id"], "description": case["description"], "budget": case["budget"],
                     "results": results, "proofgap_vs": verdicts})
    totals = {name: {k: sum(r["results"][name][k] for r in rows)
                     for k in ("inspections", "cost", "hours", "policy_violations", "infeasible_attempts",
                               "unresolved_gaps", "unresolved_weight")}
              for name in STRATEGIES}
    return {
        "method": ("Fixed synthetic cases with seeded ground-truth outcomes; each strategy spends the same budget and "
                   "runs each check at most once. Comparison key per case: (policy violations, unresolved gap "
                   "weight, cost), lower is better. Synthetic currency/hours; no real-world savings are claimed."),
        "cases": rows,
        "totals": totals,
        "not_better_cases": [{"case_id": r["case_id"], "vs": {k: v for k, v in r["proofgap_vs"].items() if v != "better"}}
                             for r in rows if any(v != "better" for v in r["proofgap_vs"].values())],
    }


if __name__ == "__main__":
    report = run()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    for r in report["cases"]:
        print(f"\n{r['case_id']} {r['description']} (budget {r['budget']})")
        for name, res in r["results"].items():
            print(f"  {name:18} insp={res['inspections']} cost={res['cost']:.0f} h={res['hours']:.1f} "
                  f"viol={res['policy_violations']} unresolved={res['unresolved_gaps']}(w{res['unresolved_weight']})  {res['log']}")
        print("  proofgap vs:", r["proofgap_vs"])
