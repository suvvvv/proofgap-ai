"""Demo identity.

This prototype uses SIMULATED APPROVAL (blueprint §7 time-box fallback): the
browser names a seeded demo user via the X-Demo-User header, and the backend
looks that user's role up in its own users store. Role or approver fields in
request bodies are never read. This is not a security control and must not be
described as server-enforced RBAC; every record it produces is marked
simulation=true.
"""

from fastapi import Depends, Header

from .service import Actor, ApiError
from .stores import Store, get_store


def store_dep() -> Store:
    return get_store()


def current_actor(x_demo_user: str | None = Header(default=None), store: Store = Depends(store_dep)) -> Actor:
    if not x_demo_user:
        raise ApiError(401, "IDENTITY_REQUIRED", "Select a demo user (X-Demo-User header).")
    user = store.get_user(x_demo_user)
    if user is None:
        raise ApiError(401, "UNKNOWN_DEMO_USER", f"Unknown demo user {x_demo_user}")
    return Actor(id=user["id"], name=user["name"], role=user["role"], simulation=True)
