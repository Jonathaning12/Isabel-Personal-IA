"""FastAPI application entry point.

Clients are created once at startup (lifespan) and shared through app.state.
Startup fails fast if the Qdrant collections do not match EMBED_DIM.
Run locally: uv run uvicorn assistant.api.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from assistant.api.routes import health, memory
from assistant.config import get_settings
from assistant.ingest.pipeline import Ingestor
from assistant.llm.chat import ChatClient
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder
from assistant.memory.facts import FactMemory
from assistant.memory.retrieval import Retriever
from assistant.memory.store import MemoryStore, build_qdrant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    client = build_client(settings)
    qdrant = build_qdrant(settings)
    store = MemoryStore(qdrant, settings.embed_dim)
    await store.ensure_collections()

    chat = ChatClient(client, settings)
    embedder = Embedder(client, settings)
    app.state.settings = settings
    app.state.openai = client
    app.state.chat = chat
    app.state.embedder = embedder
    app.state.store = store
    app.state.ingestor = Ingestor(store, embedder, settings)
    app.state.retriever = Retriever(store, embedder, settings)
    app.state.facts = FactMemory(store, embedder, chat, settings)
    yield
    await qdrant.close()
    await client.close()


app = FastAPI(title="Personal AI Assistant", lifespan=lifespan)
app.include_router(health.router)
app.include_router(memory.router)
