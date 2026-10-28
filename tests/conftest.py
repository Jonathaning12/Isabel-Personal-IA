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


class FakeEmbedder:
    """Deterministic embeddings: identical texts → identical vectors (cosine 1.0)."""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib

        self.calls += 1
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vectors.append([b / 255 + 0.01 for b in digest[: self.dim]])
        return vectors


class FakeChat:
    """Returns a scripted reply and records the messages it received."""

    def __init__(self, reply: str = ""):
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def complete(self, messages, **kwargs):
        from types import SimpleNamespace

        self.calls.append(messages)
        return SimpleNamespace(content=self.reply, tool_calls=None)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
async def store():
    """MemoryStore on an in-memory Qdrant (no Docker needed)."""
    from qdrant_client import AsyncQdrantClient

    from assistant.memory.store import MemoryStore

    client = AsyncQdrantClient(location=":memory:")
    memory_store = MemoryStore(client, dim=8)
    await memory_store.ensure_collections()
    yield memory_store
    await client.close()
