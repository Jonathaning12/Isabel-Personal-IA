"""Integration tests against the real Qdrant from docker-compose (localhost:6333).

They use throwaway collections (prefix "test_") and never touch real data.
Run: docker compose up -d qdrant && uv run pytest -m integration
"""

import uuid

import pytest
from qdrant_client import AsyncQdrantClient

from assistant.ingest.pipeline import Ingestor
from assistant.memory.facts import FactMemory
from assistant.memory.store import CollectionDimensionError, MemoryStore
from tests.conftest import FakeChat

pytestmark = pytest.mark.integration


@pytest.fixture
async def real_store():
    client = AsyncQdrantClient(url="http://localhost:6333")
    prefix = f"test_{uuid.uuid4().hex[:8]}_"
    store = MemoryStore(client, dim=8, prefix=prefix)
    await store.ensure_collections()
    yield store
    for name in (store.documents, store.user_facts):
        await client.delete_collection(name)
    await client.close()


async def test_delete_document_physically_removes_points(real_store, fake_embedder, settings):
    ingestor = Ingestor(real_store, fake_embedder, settings)
    await ingestor.ingest("a.md", b"# A\n\nuno\n\n## B\n\ndos")
    assert await real_store.count(real_store.documents) == 2

    assert await real_store.delete_document("a.md") == 2
    assert await real_store.count(real_store.documents) == 0


async def test_forget_fact_physically_removes_point(real_store, fake_embedder, settings):
    facts = FactMemory(real_store, fake_embedder, FakeChat(), settings)
    result = await facts.remember("Le gusta el café.")

    assert await facts.forget(result.id)
    assert await real_store.count(real_store.user_facts) == 0


async def test_dimension_mismatch_against_real_server(real_store):
    other = MemoryStore(
        real_store.client, dim=16, prefix=real_store.documents.removesuffix("documents")
    )
    with pytest.raises(CollectionDimensionError):
        await other.ensure_collections()
