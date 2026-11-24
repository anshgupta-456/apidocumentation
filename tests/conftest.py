import os
import sys
import tempfile
from pathlib import Path

import pytest

# Isolated SQLite database + deterministic (rule-based) explanations for every test run.
_tmp = tempfile.mkdtemp(prefix="acv-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["GROQ_API_KEY"] = ""
os.environ["AI_ENABLED"] = "false"
os.environ["GENERATED_SPEC_PATH"] = str(Path(_tmp) / "openapi.generated.json")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.routes import demo_routes  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    demo_routes.users_db.clear()
    demo_routes._next_id["value"] = 1
    with TestClient(app) as c:
        yield c
