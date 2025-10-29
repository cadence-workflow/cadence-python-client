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


class NoOpMetricsEmitter:
    """No-op metrics emitter that discards all metrics."""

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
