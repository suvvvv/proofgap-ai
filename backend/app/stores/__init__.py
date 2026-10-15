from functools import lru_cache

from ..config import settings
from .base import Store


@lru_cache(maxsize=1)
def get_store() -> Store:
    """STORE=firestore in deployed mode; SQL (SQLite/Postgres) otherwise."""
    if settings.store == "firestore":
        from .firestore import FirestoreStore

        return FirestoreStore(project=settings.gcp_project, database=settings.firestore_database)
    from .sql import SqlStore

    return SqlStore()
