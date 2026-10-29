"""Ingestion pipeline: file → text → sanitize → chunks → embeddings → Qdrant.

Idempotent: each file is identified by its path and fingerprinted with SHA-256.
- Same path, same content  → skipped ("unchanged"), no Nebius calls.
- Same path, new content   → old chunks deleted, new ones stored.
Point IDs are derived from (sha256, chunk index), so re-runs never duplicate points.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any, Literal, Protocol

from qdrant_client import models

from assistant.config import Settings
from assistant.guardrails.sanitize import is_suspicious, normalize_text
from assistant.ingest.chunking import chunk_text
from assistant.ingest.loaders import UnsupportedFileError, is_markdown, load_text
from assistant.memory.store import MemoryStore

NAMESPACE = uuid.UUID("6f1c2a1e-5b7d-4d8e-9a39-0c6d1f2b7e11")
# Bump when chunking/embedding changes, so unchanged files are re-indexed with the new logic.
PIPELINE_VERSION = "2"


class SupportsEmbed(Protocol):
    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]: ...


@dataclass
class IngestResult:
    source_path: str
    status: Literal["indexed", "unchanged", "skipped", "error"]
    chunks: int = 0
    message: str = ""


def _title(source_path: str, text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return PurePath(source_path).stem


def contextualize(title: str, heading: str | None, text: str) -> str:
    header = f"{title} › {heading}" if heading and heading != title else title
    return f"{header}\n\n{text}"


class Ingestor:
    def __init__(self, store: MemoryStore, embedder: SupportsEmbed, settings: Settings):
        self._store = store
        self._embedder = embedder
        self._settings = settings

    async def ingest(self, source_path: str, data: bytes) -> IngestResult:
        # Fingerprint = file content + pipeline version.
        sha = hashlib.sha256(PIPELINE_VERSION.encode() + b":" + data).hexdigest()
        existing_sha = await self._store.get_document_sha(source_path)
        if existing_sha == sha:
            return IngestResult(source_path, "unchanged")

        try:
            text = normalize_text(load_text(source_path, data))
        except UnsupportedFileError as exc:
            return IngestResult(source_path, "skipped", message=str(exc))
        except Exception as exc:  # corrupt PDF, etc.
            return IngestResult(source_path, "error", message=f"{type(exc).__name__}: {exc}")
        if not text:
            return IngestResult(source_path, "skipped", message="No text found")

        chunks = chunk_text(
            text,
            max_chars=self._settings.chunk_max_chars,
            overlap_chars=self._settings.chunk_overlap_chars,
            markdown=is_markdown(source_path),
        )
        # Contextual chunk headers: embed each chunk with its document title and section,
        # so a chunk like "Acciones acordadas" still "knows" it belongs to "Sprint 12".
        title = _title(source_path, text)
        vectors = await self._embedder.embed(
            [contextualize(title, c.heading, c.text) for c in chunks]
        )

        now = datetime.now(UTC).isoformat()
        doc_id = str(uuid.uuid5(NAMESPACE, source_path))
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(NAMESPACE, f"{sha}:{c.index}")),
                vector=vector,
                payload={
                    "doc_id": doc_id,
                    "source_path": source_path,
                    "title": title,
                    "sha256": sha,
                    "chunk_idx": c.index,
                    "heading": c.heading,
                    "text": c.text,
                    "suspicious": is_suspicious(c.text),
                    "created_at": now,
                },
            )
            for c, vector in zip(chunks, vectors, strict=True)
        ]

        if existing_sha is not None:
            await self._store.delete_document(source_path)
        await self._store.upsert_chunks(points)
        return IngestResult(source_path, "indexed", chunks=len(points))
