"""T04 re-ranking on persisted evidence, T05 governance, T07 resilience."""

from conftest import INC, OP, QM


def _plan(client):
    return client.get(f"/api/incidents/{INC}/plan").json()


def _order(plan):
    return [r["check_id"] for r in plan["ranked_candidates"]]


def test_contract_shapes(client):
    inc = client.get(f"/api/incidents/{INC}").json()
    assert inc["version"] == 1 and inc["sensor"]["record_id"] == "SR-90017"
    assert client.get("/healthz").json()["status"] == "ok"
    err = client.get("/api/incidents/NOPE").json()
    assert set(err) == {"code", "message", "details"} and err["code"] == "INCIDENT_NOT_FOUND"


def test_t04_pass_resolves_gap_and_reranks_persistently(client):
    p1 = _plan(client)
    assert _order(p1) == ["C-01", "C-02", "C-03", "C-04"]
    c01_before = next(r for r in p1["ranked_candidates"] if r["check_id"] == "C-01")
    r = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                    json={"check_id": "C-02", "result": "PASS", "batch_id": "B-2203", "expected_version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["version"] == 2

    p2 = _plan(client)  # fresh GET = "reload"
    assert p2["version"] == 2
    assert "G-02" not in {g["id"] for g in p2["unresolved_gaps"]}
    assert _order(p2) == ["C-03", "C-04", "C-01"]
    c01_after = next(r for r in p2["ranked_candidates"] if r["check_id"] == "C-01")
    assert c01_after["gap_ids_addressed"] == ["G-03"]
    assert c01_after["factors"]["E"] < c01_before["factors"]["E"]
    assert {"check_id": "C-02", "rule_ids": ["F07"]}.items() <= next(
        e for e in p2["excluded_candidates"] if e["check_id"] == "C-02").items()


def test_t04_inconclusive_does_not_change_rank(client):
    before = _plan(client)
    r = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                    json={"check_id": "C-03", "result": "INCONCLUSIVE", "expected_version": 1})
    assert r.status_code == 200
    after = _plan(client)
    assert after["version"] == 2
    assert _order(after) == _order(before)
    assert [g["id"] for g in after["unresolved_gaps"]] == [g["id"] for g in before["unresolved_gaps"]]


def test_t04_fail_creates_review_gap_and_changes_feasibility(client):
    client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                json={"check_id": "C-02", "result": "PASS", "expected_version": 1})
    r = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                    json={"check_id": "C-01", "result": "FAIL", "batch_id": "B-2204", "expected_version": 2})
    assert r.status_code == 200
    p = _plan(client)
    assert "G-04" in {g["id"] for g in p["unresolved_gaps"]}
    assert _order(p) == ["C-03", "C-11", "C-04"]  # C-11 was F07 before the FAIL
    assert [x["id"] for x in p["restrictions"]] == ["MRB-B-2204"]
    actions = {a["action_id"]: a for a in p["actions"]}
    assert actions["A-04"]["status"] == "BLOCKED" and "F02" in actions["A-04"]["rule_ids"]
    assert actions["A-05"]["status"] == "ELIGIBLE"


def test_duplicate_and_supersede(client):
    client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                json={"check_id": "C-03", "result": "INCONCLUSIVE", "expected_version": 1})
    dup = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                      json={"check_id": "C-03", "result": "PASS", "expected_version": 2})
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_EVIDENCE"
    ok = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                     json={"check_id": "C-03", "result": "PASS", "expected_version": 2, "supersedes_id": "EV-0001"})
    assert ok.status_code == 200
    assert "G-01" not in {g["id"] for g in _plan(client)["unresolved_gaps"]}


def test_evidence_validation_and_ineligible(client):
    bad = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                      json={"check_id": "C-02", "result": "MAYBE", "expected_version": 1})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_FAILED"
    blocked = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                          json={"check_id": "C-07", "result": "PASS", "expected_version": 1})
    assert blocked.status_code == 409 and blocked.json()["details"]["rule_ids"] == ["F03"]
    stale = client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                        json={"check_id": "C-02", "result": "PASS", "expected_version": 7})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    anon = client.post(f"/api/incidents/{INC}/evidence", json={"check_id": "C-02", "result": "PASS", "expected_version": 1})
    assert anon.status_code == 401


