"""Tests for metrics collection functionality."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from google.protobuf.timestamp_pb2 import Timestamp

from cadence.metrics import (
    duration_between_ns,
    MetricsEmitter,
    MetricsStopwatch,
    MetricType,
    NoOpMetricsEmitter,
    record_duration,
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
        assert duration_between_ns(
            _timestamp(seconds=10, nanos=100_000_000),
            _timestamp(seconds=12, nanos=350_000_000),
        ) == timedelta(seconds=2, microseconds=250_000)

    def test_duration_between_ns_requires_both_timestamps(self):
        assert duration_between_ns(_timestamp(), _timestamp(seconds=1)) is None
        assert duration_between_ns(_timestamp(seconds=1), _timestamp()) is None

    def test_duration_between_ns_clamps_clock_skew(self):
        assert duration_between_ns(
            _timestamp(seconds=2),
            _timestamp(seconds=1),
        ) == timedelta(0)

    def test_record_duration_converts_to_nanoseconds(self):
        emitter = Mock(spec=MetricsEmitter)

        record_duration(
            emitter,
            "latency_ns",
            timedelta(seconds=2, microseconds=345),
            {"operation": "test"},
        )

        emitter.histogram.assert_called_once_with(
            "latency_ns",
            2_000_345_000,
            {"operation": "test"},
        )

    def test_record_duration_rejects_negative_values(self):
        emitter = Mock(spec=MetricsEmitter)

        with pytest.raises(ValueError, match="non-negative"):
            record_duration(emitter, "latency_ns", timedelta(microseconds=-1))

        emitter.histogram.assert_not_called()

    def test_stopwatch_records_once_using_monotonic_nanoseconds(self):
        emitter = Mock(spec=MetricsEmitter)
        clock = Mock(side_effect=[10, 42])
        stopwatch = MetricsStopwatch(emitter, "latency_ns", clock_ns=clock)

        assert stopwatch.stop() == 32
        assert stopwatch.stop() == 32

        emitter.histogram.assert_called_once_with("latency_ns", 32)

    def test_stopwatch_context_manager_records_with_tags(self):
        emitter = Mock(spec=MetricsEmitter)
        clock = Mock(side_effect=[100, 150])

        with MetricsStopwatch(
            emitter,
            "latency_ns",
            {"operation": "test"},
            clock_ns=clock,
        ):
            pass

        emitter.histogram.assert_called_once_with(
            "latency_ns",
            50,
            {"operation": "test"},
        )
