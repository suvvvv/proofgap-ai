import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)
os.environ["STATIC_DIR"] = os.path.join(tempfile.gettempdir(), "proofgap-no-static")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import service  # noqa: E402
from app.auth import store_dep  # noqa: E402
from app.main import app, app_state  # noqa: E402
from app.stores.sql import SqlStore  # noqa: E402

INC = "INC-M04-001"
OP = {"X-Demo-User": "u-op-1"}
QM = {"X-Demo-User": "u-qm-1"}

STORES = ["sql"] + (["firestore"] if os.getenv("FIRESTORE_EMULATOR_HOST") else [])


def make_store(kind: str):
    if kind == "firestore":
        from app.stores.firestore import FirestoreStore
        return FirestoreStore(project="demo-proofgap")
    return SqlStore()


@pytest.fixture(params=STORES)
def client(request):
    store = make_store(request.param)
    app.dependency_overrides[store_dep] = lambda: store
    with TestClient(app) as c:
        store.seed(service.load_scenario(), reset=True)
        app_state["model_fn"] = None
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def scenario():
    return service.load_scenario()
