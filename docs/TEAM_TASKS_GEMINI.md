# Gemini tasks: friend / AI owner

**Repo:** https://github.com/suvvvv/proofgap-ai
**Deadline:** results committed by **17 Oct, end of day**. 18 Oct is for bug fixes and submission only.

Per the blueprint, you own the AI module code and its evaluation. Gemini **explains** the plan; it never decides. The backend's deterministic ranking is authoritative.

## What already exists

| File | What it does |
|---|---|
| `backend/app/ai/grounding.py` | Builds the curated payload sent to Gemini (`build_payload`), the system prompt (`SYSTEM_INSTRUCTION`), the response schema (`Explanation`), and the validator (`validate_explanation`). The validator strips or rejects unknown record IDs, probabilities, causal claims stated as facts, and "ship/release without review" advice. |
| `backend/app/ai/gemini.py` | Calls Gemini through the `google-genai` SDK with JSON structured output and a timeout. Falls back to a non-AI summary if anything fails. |
| `backend/app/ai/live_eval.py` | **New, for you.** Runs the real model over 4 incident states plus 5 prompt-injection probes and writes a markdown report. |
| `backend/tests/test_grounding.py` | Offline adversarial tests (T06) using stubbed model outputs. |

## Setup (about 10 minutes)

```bash
git clone https://github.com/suvvvv/proofgap-ai && cd proofgap-ai/backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                       # should be all green
export GEMINI_API_KEY=<your key from https://aistudio.google.com/apikey>
```

## Tasks

1. **Pick the model.** Run `.venv/bin/python -m app.ai.live_eval --list-models`. Choose the current Flash model that supports structured JSON output; the default is `gemini-2.5-flash`. If it's retired, tell the owner the new name so it goes into `GEMINI_MODEL` at deploy time.
2. **Run the live evaluation**, then commit the report:
   ```bash
   .venv/bin/python -m app.ai.live_eval --model <model> --repeats 3 --out ../docs/gemini_eval_results.md
   ```
3. **Read the report and fix what fails.**
   - Normal states should be `ok` with several verified facts kept. If many facts are being stripped, tighten `SYSTEM_INSTRUCTION`; don't loosen the validator.
   - Every probe should be `rejected_by_validator`, `stripped`, or `model_ignored_injection`. Open the raw JSON for any `model_ignored_injection` row and confirm nothing unsafe got through.
   - If an unsafe phrase slips past the regexes, add it to `PROBABILITY_PATTERN`, `CAUSAL_PATTERN` or `UNSAFE_PATTERN` in `grounding.py`, **and add a matching stub test in `tests/test_grounding.py`**.
4. **Optional quality pass:** improve the wording of `summary` and `recommendation_rationale` so a plant manager understands it in 20 seconds. Keep the rules.
5. **Run the demo with your key locally** (`uvicorn app.main:app --port 8000`, then `npm run dev` in `frontend/`). Click "Generate grounded explanation" in four states: initial, after C-02 PASS, after C-01 FAIL, after approving A-01. Take screenshots for the deck.
6. **Write 3–4 bullets for the deck** on how Gemini is used. Use only numbers from your eval report: success rate, latency, probes blocked.
7. **API key for the deployed app:** the owner deploys. Either share a key over a private channel (never in git or chat logs) so it can go into Secret Manager as `gemini-api-key`, or create the key inside the deployment GCP project yourself.

## Rules (from the blueprint)

- Never send secrets or personal data in the payload. Never invent measurements.
- Every `record_id` and `gap_id` in the output must exist in the payload.
- Gemini can't suggest actions outside `eligible_actions`, and can't override the backend ranking.
- If Gemini fails, the panel says "AI explanation unavailable" and everything else keeps working. Test T07 checks this.

## Done when

- `docs/gemini_eval_results.md` is committed, from a real run with `--repeats 3`.
- All tests pass: `pytest -q`.
- The deck bullets are sent to the owner.
