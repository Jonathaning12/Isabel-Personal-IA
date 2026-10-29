"""Semantic search over the user's documents (the "R" in RAG).

The question is embedded and Qdrant returns the closest chunks by cosine similarity.
Qwen3-Embedding works best when *queries* carry a short task instruction while
*documents* are embedded as-is (asymmetric retrieval), so we add one here.
"""

from collections import OrderedDict
from dataclasses import dataclass

from assistant.config import Settings
from assistant.ingest.pipeline import SupportsEmbed
from assistant.memory.store import MemoryStore

QUERY_INSTRUCTION = (
    "Instruct: Given a question from the user, retrieve passages from their personal notes "
    "that answer it\nQuery: "
)


@dataclass
class Citation:
    n: int
    source_path: str
    title: str | None
    heading: str | None
    text: str
    score: float
    suspicious: bool


QUERY_CACHE_SIZE = 256


class Retriever:
    def __init__(self, store: MemoryStore, embedder: SupportsEmbed, settings: Settings):
        self._store = store
        self._embedder = embedder
        self._settings = settings
        # Query embeddings are cached in memory: a repeated question skips the Nebius call.
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    async def embed_query(self, query: str) -> list[float]:
        key = query.strip()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        vector = (
            await self._embedder.embed(
                [QUERY_INSTRUCTION + key],
                timeout_s=self._settings.query_embed_timeout_s,
                max_attempts=self._settings.query_embed_attempts,
            )
        )[0]
        self._cache[key] = vector
        if len(self._cache) > QUERY_CACHE_SIZE:
            self._cache.popitem(last=False)
        return vector

    async def search(self, query: str, *, k: int | None = None) -> list[Citation]:
        return await self.search_by_vector(await self.embed_query(query), k=k)

    async def search_by_vector(
        self, vector: list[float], *, k: int | None = None
    ) -> list[Citation]:
        points = await self._store.search_documents(
            vector,
            limit=k or self._settings.retrieval_top_k,
            min_score=self._settings.retrieval_min_score,
        )
        citations = []
        for p in points:
            payload = p.payload or {}
            citations.append(
                Citation(
                    n=len(citations) + 1,
                    source_path=payload["source_path"],
                    title=payload.get("title"),
                    heading=payload.get("heading"),
                    text=payload["text"],
                    score=round(p.score, 4),
                    suspicious=bool(payload.get("suspicious")),
                )
            )
        return citations
