# ProofGap AI

**Challenge:** Manufacturing — Intelligent Operations & Industrial Efficiency · AI Builder Cup 2026

When a machine alarm threatens downstream production, ProofGap helps a factory team:

1. trace exactly which runs, batches, orders and shipments are affected,
2. find the evidence gaps that block a decision,
3. pick the next most useful check from those that are actually feasible, with the math shown,
4. record the result and watch the plan recompute from persisted state, and
5. make a reviewable, audited decision.

Gemini explains the plan in grounded language. It is not the decision engine.

> **Boundary:** this is a prototype for decision support, built on synthetic data. It is not certified quality assurance, defect prediction or machine control. Scores are a documented deterministic heuristic, not probabilities. Approvals are **SIMULATED**: demo identities, not a security control.

## Architecture

```
Firebase Hosting (React + TS)  ──/api rewrite──▶  Cloud Run: FastAPI (Python)  ──▶  Cloud Firestore
  renders server values         ├─ engine.py      deterministic traceability, gaps, F01–F07 rules, ranking
  never recomputes scores       ├─ service.py     transactions, optimistic versioning (409), append-only audit
                                ├─ auth.py        SIMULATED demo identity → role looked up server-side (403)
                                ├─ ai/grounding   curated payload + strict validator (strips unknown IDs, probabilities, causal claims)
                                ├─ ai/gemini      google-genai structured output, timeout, deterministic fallback
                                └─ baseline.py    T08 reproducible strategy comparison
                              stores/: Firestore (STORE=firestore, deployed) or SQL (SQLite locally / Postgres)
                              Gemini via google-genai (explanations only)
```

**Trust boundary.** The browser never supplies authorization truth: role and approver fields in request bodies are ignored. The backend owns traceability, constraints, scores, persistence and audit. Gemini gets curated evidence and can only return an explanation, which is checked against the record IDs in the payload.

## Run locally

```bash
# backend
cd backend
uv venv --python 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt   # or python -m venv + pip
.venv/bin/python -m pytest              # T01–T08
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm ci && npm run dev    # http://localhost:5173 (proxies /api to :8000)
```

Optional Gemini: `export GEMINI_API_KEY=...` (Google AI Studio), or `GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=...`. The model is set with `GEMINI_MODEL` (default `gemini-2.5-flash`). If Gemini isn't configured, or fails, the panel says *AI explanation unavailable* and everything else keeps working.

## Deploy (Cloud Run + Firestore + Firebase Hosting)

```bash
printf %s "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- --project <project>
firebase login
./scripts/deploy.sh <project> asia-south1 <gcloud-account>   # enables APIs, creates Firestore, deploys, smoke-tests
```

Cloud Run runs with `STORE=firestore`, so evidence, approvals and the audit log persist in Firestore transactions. Firebase Hosting serves the UI and rewrites `/api/**` to the Cloud Run service. Browsers never access Firestore directly (`firestore.rules` denies all). Keep secrets in Secret Manager, never in the repo or the UI. Run the Firestore tests locally with the emulator: `FIRESTORE_EMULATOR_HOST=localhost:8085 pytest`.

## API v1

| Method / path | Notes |
|---|---|
| `GET /api/incidents/{id}` | summary, version, sensor provenance |
| `GET /api/incidents/{id}/thread` | typed nodes/edges, UNKNOWN relationships, excluded runs |
| `GET /api/incidents/{id}/plan` | unresolved gaps, ranked checks with I/E/C/T, excluded checks, action eligibility, weight sensitivity |
| `POST /api/incidents/{id}/evidence` | `{check_id, result, batch_id?, expected_version, supersedes_id?}`; returns 409 for a stale version, an ineligible check or a duplicate |
| `POST /api/incidents/{id}/explain` | `{expected_version}`: grounded explanation, or a fallback if Gemini is unavailable |
| `POST /api/incidents/{id}/approve` | `{action_id, expected_version, justification}`; returns 403 for the wrong role, 409 for a stale version or an ineligible action |
| `GET /api/incidents/{id}/audit` | append-only event timeline |
| `GET /api/baseline` | T08 report |
| `GET /api/health` | status (no secrets) |

Errors are `{code, message, details}`. The canonical OpenAPI spec is served at `/docs` and `/openapi.json`.

## Ranking (prototype heuristic)

`score = 100 × (0.40·I + 0.30·E − 0.20·C − 0.10·T)`

- **I:** share of unresolved gap weight that the check addresses.
- **E:** share of unresolved gaps it addresses.
- **C:** cost ÷ 1000.
- **T:** hours ÷ 8.

All factors are clamped to [0, 1]. Feasibility rules F01–F07 run **before** scoring. Ties break on lower cost, then shorter time, then `check_id`. The UI shows sensitivity to four alternative weight sets. In the seed, the top choice changes under some weightings, and the UI says so.

## Demo script (3 min)

1. **Incident:** M-04 reads 9.8 mm/s against a 7.1 threshold (record SR-90017). The window runs from 06:00 to 10:00Z.
2. **Graph:** PR-1042 and PR-1043 lead to batches B-2202…B-2205. B-2202 has shipped (SH-501), and B-2205's order link is **UNKNOWN**.
3. **Plan:** C-01 > C-02 > C-03 > C-04. The CT scan is excluded (F03), and the hold on shipped batch B-2202 is excluded (F01).
4. **Evidence:** record **C-02 PASS**. G-02 is resolved, C-01's coverage drops, and the order becomes C-03 > C-04 > C-01 (persisted, so it survives a reload). Then record **C-01 FAIL**. That creates gap G-04 and restriction MRB-B-2204, makes C-11 eligible, and blocks release A-04 (F02). Recording **INCONCLUSIVE** on C-03 leaves the rank unchanged.
5. **Gemini:** grounded summary with cited record IDs. Any claim the validator strips is shown.
6. **Approval:** the demo operator gets 403. The demo quality manager approves A-01 and gets a work order. The audit timeline shows the actor, role, versions and `simulated`.
7. **Baseline:** six synthetic cases with fixed outcomes. ProofGap has 0 policy violations and less unresolved gap weight left. S5 and S6 are ties, kept in the report, and S6 shows that greedy ranking isn't optimal.

## Test scorecard

| Test | Where |
|---|---|
| T01 traceability | `tests/test_engine.py::test_t01_*` |
| T02 eligibility | `tests/test_engine.py::test_t02_*` |
| T03 ranking | `tests/test_engine.py::test_t03_*` |
| T04 re-ranking | `tests/test_api.py::test_t04_*` |
| T05 governance | `tests/test_api.py::test_t05_governance` |
| T06 grounding | `tests/test_grounding.py` (unknown batch, causal claim, probability, ship-without-review, malformed JSON, timeout) |
| T07 resilience | `tests/test_api.py::test_t07_resilience_without_gemini` |
| T08 baseline | `tests/test_baseline.py`, `python -m app.baseline` |
| T09 deployment | `scripts/smoke.sh <url>` |

Live Gemini output still has to be evaluated with a real key. The T06 tests use adversarial model stubs.

## Docs

- `docs/ProofGap_AI_Final_Implementation_Blueprint.docx`: the implementation blueprint
- `docs/SUBMISSION.md`: portal fields, brief description, video script, deck outline, checklist
- `docs/TEAM_TASKS_GEMINI.md`: tasks for the Gemini/AI owner (live evaluation with `python -m app.ai.live_eval`)

Product novelty: related quality agents, digital-thread tools and inspection-planning research already exist. ProofGap doesn't claim to be the first. Its methodology is a practical hackathon heuristic and would need real validation before any industrial use.
