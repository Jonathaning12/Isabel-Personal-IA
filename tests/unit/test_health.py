"""Unit tests for GET /health, with Nebius and Qdrant mocked."""

import httpx
import respx
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from assistant import config
from assistant.api.main import app
from tests.conftest import FAKE_BASE_URL, build_test_client

MODELS_URL = f"{FAKE_BASE_URL}models"
QDRANT_READY_URL = "http://qdrant.test:6333/readyz"


def make_client(monkeypatch, settings) -> TestClient:
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr("assistant.api.main.get_settings", lambda: settings)
    monkeypatch.setattr("assistant.api.main.build_client", build_test_client)
    monkeypatch.setattr(
        "assistant.api.main.build_qdrant", lambda _s: AsyncQdrantClient(location=":memory:")
    )
    return TestClient(app)


@respx.mock
def test_health_ok(monkeypatch, settings):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(QDRANT_READY_URL).mock(return_value=httpx.Response(200))

    with make_client(monkeypatch, settings) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["nebius"] == "ok"
    assert body["models"]["llm"] == "nvidia/test-llm"
    assert "test-key" not in response.text


@respx.mock
def test_health_reports_nebius_failure(monkeypatch, settings):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    respx.get(QDRANT_READY_URL).mock(return_value=httpx.Response(200))

    with make_client(monkeypatch, settings) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["nebius"].startswith("error")
