# Submission kit: Hack2skill portal (closes 18 Oct 2026, 11:59 PM IST)

## Portal fields

| Field | Value / status |
|---|---|
| Challenge | **Manufacturing — Intelligent Operations & Industrial Efficiency** |
| Prototype link (GCP / Cloud Run) | Firebase Hosting URL `https://<project>.web.app` (UI + API through Cloud Run), or the Cloud Run URL. Fill in after `scripts/deploy.sh`. |
| Deck PDF (≤ 5 MB) | Use the **prescribed template** from the portal's "Download" link. Export to PDF. |
| GitHub (public) | https://github.com/suvvvv/proofgap-ai |
| Demo video (3–4 min) | YouTube unlisted or public Drive link. Test it in an incognito window. |
| Brief description (≤ 1024 chars) | Below. 963 characters. |

### Brief description (paste as is)

> ProofGap AI helps a factory team answer a machine alarm with evidence, not guesswork. For a vibration alarm on CNC lathe M-04 it deterministically traces affected runs, batches, orders and shipments (missing links shown as UNKNOWN, never safe), lists open evidence gaps, removes infeasible or prohibited actions (e.g. holding an already-shipped batch) and ranks the remaining inspections with a transparent coverage/cost/time formula. Results are persisted and the plan recomputes; approvals are versioned and audited. Google services: Gemini (google-genai, structured JSON) writes a grounded explanation citing only real record IDs; a validator strips hallucinated IDs, probabilities and unsafe advice, with a non-AI fallback. Cloud Run hosts the FastAPI API and React UI. Cloud Firestore stores evidence, approvals and the append-only audit log in transactions. Firebase Hosting serves the UI and routes /api to Cloud Run. Synthetic data; decision support only.

Each statement above must be true on the deployed build. Before pasting, open `/healthz` on the live URL and check that `"store": "firestore"` and `"gemini_configured": true`. The footer of the app shows the same.

## Required tech: where each one is used

| Service | Where in the code | How to verify live |
|---|---|---|
| **Gemini** | `backend/app/ai/gemini.py`, `grounding.py` | Click "Generate grounded explanation"; the source shows the model name |
| **Cloud Run** | `Dockerfile`, `scripts/deploy.sh` | `/healthz` → `"runtime": "cloud_run"` |
| **Firestore** | `backend/app/stores/firestore.py` (transactions, audit sequence) | `/healthz` → `"store": "firestore"`; Firestore console shows `incidents/INC-M04-001/audit` |
| **Firebase** | `firebase.json` (Hosting + rewrites to Cloud Run), `firestore.rules` | `https://<project>.web.app` loads the app |

## Owner checklist

- [ ] Choose the GCP project from your **personal** account (not the work one). Billing must be on.
- [ ] Get the Gemini key from your friend and store it in Secret Manager as `gemini-api-key`.
- [ ] `firebase login` (personal account), then `./scripts/deploy.sh <project> asia-south1 suvarnasanapathi2001@gmail.com`
- [ ] `./scripts/smoke.sh <url>` passes on the **Firebase** URL and the **Cloud Run** URL.
- [ ] Reset the demo data before recording and before submitting: select Demo Admin, then click "Reset demo".
- [ ] Record the video (script below), 3:00–3:50 long.
- [ ] Fill the deck template (outline below) and export a PDF under 5 MB.
- [ ] Friend commits `docs/gemini_eval_results.md` (see `TEAM_TASKS_GEMINI.md`).
- [ ] Open every link in incognito. Submit early and screenshot the confirmation.
- [ ] Keep the Cloud Run service up until evaluation ends. `--min-instances 1` avoids cold starts; don't delete the project.

## Video script (about 3:30)

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Incident card | "9.8 mm/s vibration on M-04 versus a 7.1 limit. Three customer orders, and one batch already shipped." |
| 0:25–0:55 | Digital thread | "Deterministic trace: PR-1042 and PR-1043 lead to four batches. B-2205 has no order link, so it's UNKNOWN, not safe. Out-of-window runs are excluded." |
| 0:55–1:30 | Ranked checks plus excluded list | "Four feasible checks, with the formula shown. The CT scan is excluded because the scanner is down (F03). A hold on shipped B-2202 is excluded (F01); use escalation instead." |
| 1:30–2:05 | Record C-02 PASS, reload, record C-01 FAIL | "The result is persisted. G-02 is resolved, C-01's coverage drops, and the order changes. The FAIL creates G-04 and an MRB restriction, and release is now blocked." |
| 2:05–2:35 | Gemini panel | "Gemini explains the plan with cited record IDs. A validator removes anything it can't ground." |
| 2:35–3:05 | Operator approve → 403; manager approve → work order; audit timeline | "Simulated approval: the operator is rejected and the quality manager approves. Every step is versioned in the audit log in Firestore." |
| 3:05–3:30 | Baseline table, footer showing Cloud Run / Firestore / Gemini | "Across six synthetic cases: zero policy violations and the least unresolved evidence. Ties are reported too. Running on Cloud Run, Firestore, Firebase Hosting and Gemini." |

## Deck outline (map these onto the template's slides)

1. Problem: a machine alarm causes downstream uncertainty, and teams over-inspect or act unsafely.
2. Users: shift operator, quality manager.
3. Solution and differentiator: trace → gaps → feasible-only ranking → evidence loop → audited decision.
4. Architecture diagram: React on Firebase Hosting → Cloud Run (FastAPI) → Firestore; Gemini as explainer only.
5. Google AI role: grounded explanation, validator, fallback. Use numbers from the eval report.
6. Live demo screenshots.
7. Evaluation: tests T01–T09 and the baseline table, including ties.
8. Limitations: synthetic data, heuristic scores (not probabilities), simulated approval.
9. Impact and scalability: more incident types, real MES/QMS connectors, Firebase Auth for real RBAC.
