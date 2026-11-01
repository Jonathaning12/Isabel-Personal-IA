"""Episodes: short summaries of past conversations (the `episodes` collection).

Every few turns the current conversation is summarized in one to three sentences and
stored under an id derived from its thread, so a conversation always has one, up-to-date
summary. At the start of each turn the summaries most related to the new message (from
OTHER conversations) go into the prompt, with their date: Isabel can then say "la semana
pasada me pediste…". Summaries are embedded and stored locally like facts; the user can
list and delete them.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from assistant.agent.prompts import SUMMARIZE_EPISODE_SYSTEM
from assistant.config import Settings
from assistant.ingest.pipeline import SupportsEmbed
from assistant.memory.facts import SupportsComplete
from assistant.memory.store import MemoryStore

logger = logging.getLogger("assistant.episodes")

EPISODE_NAMESPACE = uuid.UUID("6f1c5a52-58a4-4a4e-9d55-2a3c1b7e0e11")
MAX_TRANSCRIPT_CHARS = 6000
MIN_USER_TURNS = 2  # a single question and answer is not worth a summary
SUMMARIZE_EVERY = 3  # turns between summary updates (2, 5, 8, …)


def episode_id(thread_id: str) -> str:
    return str(uuid.uuid5(EPISODE_NAMESPACE, thread_id))


def due_for_summary(messages: list[dict[str, Any]]) -> bool:
    """Summarize at the 2nd user turn and then every 3 turns."""
    turns = sum(1 for m in messages if m.get("role") == "user")
    return turns >= MIN_USER_TURNS and (turns - MIN_USER_TURNS) % SUMMARIZE_EVERY == 0


def transcript(messages: list[dict[str, Any]]) -> str:
    """The user's and Isabel's words only (no tool calls or results), most recent last."""
    lines = [
        f"{'Usuario' if m['role'] == 'user' else 'Isabel'}: {m['content']}"
        for m in messages
        if m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ]
    return "\n".join(lines)[-MAX_TRANSCRIPT_CHARS:]


class EpisodeMemory:
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

    async def summarize(self, thread_id: str, messages: list[dict[str, Any]]) -> str | None:
        """Write (or rewrite) this conversation's summary. Returns it, or None if empty."""
        text = transcript(messages)
        if not text:
            return None
        response = await self._chat.complete(
            [
                {"role": "system", "content": SUMMARIZE_EPISODE_SYSTEM},
                {"role": "user", "content": text},
            ],
            thinking=False,
            max_tokens=200,
        )
        summary = (response.content or "").strip()
        if not summary:
            return None
        vector = (await self._embedder.embed([summary]))[0]
        point = episode_id(thread_id)
        now = datetime.now(UTC).isoformat()
        existing = await self._store.client.retrieve(
            self._store.episodes, ids=[point], with_payload=True
        )
        started = (existing[0].payload or {}).get("started_at", now) if existing else now
        payload = {
            "thread_id": thread_id,
            "summary": summary,
            "started_at": started,
            "ended_at": now,
        }
        await self._store.upsert_episode(point, vector, payload)
        return summary

    async def relevant(
        self, query_vector: list[float], thread_id: str | None, *, k: int = 2
    ) -> list[str]:
        """Summaries of other conversations related to the current message, with their date."""
        points = await self._store.search_episodes(
            query_vector,
            limit=k,
            min_score=self._settings.episode_min_score,
            exclude_thread=thread_id,
        )
        return [
            f"({p.payload['ended_at'][:10]}) {p.payload['summary']}" for p in points if p.payload
        ]

    async def own(self, thread_id: str) -> str | None:
        """This conversation's summary, used when its older messages are not sent."""
        found = await self._store.client.retrieve(
            self._store.episodes, ids=[episode_id(thread_id)], with_payload=True
        )
        return (found[0].payload or {}).get("summary") if found else None

    async def list(self) -> list[dict[str, Any]]:
        return await self._store.list_episodes()

    async def forget(self, episode: str) -> bool:
        return await self._store.delete_episode(episode)
