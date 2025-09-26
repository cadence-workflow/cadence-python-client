"""Core metrics collection interface and registry for Cadence client."""

import logging
from enum import Enum
from typing import Dict, Optional, Protocol, Set

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics that can be collected."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class MetricsCollector(Protocol):
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


class NoOpMetricsCollector:
    """No-op metrics collector that discards all metrics."""

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


class MetricsRegistry:
    """Registry for managing metrics collection in the Cadence client."""

    def __init__(self, collector: Optional[MetricsCollector] = None):
        self._collector = collector or NoOpMetricsCollector()
        self._registered_metrics: Set[str] = set()

    def set_collector(self, collector: MetricsCollector) -> None:
        """Set the metrics collector backend."""
        self._collector = collector
        logger.info(f"Metrics collector set to {type(collector).__name__}")

    def register_metric(self, name: str, metric_type: MetricType) -> None:
        """Register a metric with the registry."""
        if name in self._registered_metrics:
            logger.warning(f"Metric {name} already registered")
            return

        self._registered_metrics.add(name)
        logger.debug(f"Registered {metric_type.value} metric: {name}")

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a counter metric."""
        try:
            self._collector.counter(key, n, tags)
        except Exception as e:
            logger.error(f"Failed to send counter {key}: {e}")

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a gauge metric."""
        try:
            self._collector.gauge(key, value, tags)
        except Exception as e:
            logger.error(f"Failed to send gauge {key}: {e}")

    def timer(
        self, key: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a timer metric."""
        try:
            self._collector.timer(key, duration, tags)
        except Exception as e:
            logger.error(f"Failed to send timer {key}: {e}")

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a histogram metric."""
        try:
            self._collector.histogram(key, value, tags)
        except Exception as e:
            logger.error(f"Failed to send histogram {key}: {e}")


# Global default registry
_default_registry: Optional[MetricsRegistry] = None


def get_default_registry() -> MetricsRegistry:
    """Get the default global metrics registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = MetricsRegistry()
    return _default_registry


def set_default_registry(registry: MetricsRegistry) -> None:
    """Set the default global metrics registry."""
    global _default_registry
    _default_registry = registry
