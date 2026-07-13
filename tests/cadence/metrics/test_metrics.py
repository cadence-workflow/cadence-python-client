"""Tests for metrics collection functionality."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from google.protobuf.timestamp_pb2 import Timestamp

from cadence.metrics import (
    duration_between,
    duration_from_nanoseconds,
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
        emitter.histogram("test_histogram", timedelta(milliseconds=500))

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
        mock_emitter.histogram(
            "test_histogram", timedelta(seconds=2, milliseconds=500), {"env": "prod"}
        )
        mock_emitter.histogram.assert_called_once_with(
            "test_histogram", timedelta(seconds=2, milliseconds=500), {"env": "prod"}
        )


class TestMetricType:
    """Test cases for MetricType enum."""

    def test_metric_type_values(self):
        """Test that MetricType enum has correct values."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"


class TestDurationMetrics:
    def test_duration_between_set_timestamps(self):
        assert duration_between(
            _timestamp(seconds=10, nanos=100_000_000),
            _timestamp(seconds=12, nanos=350_000_000),
        ) == timedelta(seconds=2, milliseconds=250)

    def test_duration_between_requires_both_timestamps(self):
        assert duration_between(_timestamp(), _timestamp(seconds=1)) is None
        assert duration_between(_timestamp(seconds=1), _timestamp()) is None

    def test_duration_between_preserves_clock_skew(self):
        assert duration_between(
            _timestamp(seconds=2),
            _timestamp(seconds=1),
        ) == -timedelta(seconds=1)

    def test_duration_between_timestamp_and_datetime(self):
        assert duration_between(
            _timestamp(seconds=10),
            datetime.fromtimestamp(12, tz=timezone.utc),
        ) == timedelta(seconds=2)

    def test_duration_from_nanoseconds_rounds_down_to_microseconds(self):
        assert duration_from_nanoseconds(2_250_999) == timedelta(microseconds=2_250)
