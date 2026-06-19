from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from cadence._internal.rpc.retry import RETRYABLE_CODES
from cadence.error import CadenceRpcError
from cadence.metrics import MetricsEmitter


class _Timestamp(Protocol):
    seconds: int
    nanos: int


class PollTask(Protocol):
    task_token: bytes
    scheduled_time: _Timestamp
    started_time: _Timestamp


@dataclass
class PollMetrics:
    emitter: MetricsEmitter  # should be pre-tagged via emitter.with_tags(...)
    poll: str
    latency: str
    succeed: str
    no_task: str
    failed: str
    transient_failed: str
    scheduled_to_start: str

    @contextlib.asynccontextmanager
    async def track(self) -> AsyncIterator[float]:
        """Emit poll counter; guarantee exactly one outcome counter on error."""
        self.emitter.counter(self.poll)
        start = time.monotonic()
        try:
            yield start
        except CadenceRpcError as e:
            self.emitter.histogram(self.latency, time.monotonic() - start)
            metric = self.transient_failed if e.code in RETRYABLE_CODES else self.failed
            self.emitter.counter(metric)
            raise
        except Exception:
            self.emitter.counter(self.failed)
            raise

    def record_result(self, start: float, task: PollTask) -> None:
        """Record latency, then succeed vs idle, and optional schedule-to-start lag."""
        self.emitter.histogram(self.latency, time.monotonic() - start)
        if not (task and task.task_token):
            self.emitter.counter(self.no_task)
            return
        self.emitter.counter(self.succeed)
        s, e = task.scheduled_time, task.started_time
        if s.seconds and e.seconds:
            lag = (e.seconds + e.nanos / 1e9) - (s.seconds + s.nanos / 1e9)
            self.emitter.histogram(self.scheduled_to_start, lag)
