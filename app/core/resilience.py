"""Resilience primitives — Exponential Backoff & Circuit Breaker.

These are used by all external API integrations to handle transient
failures gracefully and prevent cascading failures.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ═══════════════════════════════════════════════════
#  Exponential Backoff
# ═══════════════════════════════════════════════════

@dataclass
class BackoffConfig:
    """Configuration for exponential backoff retries."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)


async def request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    config: BackoffConfig | None = None,
    **kwargs: object,
) -> httpx.Response:
    """Execute an HTTP request with exponential backoff on retryable errors.

    Args:
        client: httpx.AsyncClient instance.
        method: HTTP method (GET, POST, etc.).
        url: Target URL.
        config: Backoff configuration (uses defaults if None).
        **kwargs: Passed through to client.request().

    Returns:
        httpx.Response on success.

    Raises:
        httpx.HTTPStatusError: After all retries exhausted on retryable status.
        httpx.RequestError: On non-retryable network error.
    """
    if config is None:
        config = BackoffConfig()

    last_response: httpx.Response | None = None

    for attempt in range(config.max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.RequestError:
            if attempt == config.max_retries:
                raise
            delay = _calculate_delay(attempt, config)
            logger.warning(
                "Network error on %s %s (attempt %d/%d), retrying in %.1fs",
                method, url, attempt + 1, config.max_retries + 1, delay,
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code not in config.retryable_status_codes:
            return response

        last_response = response

        if attempt == config.max_retries:
            break

        delay = _calculate_delay(attempt, config)

        # Respect Retry-After header from rate-limited responses
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass

        logger.warning(
            "Retryable status %d on %s %s (attempt %d/%d), retrying in %.1fs",
            response.status_code, method, url,
            attempt + 1, config.max_retries + 1, delay,
        )
        await asyncio.sleep(delay)

    # All retries exhausted — return last response for caller to handle
    assert last_response is not None
    return last_response


def _calculate_delay(attempt: int, config: BackoffConfig) -> float:
    delay = config.base_delay * (config.exponential_base ** attempt)
    return min(delay, config.max_delay)


# ═══════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when the circuit is open and requests are blocked."""


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    - CLOSED: requests flow normally; failures are counted.
    - OPEN: requests are blocked immediately (fail fast).
    - HALF_OPEN: a single probe request is allowed; success resets,
      failure re-opens.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "Circuit breaker OPEN after %d failures", self._failure_count,
            )

    def ensure_closed(self) -> None:
        """Raise if circuit is open (fail fast)."""
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitBreakerOpen(
                f"Circuit is OPEN — service unavailable "
                f"(recovers in {self.recovery_timeout}s)"
            )
