import httpx
import pytest
from openai import AsyncOpenAI

from assistant.config import Settings
from assistant.llm.client import build_client

FAKE_BASE_URL = "https://nebius.test/v1/"


@pytest.fixture
def settings() -> Settings:
    """Settings for unit tests: fake URL and key, never the real .env."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        nebius_api_key="test-key",
        nebius_base_url=FAKE_BASE_URL,
        llm_model="nvidia/test-llm",
        embed_model="test/embed",
        embed_dim=3,
        embed_batch_size=2,
        qdrant_url="http://qdrant.test:6333",
    )


def build_test_client(settings: Settings) -> AsyncOpenAI:
    """AsyncOpenAI on a classic httpx client so respx can intercept requests.

    The openai SDK 3.x defaults to httpx2, which respx does not mock.
    """
    return build_client(settings, http_client=httpx.AsyncClient())
