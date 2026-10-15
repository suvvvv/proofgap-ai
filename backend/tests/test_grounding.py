"""T06 grounding: adversarial model outputs are stripped or rejected."""

import json
import time

import pytest

from app import engine as eng
from app.ai import gemini, grounding


@pytest.fixture()
def payload(scenario):
    state = eng.derive_state(scenario)
    plan = eng.build_plan(scenario, state, 1)
    thread = eng.build_thread(scenario, state)
    return grounding.build_payload(scenario, state, plan, thread, [])


def good(**over):
    base = {
        "summary": "INC-M04-001: vibration reading SR-90017 exceeded threshold on M-04.",
        "verified_facts": [{"claim": "PR-1042 produced B-2203 inside the window.", "record_ids": ["PR-1042", "B-2203"]}],
        "hypotheses": [{"claim": "Spindle bearing wear may explain the vibration.", "uncertainty": "Unconfirmed until C-03."}],
        "missing_evidence": [{"gap_id": "G-01", "why_it_matters": "Confirms the machine fault."}],
        "recommendation_rationale": "C-01 ranks first because it addresses G-02 and G-03.",
        "limitations": "Synthetic data; sample-based inspection.",
    }
    base.update(over)
    return base


def run(payload, output):
    return gemini.explain(payload, lambda _p: output if isinstance(output, str) else json.dumps(output), timeout_s=2)


def test_payload_is_curated(payload):
    assert "SR-90017" in payload["allowed_record_ids"] and "B-2206" not in payload["allowed_record_ids"]
    assert payload["evidence_version"] == 1
    assert not any("key" in k.lower() for k in payload)


def test_valid_response_passes(payload):
    res = run(payload, good())
    assert res["status"] == "ok" and res["stripped"] == []
    assert res["explanation"]["verified_facts"][0]["record_ids"] == ["PR-1042", "B-2203"]


def test_unknown_batch_hallucination_stripped(payload):
    res = run(payload, good(verified_facts=[
        {"claim": "B-9999 was also produced on M-04.", "record_ids": ["B-9999"]},
        {"claim": "B-2203 is in the warehouse.", "record_ids": ["B-2203"]}]))
    assert res["status"] == "ok"
    assert [f["claim"] for f in res["explanation"]["verified_facts"]] == ["B-2203 is in the warehouse."]
    assert "B-9999" in res["stripped"][0]["reason"]


def test_unknown_id_in_summary_rejected(payload):
    res = run(payload, good(summary="Batch B-7777 is affected."))
    assert res["status"] == "unavailable" and "unknown record IDs" in res["reason"]


def test_causal_assertion_without_proof_stripped(payload):
    res = run(payload, good(verified_facts=[{"claim": "Bearing wear on M-04 caused the defects in B-2204.", "record_ids": ["M-04", "B-2204"]}]))
    assert res["explanation"]["verified_facts"] == []
    assert res["stripped"][0]["reason"] == "causal assertion presented as fact"


def test_fabricated_probability(payload):
    assert run(payload, good(recommendation_rationale="There is an 83% chance B-2204 is defective."))["status"] == "unavailable"
    res = run(payload, good(hypotheses=[{"claim": "Defect probability is high", "uncertainty": "about 70%"}]))
    assert res["explanation"]["hypotheses"] == []


def test_ship_without_review_rejected(payload):
    res = run(payload, good(recommendation_rationale="Ship B-2203 now without inspection to protect the delivery date."))
    assert res["status"] == "unavailable" and "bypassing" in res["reason"]


def test_missing_evidence_must_be_unresolved_gap(payload):
    res = run(payload, good(missing_evidence=[{"gap_id": "G-00", "why_it_matters": "already resolved"},
                                              {"gap_id": "G-03", "why_it_matters": "PR-1043 output"}]))
    assert [m["gap_id"] for m in res["explanation"]["missing_evidence"]] == ["G-03"]


def test_malformed_json(payload):
    res = run(payload, "{not json")
    assert res["status"] == "unavailable" and "Malformed" in res["reason"]
    res = run(payload, {"summary": "missing fields"})
    assert res["status"] == "unavailable"


def test_model_timeout(payload):
    def slow(_p):
        time.sleep(3)
        return json.dumps(good())
    res = gemini.explain(payload, slow, timeout_s=0.2)
    assert res["status"] == "unavailable" and "timed out" in res["reason"]


def test_not_configured(payload):
    res = gemini.explain(payload, None)
    assert res["status"] == "unavailable" and res["fallback"]["recommendation_rationale"].startswith("Top-ranked")


def test_mentioning_probabilities_is_not_a_probability_claim(payload):
    res = run(payload, good(limitations="Scores are a deterministic heuristic, not defect probabilities."))
    assert res["status"] == "ok"


def test_cache_reuses_validated_explanation_only(payload):
    calls = []

    def fn(_p):
        calls.append(1)
        return json.dumps(good())

    gemini._cache.clear()
    a = gemini.explain(payload, fn, timeout_s=2, use_cache=True)
    b = gemini.explain(payload, fn, timeout_s=2, use_cache=True)
    assert a["status"] == b["status"] == "ok" and b["cached"] is True and len(calls) == 1
    gemini._cache.clear()
    gemini.explain(payload, lambda _p: "{bad", timeout_s=2, use_cache=True)
    assert not gemini._cache  # failures are never cached
