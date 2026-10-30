"""Unit tests for the Nebius client wrappers, with HTTP mocked by respx."""

import json

import httpx
import pytest
import respx
from openai import APITimeoutError, BadRequestError
from pydantic import SecretStr
from tenacity import wait_none

from assistant.llm.chat import ChatClient
from assistant.llm.client import MAX_ATTEMPTS
from assistant.llm.embeddings import Embedder, EmbeddingDimensionError
from tests.conftest import FAKE_BASE_URL, build_test_client

CHAT_URL = f"{FAKE_BASE_URL}chat/completions"
EMBED_URL = f"{FAKE_BASE_URL}embeddings"


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "nvidia/test-llm",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )


def embed_response(request: httpx.Request, dim: int = 3) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "test/embed",
            "data": [
                {"object": "embedding", "index": i, "embedding": [float(i)] * dim}
                for i in range(len(texts))
            ],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )


@pytest.fixture
def chat(settings) -> ChatClient:
    return ChatClient(build_test_client(settings), settings, wait=wait_none())


@pytest.fixture
def embedder(settings) -> Embedder:
    return Embedder(build_test_client(settings), settings, wait=wait_none())


@respx.mock
async def test_complete_strips_content_and_sends_thinking_flag(chat):
    route = respx.post(CHAT_URL).mock(return_value=chat_response("\n\nhola"))

    message = await chat.complete([{"role": "user", "content": "hi"}], thinking=False)

    assert message.content == "hola"
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "nvidia/test-llm"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@respx.mock
async def test_gemini_provider_uses_its_own_key_and_thinking_switch(settings):
    gemini = settings.model_copy(
        update={
            "llm_provider": "gemini",
            "gemini_api_key": SecretStr("gemini-key"),
            "gemini_base_url": FAKE_BASE_URL,
        }
    )
    route = respx.post(CHAT_URL).mock(return_value=chat_response("hola"))
    client = ChatClient(build_test_client(gemini), gemini, wait=wait_none())

    await client.complete([{"role": "user", "content": "hi"}], thinking=False)

    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer gemini-key"
    assert "chat_template_kwargs" not in body  # Nemotron-only parameter
    assert body["reasoning_effort"] == "minimal"


@respx.mock
async def test_rate_limit_is_retried(chat):
    route = respx.post(CHAT_URL).mock(
        side_effect=[httpx.Response(429, json={"error": "slow down"}), chat_response("ok")]
    )

    message = await chat.complete([{"role": "user", "content": "hi"}])

    assert message.content == "ok"
    assert route.call_count == 2


@respx.mock
async def test_timeout_retries_then_raises(chat):
    route = respx.post(CHAT_URL).mock(side_effect=httpx.ReadTimeout("timeout"))

    with pytest.raises(APITimeoutError):
        await chat.complete([{"role": "user", "content": "hi"}])

    assert route.call_count == MAX_ATTEMPTS


@respx.mock
async def test_bad_request_is_not_retried(chat):
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(400, json={"error": "bad"}))

    with pytest.raises(BadRequestError):
        await chat.complete([{"role": "user", "content": "hi"}])

    assert route.call_count == 1


@respx.mock
async def test_embeddings_are_batched_in_order(embedder):
    route = respx.post(EMBED_URL).mock(side_effect=embed_response)

    vectors = await embedder.embed(["a", "b", "c", "d", "e"])  # batch size 2 -> 3 calls

    assert route.call_count == 3
    assert len(vectors) == 5
    assert all(len(v) == 3 for v in vectors)


@respx.mock
async def test_embeddings_without_index_keep_input_order(embedder):
    def no_index(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [{"object": "embedding", "embedding": [float(len(t))] * 3} for t in texts]
        return httpx.Response(200, json={"object": "list", "model": "test/embed", "data": data})

    respx.post(EMBED_URL).mock(side_effect=no_index)

    vectors = await embedder.embed(["a", "bb", "ccc"])

    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]


@respx.mock
async def test_embedding_dimension_mismatch_raises(embedder):
    respx.post(EMBED_URL).mock(side_effect=lambda req: embed_response(req, dim=4))

    with pytest.raises(EmbeddingDimensionError):
        await embedder.embed_one("ping")