def test_t05_governance(client):
    body = {"action_id": "A-01", "expected_version": 1, "justification": "Contain warehouse stock"}
    forbidden = client.post(f"/api/incidents/{INC}/approve", headers=OP, json={**body, "role": "QUALITY_MANAGER", "approved_by": "u-qm-1"})
    assert forbidden.status_code == 403  # body role/approver fields are ignored
    stale = client.post(f"/api/incidents/{INC}/approve", headers=QM, json={**body, "expected_version": 0})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    blocked = client.post(f"/api/incidents/{INC}/approve", headers=QM,
                          json={"action_id": "A-02", "expected_version": 1, "justification": "try shipped hold"})
    assert blocked.status_code == 409 and blocked.json()["details"]["rule_ids"] == ["F01"]

    ok = client.post(f"/api/incidents/{INC}/approve", headers=QM, json=body)
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert data["simulated"] is True and data["approval"]["work_order_id"].startswith("WO-")
    assert data["plan"]["version"] == 2

    events = client.get(f"/api/incidents/{INC}/audit").json()["events"]
    ev = events[-1]
    assert ev["event_type"] == "APPROVAL_RECORDED" and ev["actor_id"] == "u-qm-1"
    assert ev["actor_role"] == "QUALITY_MANAGER" and ev["simulation"] is True
    assert ev["previous_version"] == 1 and ev["new_version"] == 2
    assert ev["new_state"]["batch_status"]["B-2203"] == "ON_HOLD"
    assert ev["created_at"].endswith("Z")
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)

    again = client.post(f"/api/incidents/{INC}/approve", headers=QM, json={**body, "expected_version": 2})
    assert again.status_code == 409 and again.json()["details"]["status"] == "APPROVED"


def test_mrb_review_clears_restriction(client):
    client.post(f"/api/incidents/{INC}/evidence", headers=OP, json={"check_id": "C-01", "result": "FAIL", "expected_version": 1})
    r = client.post(f"/api/incidents/{INC}/approve", headers=QM,
                    json={"action_id": "A-05", "expected_version": 2, "justification": "MRB: rework"})
    assert r.status_code == 200
    assert r.json()["plan"]["restrictions"] == []


def test_t07_resilience_without_gemini(client):
    def boom(_payload):
        raise RuntimeError("network down")

    from app.main import app_state
    app_state["model_fn"] = boom
    exp = client.post(f"/api/incidents/{INC}/explain", json={"expected_version": 1}).json()
    assert exp["status"] == "unavailable" and "AI explanation unavailable" in exp["message"]
    assert exp["fallback"]["missing_evidence"]
    # Everything deterministic still works after the AI failure.
    assert client.get(f"/api/incidents/{INC}/thread").status_code == 200
    assert client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                       json={"check_id": "C-02", "result": "PASS", "expected_version": 1}).status_code == 200
    assert client.post(f"/api/incidents/{INC}/approve", headers=QM,
                       json={"action_id": "A-07", "expected_version": 2, "justification": "maintenance"}).status_code == 200


def test_reset_requires_admin(client):
    assert client.post("/api/admin/reset", headers=QM).status_code == 403
    assert client.post("/api/admin/reset", headers={"X-Demo-User": "u-admin-1"}).status_code == 200


def test_concurrent_writes_one_wins(client):
    from concurrent.futures import ThreadPoolExecutor

    def submit(check_id):
        return client.post(f"/api/incidents/{INC}/evidence", headers=OP,
                           json={"check_id": check_id, "result": "PASS", "expected_version": 1}).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = sorted(pool.map(submit, ["C-02", "C-03", "C-04", "C-01"]))
    assert codes.count(200) == 1 and codes.count(409) == 3
    assert _plan(client)["version"] == 2
