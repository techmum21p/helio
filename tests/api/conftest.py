import pytest
import api.db as db_module
from fastapi.testclient import TestClient


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and create tables fresh."""
    db_file = tmp_path / "test_helio.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    db_module.create_tables()
    yield db_file


@pytest.fixture
def app_client(tmp_db):
    """TestClient with fresh DB. Uses context manager so startup events (seed) run."""
    from api.main import create_app
    with TestClient(create_app()) as client:
        yield client
