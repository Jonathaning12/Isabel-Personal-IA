"""Unit tests for the local API token."""

import httpx
import respx
from pydantic import SecretStr

from assistant.api.auth import TOKEN_FILE, client_token, load_or_create_token
from tests.unit.test_health import MODELS_URL, QDRANT_READY_URL, make_client


def with_token(settings, tmp_path, token=""):
    return settings.model_copy(
        update={"require_token": True, "api_token": SecretStr(token), "data_dir": tmp_path}
    )


def test_a_token_is_generated_once_and_reused(settings, tmp_path):
    configured = with_token(settings, tmp_path)

    first = load_or_create_token(configured)

    assert len(first) >= 32
    assert (tmp_path / TOKEN_FILE).read_text(encoding="utf-8") == first
    assert load_or_create_token(configured) == first
    assert client_token(configured) == first


def test_the_env_token_wins(settings, tmp_path):
    configured = with_token(settings, tmp_path, "from-env")

    assert load_or_create_token(configured) == "from-env"
    assert not (tmp_path / TOKEN_FILE).exists()


@respx.mock
def test_routes_need_the_token_but_health_does_not(monkeypatch, settings, tmp_path):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(QDRANT_READY_URL).mock(return_value=httpx.Response(200))
    with make_client(monkeypatch, with_token(settings, tmp_path, "s3cret"), tmp_path) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/habits").status_code == 401
        wrong = client.get("/habits", headers={"Authorization": "Bearer nope"})
        right = client.get("/habits", headers={"Authorization": "Bearer s3cret"})

    assert wrong.status_code == 401
    assert right.status_code == 200
