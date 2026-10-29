"""Nebius Token Factory client factory and retry policy.

Every LLM and embedding call in the app goes through the AsyncOpenAI client built
here (hackathon requirement: all runtime inference on Nebius). The SDK's own retries
are disabled so the retry policy is explicit, logged, and testable.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

from assistant.config import Settings

logger = logging.getLogger("assistant.llm")

# Transient errors worth retrying: rate limits (429), server errors (5xx), timeouts,
# network failures. 4xx validation/auth errors are never retried.
RETRYABLE_ERRORS = (RateLimitError, InternalServerError, APITimeoutError, APIConnectionError)
MAX_ATTEMPTS = 4
DEFAULT_WAIT: wait_base = wait_exponential_jitter(initial=1, max=10)


def build_client(settings: Settings, *, http_client: Any = None) -> AsyncOpenAI:
    """Create the single AsyncOpenAI client pointed at Nebius Token Factory.

    `http_client` is only for tests (inject an httpx client that respx can mock).
    """
    return AsyncOpenAI(
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key.get_secret_value(),
        max_retries=0,
        http_client=http_client,
    )


def _log_retry(state: RetryCallState) -> None:
    error = state.outcome.exception() if state.outcome else None
    logger.warning("nebius_retry attempt=%d error=%s", state.attempt_number, type(error).__name__)


async def call_with_retries[T](
    fn: Callable[[], Awaitable[T]],
    *,
    wait: wait_base | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> T:
    """Run an async Nebius call, retrying transient errors with exponential backoff."""
    retrying = AsyncRetrying(
        retry=retry_if_exception_type(RETRYABLE_ERRORS),
        stop=stop_after_attempt(max_attempts),
        wait=wait or DEFAULT_WAIT,
        before_sleep=_log_retry,
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            return await fn()
    raise AssertionError("unreachable")  # pragma: no cover
