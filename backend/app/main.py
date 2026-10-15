from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import baseline as baseline_mod
from . import service
from .ai import gemini, grounding
from .auth import current_actor, store_dep
from .config import settings
from .service import Actor, ApiError
from .stores import Store, get_store

logging.basicConfig(level=logging.INFO)


class EvidenceIn(BaseModel):
    check_id: str
    result: Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT_PERFORMED"]
    batch_id: str | None = None
    expected_version: int
    supersedes_id: str | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ExplainIn(BaseModel):
    expected_version: int


class ApproveIn(BaseModel):
    action_id: str
    expected_version: int
    justification: str = Field(min_length=3, max_length=1000)


# Swappable for tests (T06/T07): a callable payload -> raw JSON text, or None.
app_state: dict = {"model_fn": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_store().seed(service.load_scenario())
    app_state["model_fn"] = gemini.gemini_model_fn()
    yield


app = FastAPI(title="ProofGap AI", version="1.0.0", lifespan=lifespan,
              description="Incident evidence planner (prototype decision support; synthetic data).")


@app.exception_handler(ApiError)
async def api_error(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, "details": exc.details})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"code": "VALIDATION_FAILED", "message": "Request validation failed",
                                                  "details": {"errors": jsonable_errors(exc)}})


def jsonable_errors(exc: RequestValidationError) -> list[dict]:
    return [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]


def scenario() -> dict:
    return service.load_scenario()


@app.get("/healthz")
@app.get("/api/health")  # run.app reserves paths ending in "z", so Cloud Run needs this alias
def healthz():
    return {"status": "ok", "runtime": "cloud_run" if os.getenv("K_SERVICE") else "local", "store": settings.store, "gemini_configured": app_state["model_fn"] is not None}


@app.get("/api/users")
def users():
    """Seeded demo identities for the SIMULATED approval flow."""
    return {"simulated": True, "users": scenario()["users"]}


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str, store: Store = Depends(store_dep)):
    return service.incident_summary(store, incident_id, scenario())


@app.get("/api/incidents/{incident_id}/thread")
def get_thread(incident_id: str, store: Store = Depends(store_dep)):
    return service.thread(store, incident_id, scenario())


@app.get("/api/incidents/{incident_id}/plan")
def get_plan(incident_id: str, store: Store = Depends(store_dep)):
    return service.plan(store, incident_id, scenario())


@app.post("/api/incidents/{incident_id}/evidence")
def post_evidence(incident_id: str, body: EvidenceIn, actor: Actor = Depends(current_actor),
                  store: Store = Depends(store_dep)):
    return service.record_evidence(store, incident_id, scenario(), actor, **body.model_dump())


@app.post("/api/incidents/{incident_id}/explain")
def post_explain(incident_id: str, body: ExplainIn, store: Store = Depends(store_dep)):
    sc = scenario()
    data = store.load(incident_id)
    if data.version != body.expected_version:
        raise ApiError(409, "STALE_VERSION", "Incident changed since you loaded it; reload and retry.",
                       {"expected_version": body.expected_version, "current_version": data.version})
    payload = grounding.build_payload(sc, service.derive(sc, data), service.plan(store, incident_id, sc, data),
                                      service.thread(store, incident_id, sc, data), data.evidence)
    return gemini.explain(payload, app_state["model_fn"])


@app.post("/api/incidents/{incident_id}/approve")
def post_approve(incident_id: str, body: ApproveIn, actor: Actor = Depends(current_actor),
                 store: Store = Depends(store_dep)):
    return service.approve(store, incident_id, scenario(), actor, **body.model_dump())


@app.get("/api/incidents/{incident_id}/audit")
def get_audit(incident_id: str, store: Store = Depends(store_dep)):
    return {"incident_id": incident_id, "events": store.audit(incident_id)}


@app.get("/api/baseline")
def get_baseline():
    return baseline_mod.run()


@app.post("/api/admin/reset")
def reset(actor: Actor = Depends(current_actor), store: Store = Depends(store_dep)):
    """Demo-only: wipe and re-seed the synthetic incident."""
    if not settings.allow_demo_reset:
        raise ApiError(403, "RESET_DISABLED", "Demo reset is disabled.")
    if actor.role != "ADMIN":
        raise ApiError(403, "FORBIDDEN_ROLE", "Only the demo admin can reset.")
    store.seed(scenario(), reset=True)
    return {"status": "reset"}


# Serve the built React app (single container for Cloud Run).
if (settings.static_dir / "index.html").exists():
    if (settings.static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", "Unknown API route")
        root = settings.static_dir.resolve()
        target = (root / path).resolve()
        if path and target.is_relative_to(root) and target.is_file():
            return FileResponse(target)
        return FileResponse(settings.static_dir / "index.html")
