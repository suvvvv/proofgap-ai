"""T08 baseline report is reproducible and honest."""

from app import baseline


def test_t08_reproducible_and_keeps_non_wins():
    a, b = baseline.run(), baseline.run()
    assert a == b
    assert len(a["cases"]) == 6
    assert a["totals"]["proofgap"]["policy_violations"] == 0
    # The report must keep the cases where ProofGap only ties a baseline.
    assert {c["case_id"] for c in a["not_better_cases"]} == {"S5", "S6"}
    for row in a["cases"]:
        assert row["results"]["proofgap"]["cost"] <= row["budget"]
