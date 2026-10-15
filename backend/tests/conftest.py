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
from app.db import SessionLocal  # noqa: E402
from app.main import app, app_state  # noqa: E402

INC = "INC-M04-001"
OP = {"X-Demo-User": "u-op-1"}
QM = {"X-Demo-User": "u-qm-1"}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        with SessionLocal() as s:
            service.seed(s, service.load_scenario(), reset=True)
        app_state["model_fn"] = None
        yield c


@pytest.fixture()
def scenario():
    return service.load_scenario()
