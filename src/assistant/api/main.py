"""FastAPI application entry point.

Clients are created once at startup (lifespan) and shared through app.state.
Run locally: uv run uvicorn assistant.api.main:app --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from assistant.api.routes import health
from assistant.config import get_settings
from assistant.llm.chat import ChatClient
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    client = build_client(settings)
    app.state.settings = settings
    app.state.openai = client
    app.state.chat = ChatClient(client, settings)
    app.state.embedder = Embedder(client, settings)
    yield
    await client.close()


app = FastAPI(title="Personal AI Assistant", lifespan=lifespan)
app.include_router(health.router)
