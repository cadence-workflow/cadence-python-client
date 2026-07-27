"""Prometheus metrics integration for Cadence client."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, Optional, Sequence

from prometheus_client import (  # type: ignore[import-not-found]
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .histogram_buckets import DurationBucketResolver, default_buckets_for_metric
from .metrics import MetricsEmitter, _TaggedEmitter


logger = logging.getLogger(__name__)


@dataclass
class PrometheusConfig:
    """Configuration for Prometheus metrics."""

    # Default labels to apply to all metrics
    default_labels: Dict[str, str] = field(default_factory=dict)

    # Custom registry (if None, uses default global registry)
    registry: Optional[CollectorRegistry] = None

    # Per-metric bucket overrides, keyed by exact metric name (e.g.
    # "cadence-activity-execution-latency_ns"). Takes precedence over
    # duration_bucket_resolver and the built-in Go/Java-aligned defaults.
    histogram_buckets: Dict[str, Sequence[float]] = field(default_factory=dict)

    # Overrides how default buckets are chosen for any `_ns`-suffixed metric not
    # covered by histogram_buckets. Defaults to histogram_buckets.default_buckets_for_metric.
    duration_bucket_resolver: Optional[DurationBucketResolver] = None


class PrometheusMetrics(MetricsEmitter):
    """Prometheus metrics collector implementation."""

    def __init__(self, config: Optional[PrometheusConfig] = None):
        self.config = config or PrometheusConfig()
        self.registry = self.config.registry or REGISTRY

        # Track created metrics to avoid duplicates
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}

    def _get_metric_name(self, name: str) -> str:
        """Get the metric name."""
        return name

    def _merge_labels(self, labels: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Merge provided labels with default labels."""
        merged = self.config.default_labels.copy()
        if labels:
            merged.update(labels)
        return merged

    def _get_or_create_counter(
        self, name: str, labels: Optional[Dict[str, str]]
    ) -> Counter:
        """Get or create a Counter metric."""
        metric_name = self._get_metric_name(name)

        if metric_name not in self._counters:
            label_names = list(self._merge_labels(labels).keys()) if labels else []
            self._counters[metric_name] = Counter(
                metric_name,
                f"Counter metric for {name}",
                labelnames=label_names,
                registry=self.registry,
            )
            logger.debug(f"Created counter metric: {metric_name}")

        return self._counters[metric_name]

    def _get_or_create_gauge(
        self, name: str, labels: Optional[Dict[str, str]]
    ) -> Gauge:
        """Get or create a Gauge metric."""
        metric_name = self._get_metric_name(name)

        if metric_name not in self._gauges:
            label_names = list(self._merge_labels(labels).keys()) if labels else []
            self._gauges[metric_name] = Gauge(
                metric_name,
                f"Gauge metric for {name}",
                labelnames=label_names,
                registry=self.registry,
            )
            logger.debug(f"Created gauge metric: {metric_name}")

        return self._gauges[metric_name]

    def _get_or_create_histogram(
        self, name: str, labels: Optional[Dict[str, str]]
    ) -> Histogram:
        """Get or create a Histogram metric."""
        metric_name = self._get_metric_name(name)

        if metric_name not in self._histograms:
            label_names = list(self._merge_labels(labels).keys()) if labels else []
            buckets = self._resolve_buckets(metric_name)
            if buckets is not None:
                histogram = Histogram(
                    metric_name,
                    f"Histogram metric for {name}",
                    labelnames=label_names,
                    registry=self.registry,
                    buckets=tuple(buckets),
                )
            else:
                histogram = Histogram(
                    metric_name,
                    f"Histogram metric for {name}",
                    labelnames=label_names,
                    registry=self.registry,
                )
            self._histograms[metric_name] = histogram
            logger.debug(f"Created histogram metric: {metric_name}")

        return self._histograms[metric_name]

    def _resolve_buckets(self, metric_name: str) -> Optional[Sequence[float]]:
        """Resolve bucket boundaries for a histogram, or None for Prometheus's defaults.

        Precedence: per-metric override, then custom resolver, then Go/Java-aligned
        defaults for `_ns` metrics, then Prometheus's own defaults otherwise.
        """
        override = self.config.histogram_buckets.get(metric_name)
        if override is not None:
            return override
        if not metric_name.endswith("_ns"):
            return None
        resolver = self.config.duration_bucket_resolver or default_buckets_for_metric
        return resolver(metric_name)

    def with_tags(self, tags: Dict[str, str]) -> "MetricsEmitter":
        return _TaggedEmitter(self, tags)

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a counter metric."""
        try:
            counter = self._get_or_create_counter(key, tags)
            merged_tags = self._merge_labels(tags)

            if merged_tags:
                counter.labels(**merged_tags).inc(n)
            else:
                counter.inc(n)

        except Exception as e:
            logger.error(f"Failed to send counter {key}: {e}")

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a gauge metric."""
        try:
            gauge = self._get_or_create_gauge(key, tags)
            merged_tags = self._merge_labels(tags)

            if merged_tags:
                gauge.labels(**merged_tags).set(value)
            else:
                gauge.set(value)

        except Exception as e:
            logger.error(f"Failed to send gauge {key}: {e}")

    def histogram(
        self, key: str, value: timedelta, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a duration histogram metric."""
        try:
            histogram = self._get_or_create_histogram(key, tags)
            merged_tags = self._merge_labels(tags)
            value_ns = _timedelta_to_nanoseconds(value)

            if merged_tags:
                histogram.labels(**merged_tags).observe(value_ns)
            else:
                histogram.observe(value_ns)

        except Exception as e:
            logger.error(f"Failed to send histogram {key}: {e}")

    def get_metrics_text(self) -> str:
        """Get metrics in Prometheus text format."""
        try:
            metrics_bytes = generate_latest(self.registry)
            return metrics_bytes.decode("utf-8")  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Failed to generate metrics text: {e}")
            return ""


def _timedelta_to_nanoseconds(value: timedelta) -> int:
    """Convert a Python duration to the nanoseconds used by Cadence metrics."""
    return (
        value.days * 86_400_000_000_000
        + value.seconds * 1_000_000_000
        + value.microseconds * 1_000
    )
