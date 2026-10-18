# ProofGap AI: Loom video script (about 3:10)

**Do** the actions in *[brackets]* on screen. **Say** the quoted lines.

## Before you hit record

1. Open https://proofgap-ai.web.app
2. Make sure the demo is **reset**: identity **Demo Admin** → **Reset demo**.
3. Switch the identity to **Demo Operator**, reload the page, and scroll to the top.
4. Check the ranking shows **C-01, C-02, C-03, C-04**.

---

## 0:00–0:25 · Problem
*[Top of page: incident card]*

> "This is ProofGap AI. A vibration sensor on CNC lathe M-04 just read 9.8 millimetres per second, against a limit of 7.1. That machine made parts for three customer orders, and one batch has already shipped. The question every factory faces is: what's affected, what don't we know yet, and what should we check first?"

## 0:25–0:50 · Traceability
*[Click "1. Trace affected work", or scroll to Digital thread]*

> "ProofGap traces it deterministically. Two production runs fall inside the anomaly window and lead to four batches, their orders, and one shipment. Batch B-2205 has no order record, so it's shown as UNKNOWN. We never assume it's safe. Runs outside the window, or on other machines, are excluded."

## 0:50–1:25 · Gaps and ranking
*[Evidence gaps, then Ranked feasible checks. On #1 C-01, click "Show score breakdown"]*

> "Here are the open evidence gaps, weighted by how much they matter to the decision. Before ranking, hard safety rules remove anything infeasible. The CT scan is out because the scanner is down. A warehouse hold on the shipped batch is blocked, because it already left; that needs a customer escalation instead. The remaining checks are ranked by a transparent formula of impact, coverage, cost and time. Every number is shown, and it's a heuristic, not a fake probability."

## 1:25–2:00 · Evidence loop

*[On card **#2 C-02** (profilometer), click **Record result** → keep **PASS** → **Submit evidence**. Then **reload the page**]*

> "Let's record a real result. The surface check, C-02, passed. That's saved in Firestore, and when I reload, the plan is recomputed from saved state. Gap G-02 is resolved, C-01 now covers less, and the ranking changed."

*[On card **#3 C-01**, click **Record result** → **click FAIL** (make sure it's highlighted) → **Submit evidence**]*

> "Now the dimensional inspection fails. That creates a new mandatory quality-review gap, G-04, adds a review restriction, enables a new check, and blocks releasing that batch until review is done."

## 2:00–2:25 · Gemini
*[Click "4. Explain and review" → **Generate grounded explanation**, and wait for it (5–15 s)]*

> "Gemini explains the plan in plain language. It sees only curated facts, and must cite real record IDs. Verified facts and hypotheses are kept separate. A validator removes any made-up ID, probability, or unsafe advice. Gemini explains; it never decides."

## 2:25–2:50 · Governance
*[Decisions: on **A-01**, type a justification (e.g. "Contain warehouse stock") → **Approve as Demo Operator**. A red error appears]*

> "Approvals are controlled. The operator tries to place the quality hold and is refused."

*[Switch the identity at the top to **Demo Quality Manager** → on A-01, type a justification → **Approve**. Scroll to the Audit timeline]*

> "The quality manager approves it and a work order is created. Every step is in an append-only audit log, with who did it, their role, and the before-and-after state. Roles here are clearly marked as a simulated demo."

## 2:50–3:10 · Results and stack
*[Baseline comparison summary, then scroll to the footer: "Running on: Cloud Run · Cloud Firestore · Gemini"]*

> "On six synthetic test cases, ProofGap had zero policy violations and left less evidence unresolved than naive approaches, and we report the ties too. It runs on Cloud Run, stores data in Firestore, is served through Firebase Hosting, and uses Gemini for grounded explanations. ProofGap: evidence connects operations."

---

## After recording

1. **Reset for the judges:** **Demo Admin** → **Reset demo** → switch back to **Demo Operator**.
2. Share the Loom link as **anyone with the link can view**, and test it in an incognito window.
3. Keep the video between **3:00 and 4:00**; the portal asks for 3–4 minutes.

## If something goes wrong mid-take

- **Wrong check recorded:** Demo Admin → Reset demo → Demo Operator, and start again.
- **Gemini says "AI explanation unavailable":** click **Regenerate** once. If it's still unavailable, say: *"If Gemini is unavailable, the deterministic plan keeps working. That's by design."*
- **"409 STALE_VERSION" message:** reload the page and repeat the click.
