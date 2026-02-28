"""Tests for resilience policies."""

from __future__ import annotations

import pytest

from services.resilience import (
    CircuitBreakerOpenError,
    CircuitBreakerState,
    ExternalServiceError,
    ResiliencePolicy,
)


def test_resilience_policy_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    policy = ResiliencePolicy(name="test", max_attempts=3)
    result = policy.execute(flaky)

    assert result == "ok"
    assert attempts["count"] == 3
    assert policy.breaker.state == CircuitBreakerState.CLOSED


def test_circuit_breaker_opens_after_failed_calls() -> None:
    policy = ResiliencePolicy(
        name="test",
        max_attempts=1,
        failure_threshold=2,
        recovery_timeout_seconds=60,
    )

    with pytest.raises(ExternalServiceError):
        policy.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail1")))
    with pytest.raises(ExternalServiceError):
        policy.execute(lambda: (_ for _ in ()).throw(RuntimeError("fail2")))

    assert policy.breaker.state == CircuitBreakerState.OPEN

    with pytest.raises(CircuitBreakerOpenError):
        policy.execute(lambda: "should not run")
