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
    TIMER = "timer"


class MetricsHandler(Protocol):
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

    def timer(
        self, key: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a timer metric."""
        ...

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a histogram metric."""
        ...


class NoOpMetricsHandler:
    """No-op metrics handler that discards all metrics."""

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass

    def timer(
        self, key: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        pass


# Global default handler
_default_handler: Optional[MetricsHandler] = None


def get_default_handler() -> MetricsHandler:
    """Get the default global metrics handler."""
    global _default_handler
    if _default_handler is None:
        _default_handler = NoOpMetricsHandler()
    return _default_handler


def set_default_handler(handler: MetricsHandler) -> None:
    """Set the default global metrics handler."""
    global _default_handler
    _default_handler = handler
