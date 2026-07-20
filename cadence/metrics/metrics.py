"""Core metrics collection interface and registry for Cadence client."""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Optional, Protocol

from google.protobuf.timestamp import to_datetime
from google.protobuf.timestamp_pb2 import Timestamp

logger = logging.getLogger(__name__)


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
        self, key: str, value: timedelta, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a duration histogram metric."""
        ...


def duration_between(
    start: Timestamp | datetime, end: Timestamp | datetime
) -> Optional[timedelta]:
    """Return the duration between two set protobuf timestamps or datetimes."""
    start_time = _to_datetime(start)
    end_time = _to_datetime(end)
    if start_time is None or end_time is None:
        return None
    return end_time - start_time


def _to_datetime(value: Timestamp | datetime) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    return _timestamp_to_datetime(value)


def _timestamp_to_datetime(timestamp: Timestamp) -> Optional[datetime]:
    """Convert a set protobuf timestamp to a timezone-aware Python datetime."""
    if not _timestamp_is_set(timestamp):
        return None
    result: datetime = to_datetime(timestamp, timezone.utc)
    return result


def duration_from_nanoseconds(nanoseconds: int) -> timedelta:
    """Convert a monotonic-clock nanosecond delta to Python's duration type."""
    return timedelta(microseconds=nanoseconds // 1_000)


def _timestamp_is_set(timestamp: Timestamp) -> bool:
    return bool(timestamp.seconds or timestamp.nanos)


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
        self, key: str, value: timedelta, tags: Optional[Dict[str, str]] = None
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
        self, key: str, value: timedelta, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass
