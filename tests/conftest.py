from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from gapfinder.config import Settings
from gapfinder.main import create_app


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), mode="demo", data_dir=tmp_path,
                   database_url=f"sqlite:///{tmp_path}/test.db", embedding_backend="hash",
                   qdrant_url="", qdrant_key="", groq_key="", cookie_secure=False)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def logged_in(client, settings):
    response = client.post("/api/login", json={"email": settings.demo_email, "password": settings.demo_password})
    assert response.status_code == 200
    return client
