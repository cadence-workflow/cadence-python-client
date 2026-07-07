"""Core metrics collection interface and registry for Cadence client."""

import logging
from enum import Enum
from typing import Dict, Optional, Protocol

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
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a histogram metric."""
        ...


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
