"""Tests for Prometheus metrics integration."""

from unittest.mock import Mock, patch

from cadence.metrics import (
    PrometheusMetrics,
    PrometheusConfig,
)


class TestPrometheusConfig:
    """Test cases for PrometheusConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PrometheusConfig()
        assert config.default_labels == {}
        assert config.registry is None

    def test_custom_config(self):
        """Test custom configuration values."""
        from prometheus_client import CollectorRegistry
        
        registry = CollectorRegistry()
        config = PrometheusConfig(
            default_labels={"env": "test"},
            registry=registry
        )
        assert config.default_labels == {"env": "test"}
        assert config.registry is registry


class TestPrometheusMetrics:
    """Test cases for PrometheusMetrics."""

    def test_init_with_default_config(self):
        """Test initialization with default config."""
        metrics = PrometheusMetrics()
        assert metrics.registry is not None

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        from prometheus_client import CollectorRegistry
        
        registry = CollectorRegistry()
        config = PrometheusConfig(
            default_labels={"service": "test"},
            registry=registry
        )
        metrics = PrometheusMetrics(config)
        assert metrics.registry is registry

    @patch('cadence.metrics.prometheus.Counter')
    def test_counter_metric(self, mock_counter_class):
        """Test counter metric creation and usage."""
        mock_counter = Mock()
        mock_counter_class.return_value = mock_counter
        
        metrics = PrometheusMetrics()
        metrics.counter("test_counter", 5, {"label": "value"})
        
        # Verify counter was created
        mock_counter_class.assert_called_once()
        mock_counter.labels.assert_called_once_with(label="value")
        mock_counter.labels.return_value.inc.assert_called_once_with(5)

    @patch('cadence.metrics.prometheus.Gauge')
    def test_gauge_metric(self, mock_gauge_class):
        """Test gauge metric creation and usage."""
        mock_gauge = Mock()
        mock_gauge_class.return_value = mock_gauge
        
        metrics = PrometheusMetrics()
        metrics.gauge("test_gauge", 42.5, {"env": "prod"})
        
        # Verify gauge was created
        mock_gauge_class.assert_called_once()
        mock_gauge.labels.assert_called_once_with(env="prod")
        mock_gauge.labels.return_value.set.assert_called_once_with(42.5)

    @patch('cadence.metrics.prometheus.Histogram')
    def test_histogram_metric(self, mock_histogram_class):
        """Test histogram metric creation and usage."""
        mock_histogram = Mock()
        mock_histogram_class.return_value = mock_histogram
        
        metrics = PrometheusMetrics()
        metrics.histogram("test_histogram", 1.5, {"type": "latency"})
        
        # Verify histogram was created
        mock_histogram_class.assert_called_once()
        mock_histogram.labels.assert_called_once_with(type="latency")
        mock_histogram.labels.return_value.observe.assert_called_once_with(1.5)


    def test_metric_name_generation(self):
        """Test metric name generation."""
        metrics = PrometheusMetrics()
        
        metric_name = metrics._get_metric_name("test_metric")
        assert metric_name == "test_metric"

    def test_label_merging(self):
        """Test label merging with default labels."""
        config = PrometheusConfig(
            default_labels={"service": "cadence", "version": "1.0"}
        )
        metrics = PrometheusMetrics(config)
        
        # Test merging with provided labels
        merged = metrics._merge_labels({"operation": "start"})
        expected = {"service": "cadence", "version": "1.0", "operation": "start"}
        assert merged == expected
        
        # Test merging with None labels
        merged_none = metrics._merge_labels(None)
        assert merged_none == {"service": "cadence", "version": "1.0"}

    @patch('cadence.metrics.prometheus.generate_latest')
    def test_get_metrics_text(self, mock_generate_latest):
        """Test getting metrics in text format."""
        mock_generate_latest.return_value = b"# HELP test_metric Test metric\n# TYPE test_metric counter\ntest_metric 1.0\n"
        
        metrics = PrometheusMetrics()
        result = metrics.get_metrics_text()
        
        assert result == "# HELP test_metric Test metric\n# TYPE test_metric counter\ntest_metric 1.0\n"
        mock_generate_latest.assert_called_once_with(metrics.registry)

    def test_error_handling_in_counter(self):
        """Test error handling in counter method."""
        metrics = PrometheusMetrics()
        
        # This should not raise an exception
        with patch.object(metrics, '_get_or_create_counter', side_effect=Exception("Test error")):
            metrics.counter("test_counter", 1)
            # Should not raise, just log error

    def test_error_handling_in_gauge(self):
        """Test error handling in gauge method."""
        metrics = PrometheusMetrics()
        
        # This should not raise an exception
        with patch.object(metrics, '_get_or_create_gauge', side_effect=Exception("Test error")):
            metrics.gauge("test_gauge", 1.0)
            # Should not raise, just log error

