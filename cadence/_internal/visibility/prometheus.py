"""Prometheus metrics integration for Cadence client."""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

from prometheus_client import (  # type: ignore[import-not-found]
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
    push_to_gateway,
    start_http_server,
)


logger = logging.getLogger(__name__)


@dataclass
class PrometheusConfig:
    """Configuration for Prometheus metrics."""

    # HTTP server configuration
    enable_http_server: bool = False
    http_port: int = 8000
    http_addr: str = "0.0.0.0"

    # Push gateway configuration
    enable_push_gateway: bool = False
    push_gateway_url: str = "localhost:9091"
    push_job_name: str = "cadence_client"

    # Metric name prefix
    metric_prefix: str = "cadence_"

    # Default labels to apply to all metrics
    default_labels: Dict[str, str] = field(default_factory=dict)

    # Custom registry (if None, uses default global registry)
    registry: Optional[CollectorRegistry] = None


class PrometheusMetrics:
    """Prometheus metrics collector implementation."""

    def __init__(self, config: Optional[PrometheusConfig] = None):
        self.config = config or PrometheusConfig()
        self.registry = self.config.registry or REGISTRY

        # Track created metrics to avoid duplicates
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._summaries: Dict[str, Summary] = {}

        # HTTP server handle
        self._http_server: Optional[Any] = None

        if self.config.enable_http_server:
            self.start_http_server()

    def _get_metric_name(self, name: str) -> str:
        """Get the full metric name with prefix."""
        return f"{self.config.metric_prefix}{name}"

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
            self._histograms[metric_name] = Histogram(
                metric_name,
                f"Histogram metric for {name}",
                labelnames=label_names,
                registry=self.registry,
            )
            logger.debug(f"Created histogram metric: {metric_name}")

        return self._histograms[metric_name]

    def _get_or_create_summary(
        self, name: str, labels: Optional[Dict[str, str]]
    ) -> Summary:
        """Get or create a Summary metric."""
        metric_name = self._get_metric_name(name)

        if metric_name not in self._summaries:
            label_names = list(self._merge_labels(labels).keys()) if labels else []
            self._summaries[metric_name] = Summary(
                metric_name,
                f"Summary metric for {name}",
                labelnames=label_names,
                registry=self.registry,
            )
            logger.debug(f"Created summary metric: {metric_name}")

        return self._summaries[metric_name]

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

    def timer(
        self, key: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a timer metric - implemented as histogram."""
        try:
            histogram = self._get_or_create_histogram(key, tags)
            merged_tags = self._merge_labels(tags)

            if merged_tags:
                histogram.labels(**merged_tags).observe(duration)
            else:
                histogram.observe(duration)

        except Exception as e:
            logger.error(f"Failed to send timer {key}: {e}")

    def histogram(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Send a histogram metric."""
        try:
            histogram = self._get_or_create_histogram(key, tags)
            merged_tags = self._merge_labels(tags)

            if merged_tags:
                histogram.labels(**merged_tags).observe(value)
            else:
                histogram.observe(value)

        except Exception as e:
            logger.error(f"Failed to send histogram {key}: {e}")

    def start_http_server(self) -> None:
        """Start HTTP server to expose metrics."""
        if self._http_server is not None:
            logger.warning("HTTP server already started")
            return

        try:
            server_result = start_http_server(
                self.config.http_port,
                addr=self.config.http_addr,
                registry=self.registry,
            )
            self._http_server = server_result
            logger.info(
                f"Prometheus metrics HTTP server started on "
                f"{self.config.http_addr}:{self.config.http_port}"
            )
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")
            raise

    def push_to_gateway(self) -> None:
        """Push metrics to Prometheus Push Gateway."""
        if not self.config.enable_push_gateway:
            logger.warning("Push gateway not enabled")
            return

        try:
            push_to_gateway(
                self.config.push_gateway_url,
                job=self.config.push_job_name,
                registry=self.registry,
            )
            logger.debug(f"Pushed metrics to gateway: {self.config.push_gateway_url}")
        except Exception as e:
            logger.error(f"Failed to push to gateway: {e}")
            raise

    def get_metrics_text(self) -> str:
        """Get metrics in Prometheus text format."""
        try:
            metrics_bytes = generate_latest(self.registry)
            return metrics_bytes.decode("utf-8")  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Failed to generate metrics text: {e}")
            return ""

    def shutdown(self) -> None:
        """Shutdown the metrics collector."""
        if self._http_server:
            try:
                self._http_server.shutdown()
                self._http_server = None
                logger.info("Prometheus HTTP server shutdown")
            except Exception as e:
                logger.error(f"Failed to shutdown HTTP server: {e}")


# Default Cadence metrics names
class CadenceMetrics:
    """Standard Cadence client metrics."""

    # Workflow metrics
    WORKFLOW_STARTED_TOTAL = "workflow_started_total"
    WORKFLOW_COMPLETED_TOTAL = "workflow_completed_total"
    WORKFLOW_FAILED_TOTAL = "workflow_failed_total"
    WORKFLOW_DURATION_SECONDS = "workflow_duration_seconds"

    # Activity metrics
    ACTIVITY_STARTED_TOTAL = "activity_started_total"
    ACTIVITY_COMPLETED_TOTAL = "activity_completed_total"
    ACTIVITY_FAILED_TOTAL = "activity_failed_total"
    ACTIVITY_DURATION_SECONDS = "activity_duration_seconds"

    # Worker metrics
    WORKER_TASK_POLLS_TOTAL = "worker_task_polls_total"
    WORKER_TASK_POLL_ERRORS_TOTAL = "worker_task_poll_errors_total"
    WORKER_ACTIVE_TASKS = "worker_active_tasks"

    # Client metrics
    CLIENT_REQUESTS_TOTAL = "client_requests_total"
    CLIENT_REQUEST_DURATION_SECONDS = "client_request_duration_seconds"
    CLIENT_REQUEST_ERRORS_TOTAL = "client_request_errors_total"
