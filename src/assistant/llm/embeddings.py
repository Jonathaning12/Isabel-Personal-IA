"""Text embeddings on Nebius, batched, with a dimension check.

An embedding turns text into a vector of numbers that represents its meaning.
Qdrant needs a fixed vector size, so every vector is checked against EMBED_DIM.
"""

import logging
import time

from openai import AsyncOpenAI
from tenacity.wait import wait_base

from assistant.config import Settings
from assistant.llm.client import MAX_ATTEMPTS, call_with_retries

logger = logging.getLogger("assistant.llm")


class EmbeddingDimensionError(RuntimeError):
    """The model returned vectors whose size does not match EMBED_DIM."""


class Embedder:
    def __init__(self, client: AsyncOpenAI, settings: Settings, *, wait: wait_base | None = None):
        self._client = client
        self._settings = settings
        self._wait = wait

    async def embed(
        self,
        texts: list[str],
        *,
        timeout_s: float | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> list[list[float]]:
        """Embed texts in batches of EMBED_BATCH_SIZE, preserving input order.

        Interactive paths (the user's question) pass a shorter timeout and fewer attempts,
        so a slow embedding service fails fast instead of blocking the chat for minutes.
        """
        vectors: list[list[float]] = []
        size = self._settings.embed_batch_size
        for i in range(0, len(texts), size):
            batch = texts[i : i + size]
            start = time.perf_counter()
            response = await call_with_retries(
                lambda batch=batch: self._client.embeddings.create(
                    model=self._settings.embed_model,
                    input=batch,
                    timeout=timeout_s or self._settings.embed_timeout_s,
                ),
                wait=self._wait,
                max_attempts=max_attempts,
            )
            logger.info(
                "nebius_embed model=%s batch=%d latency_ms=%d",
                self._settings.embed_model,
                len(batch),
                (time.perf_counter() - start) * 1000,
            )
            # Gemini omits `index`; its vectors already come in input order.
            ordered = sorted(
                enumerate(response.data),
                key=lambda pair: pair[1].index if pair[1].index is not None else pair[0],
            )
            for _, item in ordered:
                if len(item.embedding) != self._settings.embed_dim:
                    raise EmbeddingDimensionError(
                        f"Got dimension {len(item.embedding)}, "
                        f"expected EMBED_DIM={self._settings.embed_dim}"
                    )
                vectors.append(item.embedding)
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
