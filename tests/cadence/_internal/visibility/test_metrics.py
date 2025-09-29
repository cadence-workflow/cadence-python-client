"""Tests for metrics collection functionality."""

from unittest.mock import Mock


from cadence._internal.visibility.metrics import (
    MetricsHandler,
    NoOpMetricsHandler,
    get_default_handler,
    set_default_handler,
)


class TestMetricsHandler:
    """Test cases for MetricsHandler protocol."""

    def test_noop_handler(self):
        """Test no-op handler doesn't raise exceptions."""
        handler = NoOpMetricsHandler()

        # Should not raise any exceptions
        handler.counter("test_counter", 1)
        handler.gauge("test_gauge", 42.0)
        handler.histogram("test_histogram", 0.5)
        handler.timer("test_timing", 1.5)

    def test_mock_handler(self):
        """Test mock handler implementation."""
        mock_handler = Mock(spec=MetricsHandler)

        # Test counter
        mock_handler.counter("test_counter", 2, {"label": "value"})
        mock_handler.counter.assert_called_once_with(
            "test_counter", 2, {"label": "value"}
        )

        # Test gauge
        mock_handler.gauge("test_gauge", 100.0, {"env": "test"})
        mock_handler.gauge.assert_called_once_with(
            "test_gauge", 100.0, {"env": "test"}
        )

        # Test timer
        mock_handler.timer("test_timing", 0.75, {"tag": "value"})
        mock_handler.timer.assert_called_once_with(
            "test_timing", 0.75, {"tag": "value"}
        )

        # Test histogram
        mock_handler.histogram("test_histogram", 2.5, {"env": "prod"})
        mock_handler.histogram.assert_called_once_with(
            "test_histogram", 2.5, {"env": "prod"}
        )


class TestDefaultHandler:
    """Test cases for default handler management."""

    def test_get_default_handler(self):
        """Test getting the default handler."""
        handler = get_default_handler()
        assert isinstance(handler, NoOpMetricsHandler)

        # Should return the same instance
        handler2 = get_default_handler()
        assert handler is handler2

    def test_set_default_handler(self):
        """Test setting a custom default handler."""
        original_handler = get_default_handler()
        custom_handler = NoOpMetricsHandler()

        set_default_handler(custom_handler)

        # Should return the custom handler
        current_handler = get_default_handler()
        assert current_handler is custom_handler
        assert current_handler is not original_handler

        # Restore original for other tests
        set_default_handler(original_handler)
