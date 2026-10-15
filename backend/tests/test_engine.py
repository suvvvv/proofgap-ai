"""T01 traceability, T02 eligibility, T03 ranking — pure engine tests."""

import pytest

from app import engine as eng


def test_t01_traceability_exact_scope(scenario):
    state = eng.derive_state(scenario)
    assert [r["id"] for r in eng.affected_runs(scenario)] == ["PR-1042", "PR-1043"]
    assert eng.scope_batch_ids(scenario) == ["B-2202", "B-2203", "B-2204", "B-2205"]
    thread = eng.build_thread(scenario, state)
    ids = {n["id"] for n in thread["nodes"]}
    assert {"SO-7781", "SO-7782", "SO-7783", "SH-501"} <= ids
    assert not ids & {"B-2201", "B-2206", "PR-1041", "PR-1044", "SO-7780", "SO-7784"}
    reasons = {r["id"]: r["reason"] for r in thread["excluded_runs"]}
    assert reasons == {"PR-1041": "Outside anomaly window", "PR-1044": "Different machine"}


def test_t01_missing_link_is_unknown_not_safe(scenario):
    thread = eng.build_thread(scenario, eng.derive_state(scenario))
    b2205 = next(n for n in thread["nodes"] if n["id"] == "B-2205")
    assert b2205["trace_status"] == "UNKNOWN"
    assert {"source": "B-2205", "target": "UNKNOWN-ORDER-B-2205", "relation": "ALLOCATED_TO", "status": "UNKNOWN"} in thread["edges"]
    assert thread["unknown_relationships"][0]["batch_id"] == "B-2205"


def test_t02_feasibility_exclusions(scenario):
    plan = eng.build_plan(scenario, eng.derive_state(scenario), 1)
    excluded = {e["check_id"]: e["rule_ids"] for e in plan["excluded_candidates"]}
    assert excluded == {"C-07": ["F03"], "C-08": ["F04"], "C-10": ["F07"], "C-11": ["F07"]}
    actions = {a["action_id"]: a for a in plan["actions"]}
    assert actions["A-02"]["status"] == "BLOCKED" and actions["A-02"]["rule_ids"] == ["F01"]
    assert "Already shipped" in actions["A-02"]["human_reason"]
    assert actions["A-04"]["rule_ids"] == ["F02"]  # release cannot bypass outstanding review
    assert actions["A-06"]["rule_ids"] == ["F02", "F05"]
    assert actions["A-08"]["rule_ids"] == ["F06"]
    assert actions["A-05"]["status"] == "NOT_APPLICABLE"
    assert {a for a, v in actions.items() if v["status"] == "ELIGIBLE"} == {"A-01", "A-03", "A-07"}


def test_t03_ranking_formula_and_order(scenario):
    ranked, _ = eng.rank_candidates(scenario, eng.derive_state(scenario))
    assert [r["check_id"] for r in ranked] == ["C-01", "C-02", "C-03", "C-04"]
    c01 = ranked[0]
    # I = (3+2)/9, E = 2/4, C = 450/1000, T = 3/8
    expected = 100 * (0.4 * 5 / 9 + 0.3 * 0.5 - 0.2 * 0.45 - 0.1 * 0.375)
    assert c01["score"] == pytest.approx(expected)
    assert c01["score_display"] == 24.5
    assert c01["factors"] == pytest.approx({"I": 5 / 9, "E": 0.5, "C": 0.45, "T": 0.375})
    assert c01["raw"]["total_weight"] == 9 and c01["raw"]["addressed_count"] == 2


def test_t03_blueprint_example_and_tiebreak():
    relevant = [{"id": "G1", "weight": 3}, {"id": "G2", "weight": 1}]
    # Doc example arithmetic: I=.75,E=.5,C=.2,T=.25 -> 38.5
    cand = {"gap_ids_addressable": ["G1"], "cost": 200, "estimated_hours": 2}
    s = eng.score_candidate(cand, relevant)
    assert s["factors"] == pytest.approx({"I": 0.75, "E": 0.5, "C": 0.2, "T": 0.25})
    assert s["score_display"] == 38.5
    sc = {"incident": {"machine_id": "M", "window": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"}},
          "production_runs": [], "batches": [], "resources": [], "gaps": [{**g, "status": "UNRESOLVED", "batch_ids": []} for g in relevant],
          "candidates": [{"check_id": cid, "title": cid, "gap_ids_addressable": ["G1"], "cost": cost, "estimated_hours": 1,
                          "required_resources": [], "target_batch_ids": []} for cid, cost in (("Z", 100), ("A", 100))]}
    ranked, _ = eng.rank_candidates(sc, eng.derive_state(sc))
    assert [r["check_id"] for r in ranked] == ["A", "Z"]  # equal score/cost/time -> lexical check_id


def test_negative_scores_allowed():
    s = eng.score_candidate({"gap_ids_addressable": [], "cost": 5000, "estimated_hours": 20}, [{"id": "G1", "weight": 1}])
    assert s["score"] == pytest.approx(-30.0)
