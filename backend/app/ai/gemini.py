"""Gemini call with strict schema, timeout, grounding validation and fallback."""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Callable

from ..config import settings
from .grounding import SYSTEM_INSTRUCTION, Explanation, GroundingError, deterministic_summary, validate_explanation

log = logging.getLogger(__name__)

# A model function takes the curated payload and returns raw JSON text.
ModelFn = Callable[[dict], str]

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def gemini_model_fn() -> ModelFn | None:
    if not (settings.gemini_api_key or settings.use_vertex):
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key) if not settings.use_vertex else genai.Client(vertexai=True)

    def call(payload: dict) -> str:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents="Explain this incident using only this payload:\n" + json.dumps(payload),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=Explanation,
                temperature=0.2,
                http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
            ),
        )
        return resp.text or ""

    return call


def explain(payload: dict, model_fn: ModelFn | None, timeout_s: float | None = None) -> dict:
    base = {"evidence_version": payload["evidence_version"], "model": settings.gemini_model}
    if model_fn is None:
        return _unavailable(base, payload, "Gemini is not configured (no GEMINI_API_KEY / Vertex AI).")
    try:
        raw = _executor.submit(model_fn, payload).result(timeout=timeout_s or settings.gemini_timeout_s)
    except concurrent.futures.TimeoutError:
        return _unavailable(base, payload, "Gemini timed out.")
    except Exception as exc:  # network/auth/quota errors must never break the plan
        log.warning("Gemini call failed: %s", exc)
        return _unavailable(base, payload, f"Gemini call failed ({type(exc).__name__}).")
    try:
        clean, stripped = validate_explanation(raw, payload)
    except GroundingError as exc:
        return _unavailable(base, payload, f"Gemini response rejected by grounding validator: {exc}")
    return {**base, "status": "ok", "source": "gemini", "explanation": clean, "stripped": stripped,
            "allowed_record_ids": payload["allowed_record_ids"]}


def _unavailable(base: dict, payload: dict, reason: str) -> dict:
    return {**base, "status": "unavailable", "source": "deterministic_fallback",
            "message": "AI explanation unavailable. The deterministic plan below remains authoritative.",
            "reason": reason, "fallback": deterministic_summary(payload), "stripped": [],
            "allowed_record_ids": payload["allowed_record_ids"]}
