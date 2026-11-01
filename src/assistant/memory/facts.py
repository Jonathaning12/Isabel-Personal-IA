"""Long-term memory of facts about the user (stored in the `user_facts` collection).

Facts are embedded like documents. Before storing a new fact we search for a very
similar one (cosine similarity ≥ FACT_DEDUP_THRESHOLD); if found, we update it instead
of inserting a duplicate. Facts on the same topic (≥ FACT_RELATED_THRESHOLD) are shown to
the model, which says which ones the new fact makes outdated ("vive en Monterrey" →
"se mudó a Guadalajara"); those are deleted. The model also extracts facts from free text
and proposes a tidy-up (merge duplicates, drop outdated facts) that the user reviews
before it is applied. All of these are cheap structured calls with thinking off.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from assistant.agent.prompts import (
    CONSOLIDATE_FACTS_SYSTEM,
    EXTRACT_FACTS_SYSTEM,
    FACT_CONFLICT_SYSTEM,
)
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
    replaced: list[str] = []  # outdated facts this one replaced (deleted)


class Merge(BaseModel):
    ids: list[str]
    fact: str
    category: Category = "other"


class ConsolidationPlan(BaseModel):
    """A proposed tidy-up of the memory; nothing changes until it is applied."""

    merge: list[Merge] = []
    drop: list[str] = []


def _json_object(content: str) -> dict[str, Any]:
    """The first JSON object in the model's output ({} if there is none)."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
            vector, limit=5, min_score=self._settings.fact_related_threshold
        )
        if similar and similar[0].score >= self._settings.fact_dedup_threshold:
            existing = similar[0]
            payload = {**(existing.payload or {}), "fact": fact, "updated_at": now}
            await self._store.upsert_fact(str(existing.id), vector, payload)
            return RememberResult(
                id=str(existing.id), fact=fact, category=payload["category"], created=False
            )

        replaced = await self._outdated_by(fact, similar)
        for old_id in replaced:
            await self._store.delete_fact(old_id)
        if replaced:
            logger.info("facts_replaced count=%d", len(replaced))
        fact_id = await self._insert(fact, vector, category, source)
        return RememberResult(
            id=fact_id, fact=fact, category=category, created=True, replaced=replaced
        )

    async def _insert(self, fact: str, vector: list[float], category: str, source: str) -> str:
        fact_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        payload = {
            "fact": fact,
            "category": category,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        await self._store.upsert_fact(fact_id, vector, payload)
        return fact_id

    async def _outdated_by(self, fact: str, related: list[Any]) -> list[str]:
        """Ids of the related facts that the new fact makes false (asked to the model)."""
        if not related:
            return []
        existing = {str(p.id): (p.payload or {}).get("fact", "") for p in related}
        listing = "\n".join(f"- [{fid}] {text}" for fid, text in existing.items())
        response = await self._chat.complete(
            [
                {"role": "system", "content": FACT_CONFLICT_SYSTEM},
                {"role": "user", "content": f"NEW: {fact}\nEXISTING:\n{listing}"},
            ],
            thinking=False,
            max_tokens=200,
        )
        ids = _json_object(response.content or "").get("replaces", [])
        return [i for i in ids if isinstance(i, str) and i in existing]

    async def plan_consolidation(self) -> ConsolidationPlan:
        """Ask the model how to tidy the memory. Only ids that exist are kept, each once."""
        facts = await self.list()
        if len(facts) < 2:
            return ConsolidationPlan()
        listing = "\n".join(
            f"- [{f['id']}] {f.get('fact', '')} ({f.get('category', 'other')}, "
            f"{str(f.get('updated_at', ''))[:10]})"
            for f in facts
        )
        response = await self._chat.complete(
            [
                {"role": "system", "content": CONSOLIDATE_FACTS_SYSTEM},
                {"role": "user", "content": listing},
            ],
            thinking=False,
            max_tokens=1500,
        )
        try:
            raw = ConsolidationPlan.model_validate(_json_object(response.content or ""))
        except ValidationError:
            return ConsolidationPlan()
        return _clean_plan(raw, {f["id"] for f in facts})

    async def apply_consolidation(self, plan: ConsolidationPlan) -> dict[str, int]:
        """Apply a plan the user reviewed (ids that no longer exist are skipped)."""
        plan = _clean_plan(plan, {f["id"] for f in await self.list()})
        for merge in plan.merge:
            for old_id in merge.ids:
                await self._store.delete_fact(old_id)
            vector = (await self._embedder.embed([merge.fact]))[0]
            await self._insert(merge.fact.strip(), vector, merge.category, "consolidated")
        for old_id in plan.drop:
            await self._store.delete_fact(old_id)
        return {"merged": len(plan.merge), "dropped": len(plan.drop)}

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


def _clean_plan(plan: ConsolidationPlan, existing: set[str]) -> ConsolidationPlan:
    """Keep only existing ids, each in a single action; a merge needs at least two facts."""
    used: set[str] = set()
    merges = []
    for merge in plan.merge:
        ids = [i for i in dict.fromkeys(merge.ids) if i in existing and i not in used]
        if len(ids) >= 2 and merge.fact.strip():
            used.update(ids)
            merges.append(merge.model_copy(update={"ids": ids}))
    drop = [i for i in dict.fromkeys(plan.drop) if i in existing and i not in used]
    return ConsolidationPlan(merge=merges, drop=drop)
