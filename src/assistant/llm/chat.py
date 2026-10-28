"""Chat completions with Nemotron on Nebius (plain and streaming).

Nemotron 3 is a reasoning model: it "thinks" before answering, and those thinking
tokens count against max_tokens. Use thinking=True for agent decisions and
thinking=False for cheap tasks (routing, extraction), which is faster.
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from tenacity.wait import wait_base

from assistant.config import Settings
from assistant.llm.client import call_with_retries

logger = logging.getLogger("assistant.llm")


class ChatClient:
    def __init__(self, client: AsyncOpenAI, settings: Settings, *, wait: wait_base | None = None):
        self._client = client
        self._settings = settings
        self._wait = wait

    def _params(
        self,
        messages: list[dict[str, Any]],
        *,
        thinking: bool,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "max_tokens": max_tokens or self._settings.max_completion_tokens,
            "timeout": self._settings.llm_timeout_s,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": thinking}},
        }
        if tools:
            params["tools"] = tools
        return params

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        thinking: bool = True,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionMessage:
        """Return the assistant message (content stripped; may contain tool_calls)."""
        params = self._params(messages, thinking=thinking, max_tokens=max_tokens, tools=tools)
        start = time.perf_counter()
        response = await call_with_retries(
            lambda: self._client.chat.completions.create(**params), wait=self._wait
        )
        usage = response.usage
        logger.info(
            "nebius_chat model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s finish=%s",
            self._settings.llm_model,
            (time.perf_counter() - start) * 1000,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            response.choices[0].finish_reason,
        )
        message = response.choices[0].message
        if message.content:
            # Reasoning models often prefix the answer with blank lines.
            message.content = message.content.strip()
        return message

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        thinking: bool = True,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield answer text chunks as they arrive. Only opening the stream is retried."""
        params = self._params(messages, thinking=thinking, max_tokens=max_tokens, tools=None)
        stream = await call_with_retries(
            lambda: self._client.chat.completions.create(stream=True, **params), wait=self._wait
        )
        started = False
        async for chunk in stream:
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content or ""
            if not started:
                # Drop leading blank lines before the first real token.
                text = text.lstrip()
                started = bool(text)
            if text:
                yield text
