"""Live tests against the real Nebius API (uses .env). Opt-in: uv run pytest -m live"""

import pytest

from assistant.config import get_settings
from assistant.llm.chat import ChatClient
from assistant.llm.client import build_client
from assistant.llm.embeddings import Embedder

pytestmark = pytest.mark.live


async def test_live_chat_and_stream():
    settings = get_settings()
    chat = ChatClient(build_client(settings), settings)
    messages = [{"role": "user", "content": "Responde solo con: hola"}]

    message = await chat.complete(messages, thinking=False, max_tokens=50)
    assert "hola" in (message.content or "").lower()

    chunks = [c async for c in chat.stream(messages, thinking=False, max_tokens=50)]
    assert "hola" in "".join(chunks).lower()


async def test_live_embedding_dimension():
    settings = get_settings()
    embedder = Embedder(build_client(settings), settings)

    vector = await embedder.embed_one("ping")

    assert len(vector) == settings.embed_dim
