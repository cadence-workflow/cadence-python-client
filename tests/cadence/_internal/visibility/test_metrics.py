"""Tests for metrics collection functionality."""

from unittest.mock import Mock


from cadence._internal.visibility.metrics import (
    MetricsRegistry,
    MetricType,
    NoOpMetricsCollector,
    get_default_registry,
    set_default_registry,
)


class TestMetricsRegistry:
    """Test cases for MetricsRegistry."""

    def test_registry_with_no_collector(self):
        """Test registry with default no-op collector."""
        registry = MetricsRegistry()

        # Should not raise any exceptions
        registry.counter("test_counter", 1)
        registry.gauge("test_gauge", 42.0)
        registry.histogram("test_histogram", 0.5)
        registry.timer("test_timing", 1.5)

    def test_registry_with_mock_collector(self):
        """Test registry with mock collector."""
        mock_collector = Mock()
        registry = MetricsRegistry(mock_collector)

        # Test counter
        registry.counter("test_counter", 2, {"label": "value"})
        mock_collector.counter.assert_called_once_with(
            "test_counter", 2, {"label": "value"}
        )

        # Test gauge
        registry.gauge("test_gauge", 100.0, {"env": "test"})
        mock_collector.gauge.assert_called_once_with(
            "test_gauge", 100.0, {"env": "test"}
        )

        # Test timer
        registry.timer("test_timing", 0.75)
        mock_collector.timer.assert_called_once_with(
            "test_timing", 0.75, None
        )

        # Test histogram
        registry.histogram("test_histogram", 2.5)
        mock_collector.histogram.assert_called_once_with(
            "test_histogram", 2.5, None
        )

    def test_set_collector(self):
        """Test setting a new collector."""
        registry = MetricsRegistry()
        mock_collector = Mock()

        registry.set_collector(mock_collector)
        registry.counter("test", 1)

        mock_collector.counter.assert_called_once_with("test", 1, None)

    def test_register_metric(self):
        """Test metric registration."""
        registry = MetricsRegistry()

        registry.register_metric("test_counter", MetricType.COUNTER)
        registry.register_metric("test_gauge", MetricType.GAUGE)

        # Registering the same metric twice should not raise an error
        registry.register_metric("test_counter", MetricType.COUNTER)

    def test_collector_exception_handling(self):
        """Test that collector exceptions are handled gracefully."""
        mock_collector = Mock()
        mock_collector.counter.side_effect = Exception("Test exception")

        registry = MetricsRegistry(mock_collector)

        # Should not raise exception, but log error
        registry.counter("test", 1)

        mock_collector.counter.assert_called_once()


class TestNoOpMetricsCollector:
    """Test cases for NoOpMetricsCollector."""

    def test_no_op_collector(self):
        """Test that no-op collector doesn't raise exceptions."""
        collector = NoOpMetricsCollector()

        # Should not raise any exceptions
        collector.counter("test", 1, {"label": "value"})
        collector.gauge("test", 42.0)
        collector.histogram("test", 0.5, {"env": "test"})
        collector.timer("test", 1.5)


class TestDefaultRegistry:
    """Test cases for default registry management."""

    def test_get_default_registry(self):
        """Test getting the default registry."""
        registry = get_default_registry()
        assert isinstance(registry, MetricsRegistry)

        # Should return the same instance
        registry2 = get_default_registry()
        assert registry is registry2

    def test_set_default_registry(self):
        """Test setting a custom default registry."""
        original_registry = get_default_registry()
        custom_registry = MetricsRegistry()

        set_default_registry(custom_registry)

        # Should return the custom registry
        current_registry = get_default_registry()
        assert current_registry is custom_registry
        assert current_registry is not original_registry

        # Restore original for other tests
        set_default_registry(original_registry)
