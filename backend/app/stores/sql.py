"""SQLAlchemy store: SQLite locally, Postgres/Cloud SQL via DATABASE_URL."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db import Approval, AuditEvent, Evidence, Incident, SessionLocal, User, init_db
from .base import Commit, DecideFn, IncidentData, not_found, seed_audit, stale, utcnow_iso


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; values are always stored as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


AUDIT_FIELDS = ("event_type", "actor_id", "actor_role", "simulation", "action_id", "check_id", "previous_version",
                "new_version", "previous_state", "new_state", "evidence_ids", "justification", "work_order_id")


class SqlStore:
    def __init__(self, session_factory=SessionLocal):
        self.Session = session_factory
        init_db(session_factory.kw["bind"])

    def seed(self, scenario: dict, reset: bool = False) -> None:
        inc_id = scenario["incident"]["id"]
        with self.Session.begin() as s:
            if reset:
                for model in (AuditEvent, Approval, Evidence):
                    s.query(model).filter_by(incident_id=inc_id).delete()
                s.query(Incident).filter_by(id=inc_id).delete()
            for u in scenario["users"]:
                s.merge(User(id=u["id"], name=u["name"], role=u["role"]))
            if s.get(Incident, inc_id) is None:
                s.add(Incident(id=inc_id, scenario_id=scenario["scenario_id"], version=1, updated_at=_dt(utcnow_iso())))
                a = seed_audit(scenario)
                s.add(AuditEvent(incident_id=inc_id, created_at=_dt(a["created_at"]), **{k: a[k] for k in AUDIT_FIELDS}))

    def get_user(self, user_id: str) -> dict | None:
        with self.Session() as s:
            u = s.get(User, user_id)
            return {"id": u.id, "name": u.name, "role": u.role} if u else None

    def _load(self, s, incident_id: str) -> IncidentData:
        inc = s.get(Incident, incident_id)
        if inc is None:
            raise not_found(incident_id)
        ev = s.scalars(select(Evidence).where(Evidence.incident_id == incident_id).order_by(Evidence.version))
        ap = s.scalars(select(Approval).where(Approval.incident_id == incident_id).order_by(Approval.version))
        return IncidentData(
            id=inc.id, version=inc.version, updated_at=_iso(inc.updated_at),
            evidence=[{"id": e.id, "check_id": e.check_id, "batch_id": e.batch_id, "result": e.result, "notes": e.notes,
                       "captured_at": _iso(e.captured_at), "actor_id": e.actor_id, "actor_role": e.actor_role,
                       "version": e.version, "supersedes_id": e.supersedes_id} for e in ev],
            approvals=[{"id": a.id, "action_id": a.action_id, "actor_id": a.actor_id, "actor_role": a.actor_role,
                        "simulation": a.simulation, "justification": a.justification, "work_order_id": a.work_order_id,
                        "version": a.version, "created_at": _iso(a.created_at)} for a in ap])

    def load(self, incident_id: str) -> IncidentData:
        with self.Session() as s:
            return self._load(s, incident_id)

    def audit(self, incident_id: str) -> list[dict]:
        with self.Session() as s:
            if s.get(Incident, incident_id) is None:
                raise not_found(incident_id)
            rows = s.scalars(select(AuditEvent).where(AuditEvent.incident_id == incident_id).order_by(AuditEvent.seq))
            return [{"seq": r.seq, **{k: getattr(r, k) for k in AUDIT_FIELDS}, "evidence_ids": r.evidence_ids or [],
                     "created_at": _iso(r.created_at)} for r in rows]

    def commit(self, incident_id: str, decide: DecideFn):
        with self.Session.begin() as s:
            data = self._load(s, incident_id)
            c: Commit = decide(data)
            # Optimistic lock: only one writer can move version N -> N+1.
            res = s.execute(update(Incident).where(Incident.id == incident_id, Incident.version == data.version)
                            .values(version=c.new_version, updated_at=_dt(utcnow_iso())))
            if res.rowcount != 1:
                raise stale(data.version, s.get(Incident, incident_id).version)
            if c.evidence:
                e = c.evidence
                s.add(Evidence(incident_id=incident_id, **{**e, "captured_at": _dt(e["captured_at"])}))
            if c.approval:
                a = c.approval
                s.add(Approval(incident_id=incident_id, **{**a, "created_at": _dt(a["created_at"])}))
            s.add(AuditEvent(incident_id=incident_id, created_at=_dt(c.audit["created_at"]),
                             **{k: c.audit.get(k) for k in AUDIT_FIELDS}))
        return c.result
