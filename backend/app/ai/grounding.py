"""Curated Gemini payload + strict validation of the model's response.

Gemini only explains. It receives verified facts that the deterministic engine
already computed and must cite record IDs from that payload. Anything it
returns that cannot be traced back to the payload is stripped or rejected.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .. import engine as eng


class VerifiedFact(BaseModel):
    claim: str
    record_ids: list[str] = Field(min_length=1)


class Hypothesis(BaseModel):
    claim: str
    uncertainty: str


class MissingEvidence(BaseModel):
    gap_id: str
    why_it_matters: str


class Explanation(BaseModel):
    summary: str
    verified_facts: list[VerifiedFact]
    hypotheses: list[Hypothesis]
    missing_evidence: list[MissingEvidence]
    recommendation_rationale: str
    limitations: str


ID_PATTERN = re.compile(r"\b(?:[A-Z]{1,8}(?:-[A-Z0-9]+)+|F0\d)\b")
PROBABILITY_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent)|\bprobabilit|\bchance of\b|\blikelihood of \d", re.I)
CAUSAL_PATTERN = re.compile(r"\b(caused|causes|root cause|due to|because of|resulted from|led to)\b", re.I)
UNSAFE_PATTERN = re.compile(
    r"\b(ship|release|dispatch|deliver)\w*\b[^.]{0,80}\b(without|before|skip\w*|bypass\w*)\b[^.]{0,40}\b(review|inspection|approval|disposition|MRB)\b"
    r"|\b(skip|bypass)\w*\b[^.]{0,40}\b(review|inspection|approval|hold)\b",
    re.I,
)

SYSTEM_INSTRUCTION = """You explain a manufacturing incident for a factory quality team.
Rules you must follow:
- Use ONLY facts in the provided JSON payload. Never invent record IDs, measurements, batches or orders.
- Every verified fact must cite one or more record_ids that appear in the payload's allowed_record_ids.
- Do not state causes as facts; put causal ideas under hypotheses with their uncertainty.
- Never give probabilities, percentages or risk numbers that are not in the payload.
- The backend ranking is authoritative. Explain it; do not re-rank and do not propose actions outside eligible_actions.
- Never suggest shipping, releasing, or skipping review/inspection while gaps or restrictions remain.
- missing_evidence gap_id values must come from unresolved_gaps.
Return JSON matching the response schema."""


def build_payload(scenario: dict, state: eng.DerivedState, plan: dict, thread: dict, evidence: list[dict]) -> dict:
    inc = scenario["incident"]
    eligible_actions = [a for a in plan["actions"] if a["status"] == "ELIGIBLE"]
    blocked = [a for a in plan["actions"] if a["status"] == "BLOCKED"]
    payload = {
        "evidence_version": plan["version"],
        "incident": {k: inc[k] for k in ("id", "title", "machine_id", "severity", "opened_at", "why_it_matters")},
        "sensor": inc["sensor"],
        "window": inc["window"],
        "graph_facts": [
            f"{e['source']} -{e['relation']}-> {e['target']} ({e['status']})" for e in thread["edges"]
        ],
        "batch_status": {n["id"]: n["status"] for n in thread["nodes"] if n["type"] == "BATCH"},
        "unknown_relationships": thread["unknown_relationships"],
        "excluded_runs": thread["excluded_runs"],
        "unresolved_gaps": [{k: g[k] for k in ("id", "title", "weight", "why", "batch_ids")} for g in plan["unresolved_gaps"]],
        "resolved_gaps": [{"id": g["id"], "title": g["title"], "resolved_by": g.get("resolved_by")} for g in plan["resolved_gaps"]],
        "restrictions": plan["restrictions"],
        "ranked_checks": [
            {"rank": r["rank"], "check_id": r["check_id"], "title": r["title"], "score": r["score_display"],
             "factors": {k: round(v, 3) for k, v in r["factors"].items()}, "gap_ids_addressed": r["gap_ids_addressed"],
             "limitations": r["limitations"]}
            for r in plan["ranked_candidates"]
        ],
        "excluded_checks": plan["excluded_candidates"],
        "eligible_actions": [{"action_id": a["action_id"], "title": a["title"]} for a in eligible_actions],
        "blocked_actions": [{"action_id": a["action_id"], "title": a["title"], "rule_ids": a["rule_ids"], "reason": a["human_reason"]} for a in blocked],
        "evidence_records": [{k: e[k] for k in ("id", "check_id", "batch_id", "result")} for e in evidence],
        "data_limitations": [
            "All data is synthetic demo data.",
            "Scores are a deterministic heuristic, not defect probabilities.",
            "Sample-based inspections do not prove every part conforms.",
        ],
    }
    payload["allowed_record_ids"] = sorted(allowed_ids(scenario, payload))
    return payload


def allowed_ids(scenario: dict, payload: dict) -> set[str]:
    ids = set(ID_PATTERN.findall(json.dumps({k: v for k, v in payload.items() if k != "allowed_record_ids"})))
    ids |= {payload["incident"]["id"]}
    return ids


def _ids_in(text: str) -> set[str]:
    return set(ID_PATTERN.findall(text))


class GroundingError(Exception):
    pass


def validate_explanation(raw: str | dict, payload: dict) -> tuple[dict, list[dict]]:
    """Return (clean_explanation, stripped_items) or raise GroundingError."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        exp = Explanation.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise GroundingError(f"Malformed model output: {type(exc).__name__}") from exc

    allowed = set(payload["allowed_record_ids"])
    unresolved = {g["id"] for g in payload["unresolved_gaps"]}
    stripped: list[dict] = []

    for field_name in ("summary", "recommendation_rationale", "limitations"):
        text = getattr(exp, field_name)
        unknown = _ids_in(text) - allowed
        if unknown:
            raise GroundingError(f"{field_name} cites unknown record IDs: {sorted(unknown)}")
        if PROBABILITY_PATTERN.search(text):
            raise GroundingError(f"{field_name} contains an unsupported probability")
    every_text = json.dumps(exp.model_dump())
    if UNSAFE_PATTERN.search(every_text):
        raise GroundingError("Response suggests bypassing a mandatory review, inspection or hold")

    facts = []
    for f in exp.verified_facts:
        unknown = (set(f.record_ids) | _ids_in(f.claim)) - allowed
        if unknown:
            stripped.append({"section": "verified_facts", "claim": f.claim, "reason": f"unknown record IDs {sorted(unknown)}"})
        elif PROBABILITY_PATTERN.search(f.claim):
            stripped.append({"section": "verified_facts", "claim": f.claim, "reason": "unsupported probability"})
        elif CAUSAL_PATTERN.search(f.claim):
            stripped.append({"section": "verified_facts", "claim": f.claim, "reason": "causal assertion presented as fact"})
        else:
            facts.append(f.model_dump())

    hypotheses = []
    for h in exp.hypotheses:
        unknown = _ids_in(h.claim) - allowed
        if unknown:
            stripped.append({"section": "hypotheses", "claim": h.claim, "reason": f"unknown record IDs {sorted(unknown)}"})
        elif PROBABILITY_PATTERN.search(h.claim + " " + h.uncertainty):
            stripped.append({"section": "hypotheses", "claim": h.claim, "reason": "unsupported probability"})
        else:
            hypotheses.append(h.model_dump())

    missing = []
    for m in exp.missing_evidence:
        if m.gap_id not in unresolved or _ids_in(m.why_it_matters) - allowed:
            stripped.append({"section": "missing_evidence", "claim": f"{m.gap_id}: {m.why_it_matters}", "reason": "not an unresolved gap in payload"})
        else:
            missing.append(m.model_dump())

    clean = {**exp.model_dump(), "verified_facts": facts, "hypotheses": hypotheses, "missing_evidence": missing}
    return clean, stripped


def deterministic_summary(payload: dict) -> dict[str, Any]:
    """Non-AI fallback built only from payload fields."""
    s = payload["sensor"]
    top = payload["ranked_checks"][0] if payload["ranked_checks"] else None
    return {
        "summary": (f"{payload['incident']['id']}: {s['metric']} {s['reading']} {s['unit']} exceeded "
                    f"threshold {s['threshold']} at {s['reading_at']} ({s['record_id']}). "
                    f"{len(payload['unresolved_gaps'])} unresolved evidence gap(s)."),
        "verified_facts": [{"claim": fact, "record_ids": sorted(_ids_in(fact))} for fact in payload["graph_facts"]],
        "missing_evidence": [{"gap_id": g["id"], "why_it_matters": g["why"]} for g in payload["unresolved_gaps"]],
        "recommendation_rationale": (f"Top-ranked feasible check: {top['check_id']} ({top['title']}), score {top['score']}."
                                     if top else "No feasible check currently adds decision value."),
    }
