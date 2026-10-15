"""Firestore store (deployed mode).

Layout:
  users/{user_id}                       {name, role}
  incidents/{incident_id}               {scenario_id, version, updated_at, audit_seq}
  incidents/{id}/evidence/{EV-0001}     evidence record
  incidents/{id}/approvals/{AP-0001}    approval record
  incidents/{id}/audit/{000001}         append-only audit event (zero-padded seq)

Every write runs in a Firestore transaction that reads the incident document,
so concurrent writers serialize on it and the version check is atomic.
"""

from __future__ import annotations

from .base import Commit, DecideFn, IncidentData, not_found, seed_audit, stale, utcnow_iso


class FirestoreStore:
    def __init__(self, project: str | None = None, database: str | None = None, client=None):
        from google.cloud import firestore

        self._fs = firestore
        self.db = client or firestore.Client(project=project, database=database or "(default)")

    def _inc(self, incident_id: str):
        return self.db.collection("incidents").document(incident_id)

    def seed(self, scenario: dict, reset: bool = False) -> None:
        inc_id = scenario["incident"]["id"]
        ref = self._inc(inc_id)
        if reset:
            for sub in ("evidence", "approvals", "audit"):
                for doc in ref.collection(sub).stream():
                    doc.reference.delete()
            ref.delete()
        for u in scenario["users"]:
            self.db.collection("users").document(u["id"]).set({"name": u["name"], "role": u["role"]})

        @self._fs.transactional
        def create(tx):
            if ref.get(transaction=tx).exists:
                return
            tx.set(ref, {"scenario_id": scenario["scenario_id"], "version": 1, "updated_at": utcnow_iso(), "audit_seq": 1})
            tx.set(ref.collection("audit").document(f"{1:06d}"), {"seq": 1, **seed_audit(scenario)})

        create(self.db.transaction())

    def get_user(self, user_id: str) -> dict | None:
        snap = self.db.collection("users").document(user_id).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def _read(self, incident_id: str, tx=None) -> tuple[IncidentData, dict]:
        ref = self._inc(incident_id)
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise not_found(incident_id)
        doc = snap.to_dict()
        ev = sorted((d.to_dict() for d in ref.collection("evidence").stream(transaction=tx)), key=lambda e: e["version"])
        ap = sorted((d.to_dict() for d in ref.collection("approvals").stream(transaction=tx)), key=lambda a: a["version"])
        return IncidentData(id=incident_id, version=doc["version"], updated_at=doc["updated_at"], evidence=ev, approvals=ap), doc

    def load(self, incident_id: str) -> IncidentData:
        return self._read(incident_id)[0]

    def audit(self, incident_id: str) -> list[dict]:
        ref = self._inc(incident_id)
        if not ref.get().exists:
            raise not_found(incident_id)
        return [d.to_dict() for d in ref.collection("audit").order_by("seq").stream()]

    def commit(self, incident_id: str, decide: DecideFn):
        ref = self._inc(incident_id)

        @self._fs.transactional
        def run(tx):
            data, doc = self._read(incident_id, tx)
            c: Commit = decide(data)
            if c.new_version != data.version + 1:
                raise stale(data.version, doc["version"])
            seq = doc.get("audit_seq", 0) + 1
            tx.update(ref, {"version": c.new_version, "updated_at": utcnow_iso(), "audit_seq": seq})
            if c.evidence:
                tx.set(ref.collection("evidence").document(c.evidence["id"]), c.evidence)
            if c.approval:
                tx.set(ref.collection("approvals").document(c.approval["id"]), c.approval)
            tx.set(ref.collection("audit").document(f"{seq:06d}"), {"seq": seq, **c.audit})
            return c.result

        return run(self.db.transaction())
