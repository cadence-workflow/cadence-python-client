from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from google.protobuf import timestamp_pb2

from cadence._internal.rpc.retry import RETRYABLE_CODES
from cadence.error import CadenceRpcError
from cadence.metrics import (
    duration_between,
    duration_from_nanoseconds,
    MetricsEmitter,
)


class PollTask(Protocol):
    task_token: bytes
    scheduled_time: timestamp_pb2.Timestamp
    started_time: timestamp_pb2.Timestamp


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
    async def track(self) -> AsyncIterator[None]:
        """Emit poll counter; guarantee exactly one outcome counter on error."""
        self.emitter.counter(self.poll)
        start = time.monotonic_ns()
        try:
            yield
        except CadenceRpcError as e:
            metric = self.transient_failed if e.code in RETRYABLE_CODES else self.failed
            self.emitter.counter(metric)
            raise
        except Exception:
            self.emitter.counter(self.failed)
            raise
        finally:
            self.emitter.histogram(
                self.latency,
                duration_from_nanoseconds(time.monotonic_ns() - start),
            )

    def record_result(self, task: PollTask) -> None:
        """Record succeed vs idle and optional schedule-to-start latency."""
        if not (task and task.task_token):
            self.emitter.counter(self.no_task)
            return
        self.emitter.counter(self.succeed)
        latency = duration_between(task.scheduled_time, task.started_time)
        if latency is not None and latency >= timedelta(0):
            self.emitter.histogram(self.scheduled_to_start, latency)
