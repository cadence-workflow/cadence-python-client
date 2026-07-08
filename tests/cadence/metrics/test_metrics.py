"""Tests for metrics collection functionality."""

from unittest.mock import Mock

from google.protobuf.timestamp_pb2 import Timestamp

from cadence.metrics import (
    duration_between_ns,
    MetricsEmitter,
    MetricType,
    NoOpMetricsEmitter,
)


def _timestamp(seconds: int = 0, nanos: int = 0) -> Timestamp:
    return Timestamp(seconds=seconds, nanos=nanos)


class TestMetricsEmitter:
    """Test cases for MetricsEmitter protocol."""

    def test_noop_emitter(self):
        """Test no-op emitter doesn't raise exceptions."""
        emitter = NoOpMetricsEmitter()

        # Should not raise any exceptions
        emitter.counter("test_counter", 1)
        emitter.gauge("test_gauge", 42.0)
        emitter.histogram("test_histogram", 0.5)

    def test_mock_emitter(self):
        """Test mock emitter implementation."""
        mock_emitter = Mock(spec=MetricsEmitter)

        # Test counter
        mock_emitter.counter("test_counter", 2, {"label": "value"})
        mock_emitter.counter.assert_called_once_with(
            "test_counter", 2, {"label": "value"}
        )

        # Test gauge
        mock_emitter.gauge("test_gauge", 100.0, {"env": "test"})
        mock_emitter.gauge.assert_called_once_with("test_gauge", 100.0, {"env": "test"})

        # Test histogram
        mock_emitter.histogram("test_histogram", 2.5, {"env": "prod"})
        mock_emitter.histogram.assert_called_once_with(
            "test_histogram", 2.5, {"env": "prod"}
        )


class TestMetricType:
    """Test cases for MetricType enum."""

    def test_metric_type_values(self):
        """Test that MetricType enum has correct values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"


class TestDurationMetrics:
    def test_duration_between_ns_set_timestamps(self):
        assert (
            duration_between_ns(
                _timestamp(seconds=10, nanos=100_000_000),
                _timestamp(seconds=12, nanos=350_000_000),
            )
            == 2_250_000_000
        )

    def test_duration_between_ns_requires_both_timestamps(self):
        assert duration_between_ns(_timestamp(), _timestamp(seconds=1)) is None
        assert duration_between_ns(_timestamp(seconds=1), _timestamp()) is None

    def test_duration_between_ns_clamps_clock_skew(self):
        assert (
            duration_between_ns(
                _timestamp(seconds=2),
                _timestamp(seconds=1),
            )
            == 0
        )
