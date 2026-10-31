"""Long-term memory of facts about the user (stored in the `user_facts` collection).

Facts are embedded like documents. Before storing a new fact we search for a very
similar one (cosine similarity ≥ FACT_DEDUP_THRESHOLD); if found, we update it instead
of inserting a duplicate. Nemotron extracts facts from free text, with thinking off
(a cheap structured task).
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from assistant.agent.prompts import EXTRACT_FACTS_SYSTEM
from assistant.config import Settings
from assistant.ingest.pipeline import SupportsEmbed
from assistant.memory.store import MemoryStore

logger = logging.getLogger("assistant.memory")

Category = Literal["preference", "personal", "work", "goal", "other"]


class SupportsComplete(Protocol):
    async def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...


class ExtractedFact(BaseModel):
    fact: str
    category: Category = "other"


class ExtractedFacts(BaseModel):
    facts: list[ExtractedFact]


class RememberResult(BaseModel):
    id: str
    fact: str
    category: str
    created: bool  # False when an existing near-duplicate was updated


def parse_facts_json(content: str) -> list[ExtractedFact]:
    """Parse the model's JSON output, tolerating code fences or extra prose around it."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return []
    try:
        return ExtractedFacts.model_validate(json.loads(match.group(0))).facts
    except (json.JSONDecodeError, ValidationError):
        logger.warning("fact_extraction_invalid_json")
        return []


class FactMemory:
    def __init__(
        self,
        store: MemoryStore,
        embedder: SupportsEmbed,
        chat: SupportsComplete,
        settings: Settings,
    ):
        self._store = store
        self._embedder = embedder
        self._chat = chat
        self._settings = settings

    async def remember(
        self, fact: str, category: str = "other", source: str = "conversation"
    ) -> RememberResult:
        fact = fact.strip()
        vector = (await self._embedder.embed([fact]))[0]
        now = datetime.now(UTC).isoformat()
        similar = await self._store.search_facts(
            vector, limit=1, min_score=self._settings.fact_dedup_threshold
        )
        if similar:
            existing = similar[0]
            payload = {**(existing.payload or {}), "fact": fact, "updated_at": now}
            await self._store.upsert_fact(str(existing.id), vector, payload)
            return RememberResult(
                id=str(existing.id), fact=fact, category=payload["category"], created=False
            )

        fact_id = str(uuid.uuid4())
        payload = {
            "fact": fact,
            "category": category,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        await self._store.upsert_fact(fact_id, vector, payload)
        return RememberResult(id=fact_id, fact=fact, category=category, created=True)

    async def extract(self, message: str) -> list[ExtractedFact]:
        response = await self._chat.complete(
            [
                {"role": "system", "content": EXTRACT_FACTS_SYSTEM},
                {"role": "user", "content": message},
            ],
            thinking=False,
            max_tokens=400,
        )
        return parse_facts_json(response.content or "")

    async def learn(self, message: str, source: str = "conversation") -> list[RememberResult]:
        """Extract durable facts from a message and store them (deduplicated)."""
        facts = await self.extract(message)
        return [await self.remember(f.fact, f.category, source) for f in facts]

    async def relevant(self, query_vector: list[float], *, k: int = 5) -> list[str]:
        """Facts related to the current question, to personalize the answer."""
        points = await self._store.search_facts(query_vector, limit=k, min_score=0.2)
        return [p.payload["fact"] for p in points if p.payload]

    async def list(self) -> list[dict[str, Any]]:
        return await self._store.list_facts()

    async def forget(self, fact_id: str) -> bool:
        return await self._store.delete_fact(fact_id)
