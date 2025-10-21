"""Tests for metrics collection functionality."""

from unittest.mock import Mock


from cadence.metrics import (
    MetricsEmitter,
    MetricType,
    NoOpMetricsEmitter,
)


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
