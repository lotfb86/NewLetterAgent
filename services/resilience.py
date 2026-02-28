"""Resilience primitives for external service calls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")

# Transient exceptions worth retrying.  Non-transient errors like
# ValueError / TypeError / KeyError should fail immediately.
_RETRYABLE_EXCEPTIONS = (
    OSError,
    ConnectionError,
    TimeoutError,
    RuntimeError,
)


class ExternalServiceError(RuntimeError):
    """Raised when an external dependency call fails after retries."""


class CircuitBreakerOpenError(ExternalServiceError):
    """Raised when a circuit breaker rejects a call while open."""


class CircuitBreakerState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Simple thread-safe circuit breaker."""

    name: str
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0

    def before_call(self) -> None:
        """Validate whether a call is allowed in the current state."""
        now = time.monotonic()
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if now - self._opened_at >= self.recovery_timeout_seconds:
                    self._state = CircuitBreakerState.HALF_OPEN
                else:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker {self.name} is open; retry later"
                    )

    def record_success(self) -> None:
        """Reset breaker state on successful call."""
        with self._lock:
            self._failure_count = 0
            self._state = CircuitBreakerState.CLOSED
            self._opened_at = 0.0

    def record_failure(self) -> None:
        """Track call failure and open breaker if threshold exceeded."""
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitBreakerState.OPEN
                self._opened_at = time.monotonic()

    @property
    def state(self) -> CircuitBreakerState:
        """Expose current breaker state for logging and tests."""
        with self._lock:
            return self._state


class ResiliencePolicy:
    """Retry and circuit-breaker execution policy."""

    def __init__(
        self,
        *,
        name: str,
        max_attempts: int,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        self.name = name
        self.max_attempts = max_attempts
        self.breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout_seconds=recovery_timeout_seconds,
        )

    def execute(self, operation: Callable[[], T]) -> T:
        """Execute operation with retry and breaker behavior."""
        self.breaker.before_call()

        retryer = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential_jitter(initial=0.25, max=8.0),
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            reraise=True,
        )

        try:
            result = retryer(operation)
        except CircuitBreakerOpenError:
            raise
        except RetryError as exc:  # pragma: no cover
            self.breaker.record_failure()
            root = _root_cause(exc)
            raise ExternalServiceError(
                f"{self.name} failed after {self.max_attempts} attempts: {root}"
            ) from exc
        except Exception as exc:
            self.breaker.record_failure()
            raise ExternalServiceError(
                f"{self.name} failed after {self.max_attempts} attempts: {exc}"
            ) from exc

        self.breaker.record_success()
        return result


def _root_cause(exc: BaseException) -> str:
    """Walk the exception chain to find the root cause message."""
    current: BaseException | None = exc
    last_msg = str(exc)
    while current is not None:
        msg = str(current).strip()
        if msg:
            last_msg = msg
        current = current.__cause__ or current.__context__
        if current is exc:
            break
    return last_msg
