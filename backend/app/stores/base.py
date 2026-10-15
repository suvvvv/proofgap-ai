"""Storage contract shared by the SQL and Firestore backends.

The service layer reads an incident's event log, decides (pure Python) what to
write, and hands a ``Commit`` back to the store. The store applies it
atomically: bump the incident version, write the evidence/approval record,
append an audit event with the next sequence number. Firestore may re-run the
decision function on contention, so it must not have side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class IncidentData:
    id: str
    version: int
    updated_at: str
    evidence: list[dict] = field(default_factory=list)   # ordered by version
    approvals: list[dict] = field(default_factory=list)  # ordered by version


@dataclass
class Commit:
    new_version: int
    audit: dict                      # audit fields except seq (assigned by the store)
    evidence: dict | None = None
    approval: dict | None = None
    result: Any = None


DecideFn = Callable[[IncidentData], Commit]


class Store(Protocol):
    def seed(self, scenario: dict, reset: bool = False) -> None: ...
    def get_user(self, user_id: str) -> dict | None: ...
    def load(self, incident_id: str) -> IncidentData: ...
    def audit(self, incident_id: str) -> list[dict]: ...
    def commit(self, incident_id: str, decide: DecideFn) -> Any: ...


def not_found(incident_id: str) -> ApiError:
    return ApiError(404, "INCIDENT_NOT_FOUND", f"Incident {incident_id} not found")


def stale(expected: int, current: int) -> ApiError:
    return ApiError(409, "STALE_VERSION", "Incident changed since you loaded it; reload and retry.",
                    {"expected_version": expected, "current_version": current})


def seed_audit(scenario: dict) -> dict:
    return {"event_type": "INCIDENT_SEEDED", "actor_id": "system", "actor_role": "SYSTEM", "simulation": False,
            "action_id": None, "check_id": None, "previous_version": None, "new_version": 1,
            "previous_state": None, "new_state": None, "evidence_ids": [], "work_order_id": None,
            "justification": f"Seeded synthetic scenario {scenario['scenario_id']}", "created_at": utcnow_iso()}
