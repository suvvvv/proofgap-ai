"""Gemini call with strict schema, timeout, grounding validation and fallback."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from typing import Callable

from ..config import settings
from .grounding import SYSTEM_INSTRUCTION, Explanation, GroundingError, deterministic_summary, validate_explanation

log = logging.getLogger(__name__)

# A model function takes the curated payload and returns raw JSON text, or (text, model_name).
ModelFn = Callable[[dict], "str | tuple[str, str]"]

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def gemini_model_fn() -> ModelFn | None:
    if not (settings.gemini_api_key or settings.use_vertex):
        return None
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=settings.gemini_api_key) if not settings.use_vertex else genai.Client(vertexai=True)
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=Explanation,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        # Explaining a precomputed plan needs little reasoning; low thinking keeps latency demo-friendly.
        thinking_config=types.ThinkingConfig(thinking_level=settings.gemini_thinking_level),
        http_options=types.HttpOptions(timeout=int(settings.gemini_timeout_s * 1000)),
    )

    def call(payload: dict) -> tuple[str, str]:
        contents = "Explain this incident using only this payload:\n" + json.dumps(payload)
        last: Exception | None = None
        # Busy (429/503) or retired (404) models fall through to the next one in the chain.
        for model in models:
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(model=model, contents=contents, config=config)
                    return resp.text or "", model
                except errors.APIError as exc:
                    last = exc
                    if exc.code in (429, 500, 503) and attempt == 0:
                        time.sleep(1.5)
                        continue
                    if exc.code in (404, 429, 500, 503):
                        break
                    raise
        raise last or RuntimeError("no Gemini model configured")

    return call


def explain(payload: dict, model_fn: ModelFn | None, timeout_s: float | None = None) -> dict:
    base = {"evidence_version": payload["evidence_version"], "model": settings.gemini_model}
    if model_fn is None:
        return _unavailable(base, payload, "Gemini is not configured (no GEMINI_API_KEY / Vertex AI).")
    try:
        raw = _executor.submit(model_fn, payload).result(timeout=timeout_s or settings.gemini_total_timeout_s)
        if isinstance(raw, tuple):  # (text, model that answered)
            raw, base["model"] = raw
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
