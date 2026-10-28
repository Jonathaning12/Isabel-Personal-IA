"""FastAPI application entry point.

Clients are created once at startup (lifespan) and shared through app.state.
Startup fails fast if the Qdrant collections do not match EMBED_DIM.
Run locally: uv run uvicorn assistant.api.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from assistant.agent.graph import AgentDeps, build_graph
from assistant.api.routes import chat as chat_routes
from assistant.api.routes import health, memory
from assistant.config import get_settings
from assistant.guardrails.audit import AuditLog
from assistant.ingest.pipeline import Ingestor
from assistant.llm.chat import ChatClient
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder
from assistant.memory.facts import FactMemory
from assistant.memory.retrieval import Retriever
from assistant.memory.store import MemoryStore, build_qdrant
from assistant.sandbox.docker_runner import DockerRunner

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

    # Conversation state (LangGraph checkpoints) persists in data/checkpoints.sqlite.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(
        str(settings.data_dir / "checkpoints.sqlite")
    ) as checkpointer:
        deps = AgentDeps(
            chat=chat,
            retriever=app.state.retriever,
            facts=app.state.facts,
            sandbox=DockerRunner(settings),
            audit=AuditLog(settings.data_dir / "audit.log"),
            settings=settings,
        )
        app.state.graph = build_graph(deps, checkpointer)
        yield
    await qdrant.close()
    await client.close()


app = FastAPI(title="Personal AI Assistant", lifespan=lifespan)
app.include_router(health.router)
app.include_router(memory.router)
app.include_router(chat_routes.router)
