"""Qdrant wrapper: the assistant's local long-term memory.

Three collections (think "tables" whose index is a meaning search):
- documents:  chunks of the user's files, each with its embedding vector.
- user_facts: durable facts about the user ("prefers bullet-point answers").
- episodes:   short summaries of past conversations, one per conversation.

Qdrant runs locally in Docker; nothing here leaves the machine.
"""

from typing import Any

from qdrant_client import AsyncQdrantClient, models

from assistant.config import Settings

DOCUMENTS = "documents"
USER_FACTS = "user_facts"
EPISODES = "episodes"
_INDEXED_FIELDS = {
    DOCUMENTS: ["source_path", "sha256", "doc_id"],
    USER_FACTS: ["category"],
    EPISODES: ["thread_id"],
}


class CollectionDimensionError(RuntimeError):
    """An existing collection was created with a different vector size than EMBED_DIM."""


def build_qdrant(settings: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.qdrant_url)


def _by_source(source_path: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="source_path", match=models.MatchValue(value=source_path))]
    )


class MemoryStore:
    def __init__(self, client: AsyncQdrantClient, dim: int, *, prefix: str = ""):
        self.client = client
        self.dim = dim
        # The prefix lets integration tests use throwaway collections.
        self.documents = f"{prefix}{DOCUMENTS}"
        self.user_facts = f"{prefix}{USER_FACTS}"
        self.episodes = f"{prefix}{EPISODES}"

    async def ensure_collections(self) -> None:
        """Create missing collections; fail fast if an existing one has the wrong size."""
        collections = (
            (self.documents, DOCUMENTS),
            (self.user_facts, USER_FACTS),
            (self.episodes, EPISODES),
        )
        for name, base in collections:
            if await self.client.collection_exists(name):
                info = await self.client.get_collection(name)
                size = info.config.params.vectors.size  # type: ignore[union-attr]
                if size != self.dim:
                    raise CollectionDimensionError(
                        f"Collection '{name}' has vector size {size}, but EMBED_DIM={self.dim}. "
                        "Use the original embedding model or delete the collection and re-ingest."
                    )
                continue
            await self.client.create_collection(
                name,
                vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
            )
            for field in _INDEXED_FIELDS[base]:
                await self.client.create_payload_index(
                    name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
                )

    async def count(self, collection: str) -> int:
        return (await self.client.count(collection, exact=True)).count

    # --- documents -------------------------------------------------------------

    async def get_document_sha(self, source_path: str) -> str | None:
        points, _ = await self.client.scroll(
            self.documents, scroll_filter=_by_source(source_path), limit=1, with_payload=["sha256"]
        )
        return points[0].payload["sha256"] if points and points[0].payload else None

    async def delete_document(self, source_path: str) -> int:
        """Physically delete all chunks of a document. Returns how many were removed."""
        flt = _by_source(source_path)
        removed = (await self.client.count(self.documents, count_filter=flt, exact=True)).count
        if removed:
            await self.client.delete(
                self.documents, points_selector=models.FilterSelector(filter=flt), wait=True
            )
        return removed

    async def upsert_chunks(self, points: list[models.PointStruct]) -> None:
        await self.client.upsert(self.documents, points=points, wait=True)

    async def search_documents(
        self, vector: list[float], *, limit: int, min_score: float
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            self.documents,
            query=vector,
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return response.points

    async def list_documents(self) -> list[dict[str, Any]]:
        """One entry per document: source_path, title and number of chunks."""
        docs: dict[str, dict[str, Any]] = {}
        offset = None
        while True:
            points, offset = await self.client.scroll(
                self.documents,
                limit=256,
                offset=offset,
                with_payload=["source_path", "title"],
            )
            for p in points:
                payload = p.payload or {}
                entry = docs.setdefault(
                    payload["source_path"],
                    {
                        "source_path": payload["source_path"],
                        "title": payload.get("title"),
                        "chunks": 0,
                    },
                )
                entry["chunks"] += 1
            if offset is None:
                return sorted(docs.values(), key=lambda d: d["source_path"])

    # --- user facts ------------------------------------------------------------

    async def search_facts(
        self, vector: list[float], *, limit: int, min_score: float
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            self.user_facts,
            query=vector,
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return response.points

    async def upsert_fact(self, fact_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        await self.client.upsert(
            self.user_facts,
            points=[models.PointStruct(id=fact_id, vector=vector, payload=payload)],
            wait=True,
        )

    async def list_facts(self) -> list[dict[str, Any]]:
        points, _ = await self.client.scroll(self.user_facts, limit=1000, with_payload=True)
        facts = [{"id": str(p.id), **(p.payload or {})} for p in points]
        return sorted(facts, key=lambda f: f.get("created_at", ""))

    async def delete_fact(self, fact_id: str) -> bool:
        found = await self.client.retrieve(self.user_facts, ids=[fact_id])
        if not found:
            return False
        await self.client.delete(
            self.user_facts, points_selector=models.PointIdsList(points=[fact_id]), wait=True
        )
        return True

    # --- episodes (conversation summaries) -----------------------------------------

    async def upsert_episode(
        self, episode_id: str, vector: list[float], payload: dict[str, Any]
    ) -> None:
        await self.client.upsert(
            self.episodes,
            points=[models.PointStruct(id=episode_id, vector=vector, payload=payload)],
        )

    async def search_episodes(
        self, vector: list[float], *, limit: int, min_score: float, exclude_thread: str | None
    ) -> list[models.ScoredPoint]:
        not_this = (
            models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="thread_id", match=models.MatchValue(value=exclude_thread)
                    )
                ]
            )
            if exclude_thread
            else None
        )
        response = await self.client.query_points(
            self.episodes,
            query=vector,
            query_filter=not_this,
            limit=limit,
            score_threshold=min_score,
            with_payload=True,
        )
        return response.points

    async def list_episodes(self) -> list[dict[str, Any]]:
        points, _ = await self.client.scroll(self.episodes, limit=1000, with_payload=True)
        episodes = [{"id": str(p.id), **(p.payload or {})} for p in points]
        return sorted(episodes, key=lambda e: e.get("ended_at", ""), reverse=True)

    async def delete_episode(self, episode_id: str) -> bool:
        if not await self.client.retrieve(self.episodes, ids=[episode_id]):
            return False
        await self.client.delete(
            self.episodes, points_selector=models.PointIdsList(points=[episode_id]), wait=True
        )
        return True
