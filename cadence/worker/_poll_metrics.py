from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

from cadence._internal.rpc.retry import RETRYABLE_CODES
from cadence.error import CadenceRpcError
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    POLLER_START_COUNTER,
    WORKER_PANIC_COUNTER,
    WORKER_START_COUNTER,
)
from cadence.worker._poller import Poller

T = TypeVar("T")


@dataclass
class PollMetrics:
    emitter: MetricsEmitter
    tags: dict[str, str]
    poll: str
    latency: str
    succeed: str
    no_task: str
    failed: str
    transient_failed: str
    scheduled_to_start: str

    def start_poll(self) -> float:
        self.emitter.counter(self.poll, tags=self.tags)
        return time.monotonic()

    def record_failure(self, start: float, error: CadenceRpcError) -> None:
        self.emitter.histogram(self.latency, time.monotonic() - start, tags=self.tags)
        metric = self.transient_failed if error.code in RETRYABLE_CODES else self.failed
        self.emitter.counter(metric, tags=self.tags)

    def record_result(self, start: float, task: Any) -> None:
        """Record latency, then succeed vs idle, and optional schedule-to-start lag."""
        self.emitter.histogram(self.latency, time.monotonic() - start, tags=self.tags)
        if not (task and task.task_token):
            self.emitter.counter(self.no_task, tags=self.tags)
            return
        self.emitter.counter(self.succeed, tags=self.tags)
        s, e = task.scheduled_time, task.started_time
        if s.seconds and e.seconds:
            lag = (e.seconds + e.nanos / 1e9) - (s.seconds + s.nanos / 1e9)
            self.emitter.histogram(self.scheduled_to_start, lag, tags=self.tags)


async def run_with_lifecycle_metrics(
    emitter: MetricsEmitter,
    poller: Poller[T],
    *,
    num_pollers: int,
    tags: dict[str, str],
) -> None:
    emitter.counter(WORKER_START_COUNTER, tags=tags)
    emitter.counter(POLLER_START_COUNTER, num_pollers, tags=tags)
    try:
        await poller.run()
    except Exception:
        emitter.counter(WORKER_PANIC_COUNTER, tags=tags)
        raise
