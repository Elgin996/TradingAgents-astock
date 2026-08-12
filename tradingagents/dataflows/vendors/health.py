"""In-process vendor circuit breakers with observable state transitions."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    clock: callable = time.monotonic
    state: str = "closed"
    consecutive_failures: int = 0
    opened_at: float | None = None

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        now = self.clock()
        if self.state == "open" and self.opened_at is not None and now - self.opened_at >= self.cooldown_seconds:
            self.state = "half_open"
            return True
        return self.state == "half_open"

    def record_success(self) -> None:
        self.state = "closed"
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.state == "half_open" or self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = self.clock()


class VendorHealthRegistry:
    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 60.0, clock=time.monotonic):
        self._kwargs = {"failure_threshold": failure_threshold, "cooldown_seconds": cooldown_seconds, "clock": clock}
        self._breakers: dict[str, CircuitBreaker] = {}

    def breaker(self, source: str) -> CircuitBreaker:
        if source not in self._breakers:
            self._breakers[source] = CircuitBreaker(**self._kwargs)
        return self._breakers[source]

    def allow(self, source: str) -> bool:
        return self.breaker(source).allow_request()

    def record_success(self, source: str) -> None:
        self.breaker(source).record_success()

    def record_failure(self, source: str) -> None:
        self.breaker(source).record_failure()

