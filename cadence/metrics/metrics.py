"""Core metrics collection interface and registry for Cadence client."""

import logging
import time
from datetime import timedelta, timezone
from enum import Enum
from types import TracebackType
from typing import Callable, Dict, Optional, Protocol, cast

from google.protobuf.timestamp_pb2 import Timestamp

logger = logging.getLogger(__name__)

_NANOSECONDS_PER_SECOND = 1_000_000_000


class MetricType(Enum):
    """Types of metrics that can be collected."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class MetricsEmitter(Protocol):
    """Protocol for metrics collection backends."""

    def with_tags(self, tags: Dict[str, str]) -> "MetricsEmitter": ...

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a counter metric."""
        ...

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a gauge metric."""
        ...

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a histogram metric."""
        ...


def duration_between_ns(start: Timestamp, end: Timestamp) -> Optional[timedelta]:
    """Return a non-negative duration in nanoseconds (consistent with existing SDK) between two set protobuf timestamps."""
    if not _timestamp_is_set(start) or not _timestamp_is_set(end):
        return None
    return cast(
        timedelta,
        max(
            timedelta(0),
            end.ToDatetime(tzinfo=timezone.utc) - start.ToDatetime(tzinfo=timezone.utc),
        ),
    )


def record_duration(
    emitter: MetricsEmitter,
    key: str,
    value: timedelta,
    tags: Optional[Dict[str, str]] = None,
) -> None:
    """Record a non-negative duration in the nanoseconds expected by SDK metrics."""
    if value < timedelta(0):
        raise ValueError("Metric duration must be non-negative")
    nanoseconds = (
        value.days * 86_400 + value.seconds
    ) * _NANOSECONDS_PER_SECOND + value.microseconds * 1_000
    if tags is None:
        emitter.histogram(key, nanoseconds)
    else:
        emitter.histogram(key, nanoseconds, tags)


def _timestamp_is_set(timestamp: Timestamp) -> bool:
    return bool(timestamp.seconds or timestamp.nanos)


class MetricsStopwatch:
    """Monotonic stopwatch that records a duration metric exactly once."""

    def __init__(
        self,
        emitter: MetricsEmitter,
        key: str,
        tags: Optional[Dict[str, str]] = None,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._emitter = emitter
        self._key = key
        self._tags = tags
        self._clock_ns = clock_ns
        self._started_ns = clock_ns()
        self._elapsed_ns: Optional[int] = None

    def stop(self) -> int:
        """Record and return elapsed nanoseconds; repeated calls are no-ops."""
        if self._elapsed_ns is not None:
            return self._elapsed_ns
        elapsed_ns = max(0, self._clock_ns() - self._started_ns)
        if self._tags is None:
            self._emitter.histogram(self._key, elapsed_ns)
        else:
            self._emitter.histogram(self._key, elapsed_ns, self._tags)
        self._elapsed_ns = elapsed_ns
        return elapsed_ns

    def __enter__(self) -> "MetricsStopwatch":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.stop()


class _TaggedEmitter:
    """MetricsEmitter wrapper that pre-bakes a fixed set of tags into every call."""

    def __init__(self, base: MetricsEmitter, tags: Dict[str, str]) -> None:
        self._base = base
        self._tags = tags

    def with_tags(self, tags: Dict[str, str]) -> MetricsEmitter:
        return _TaggedEmitter(self._base, {**self._tags, **tags})

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._base.counter(key, n, tags={**self._tags, **(tags or {})})

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._base.gauge(key, value, tags={**self._tags, **(tags or {})})

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._base.histogram(key, value, tags={**self._tags, **(tags or {})})


class NoOpMetricsEmitter:
    """No-op metrics emitter that discards all metrics."""

    def with_tags(self, tags: Dict[str, str]) -> MetricsEmitter:
        return self

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass
