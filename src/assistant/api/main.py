"""FastAPI application entry point.

Clients are created once at startup (lifespan) and shared through app.state.
Startup fails fast if the Qdrant collections do not match EMBED_DIM.
Run locally: uv run uvicorn assistant.api.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from openai import APIConnectionError, APIStatusError

from assistant.agent.graph import AgentDeps, build_graph
from assistant.api.auth import load_or_create_token, require_token
from assistant.api.routes import chat as chat_routes
from assistant.api.routes import health, memory, projects, skills, vault, vision, voice
from assistant.config import get_settings
from assistant.guardrails.audit import AuditLog
from assistant.ingest.pipeline import Ingestor
from assistant.llm.chat import ChatClient
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder
from assistant.memory.facts import FactMemory
from assistant.memory.habits import HabitLog
from assistant.memory.retrieval import Retriever
from assistant.memory.store import MemoryStore, build_qdrant
from assistant.sandbox.docker_runner import DockerRunner
from assistant.skills.store import SkillStore
from assistant.vault.notes import Vault
from assistant.workspace.projects import Workspace

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
    app.state.api_token = load_or_create_token(settings)
    app.state.openai = client
    app.state.chat = chat
    app.state.embedder = embedder
    app.state.store = store
    app.state.ingestor = Ingestor(store, embedder, settings)
    app.state.retriever = Retriever(store, embedder, settings)
    app.state.facts = FactMemory(store, embedder, chat, settings)

    # Conversation state (LangGraph checkpoints) persists in data/checkpoints.sqlite.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.skills = SkillStore(settings.data_dir / "skills.json")
    app.state.habits = HabitLog(settings.data_dir / "habits.json")
    vault_dir = settings.vault_dir
    app.state.vault = (
        Vault(vault_dir, settings.data_dir / "note-backups")
        if vault_dir is not None and vault_dir.is_dir()
        else None
    )
    projects_dir = settings.projects_dir
    app.state.workspace = (
        Workspace(
            projects_dir,
            autocrlf=settings.git_autocrlf,
            github_token=settings.github_token.get_secret_value(),
        )
        if projects_dir is not None and projects_dir.is_dir()
        else None
    )
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
            skills=app.state.skills,
            vault=app.state.vault,
            ingestor=app.state.ingestor,
            workspace=app.state.workspace,
            habits=app.state.habits,
        )
        app.state.graph = build_graph(deps, checkpointer)
        yield
    await qdrant.close()
    await client.close()


app = FastAPI(title="Personal AI Assistant", lifespan=lifespan)
app.middleware("http")(require_token)


@app.exception_handler(APIConnectionError)  # includes timeouts
@app.exception_handler(APIStatusError)
async def nebius_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """Nebius failed after all retries: return a clear JSON 503 instead of a bare 500."""
    logging.getLogger("assistant.api").warning("nebius_unavailable error=%s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "nebius_unavailable", "error": type(exc).__name__},
    )


app.include_router(health.router)
app.include_router(memory.router)
app.include_router(chat_routes.router)
app.include_router(skills.router)
app.include_router(voice.router)
app.include_router(vault.router)
app.include_router(projects.router)
app.include_router(vision.router)
