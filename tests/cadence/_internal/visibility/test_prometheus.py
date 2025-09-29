"""Tests for Prometheus metrics integration."""

from unittest.mock import Mock, patch


from cadence._internal.visibility.prometheus import (
    CadenceMetrics,
    PrometheusConfig,
    PrometheusMetrics,
)


class TestPrometheusConfig:
    """Test cases for PrometheusConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PrometheusConfig()

        assert config.enable_http_server is False
        assert config.http_port == 8000
        assert config.http_addr == "0.0.0.0"
        assert config.enable_push_gateway is False
        assert config.push_gateway_url == "localhost:9091"
        assert config.push_job_name == "cadence_client"
        assert config.metric_prefix == "cadence_"
        assert config.default_labels == {}
        assert config.registry is None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = PrometheusConfig(
            enable_http_server=True,
            http_port=9000,
            metric_prefix="my_cadence_",
            default_labels={"env": "test"},
        )

        assert config.enable_http_server is True
        assert config.http_port == 9000
        assert config.metric_prefix == "my_cadence_"
        assert config.default_labels == {"env": "test"}


class TestPrometheusMetrics:
    """Test cases for PrometheusMetrics."""

    @patch("cadence._internal.visibility.prometheus.start_http_server")
    def test_initialization_with_http_server(self, mock_start_server):
        """Test PrometheusMetrics initialization with HTTP server."""
        config = PrometheusConfig(enable_http_server=True, http_port=8001)

        metrics = PrometheusMetrics(config)

        assert metrics.config == config
        mock_start_server.assert_called_once_with(
            8001, addr="0.0.0.0", registry=metrics.registry
        )

    def test_initialization_without_http_server(self):
        """Test PrometheusMetrics initialization without HTTP server."""
        config = PrometheusConfig(enable_http_server=False)

        metrics = PrometheusMetrics(config)

        assert metrics.config == config
        assert metrics._http_server is None

    def test_metric_name_with_prefix(self):
        """Test metric name generation with prefix."""
        config = PrometheusConfig(metric_prefix="test_")
        metrics = PrometheusMetrics(config)

        name = metrics._get_metric_name("counter")
        assert name == "test_counter"

    def test_merge_labels(self):
        """Test label merging with default labels."""
        config = PrometheusConfig(default_labels={"env": "test", "service": "cadence"})
        metrics = PrometheusMetrics(config)

        # Test with no additional labels
        merged = metrics._merge_labels(None)
        assert merged == {"env": "test", "service": "cadence"}

        # Test with additional labels
        merged = metrics._merge_labels({"operation": "poll"})
        assert merged == {"env": "test", "service": "cadence", "operation": "poll"}

        # Test label override
        merged = metrics._merge_labels({"env": "prod", "operation": "poll"})
        assert merged == {"env": "prod", "service": "cadence", "operation": "poll"}

    @patch("cadence._internal.visibility.prometheus.Counter")
    def test_counter(self, mock_counter_class):
        """Test counter metric."""
        mock_counter = Mock()
        mock_labeled_counter = Mock()
        mock_counter.labels.return_value = mock_labeled_counter
        mock_counter_class.return_value = mock_counter

        config = PrometheusConfig()
        metrics = PrometheusMetrics(config)

        # Test without labels
        metrics.counter("test_counter", 2)
        mock_counter.inc.assert_called_once_with(2)

        # Reset mock
        mock_counter.reset_mock()
        mock_labeled_counter.reset_mock()

        # Test with labels
        metrics.counter("test_counter", 1, {"env": "test"})
        mock_counter.labels.assert_called_once_with(env="test")
        mock_labeled_counter.inc.assert_called_once_with(1)

    @patch("cadence._internal.visibility.prometheus.Gauge")
    def test_gauge(self, mock_gauge_class):
        """Test gauge metric."""
        mock_gauge = Mock()
        mock_labeled_gauge = Mock()
        mock_gauge.labels.return_value = mock_labeled_gauge
        mock_gauge_class.return_value = mock_gauge

        config = PrometheusConfig()
        metrics = PrometheusMetrics(config)

        # Test without labels
        metrics.gauge("test_gauge", 42.0)
        mock_gauge.set.assert_called_once_with(42.0)

        # Reset mock
        mock_gauge.reset_mock()
        mock_labeled_gauge.reset_mock()

        # Test with labels
        metrics.gauge("test_gauge", 100.0, {"env": "test"})
        mock_gauge.labels.assert_called_once_with(env="test")
        mock_labeled_gauge.set.assert_called_once_with(100.0)

    @patch("cadence._internal.visibility.prometheus.Histogram")
    def test_timer(self, mock_histogram_class):
        """Test timer metric."""
        mock_histogram = Mock()
        mock_labeled_histogram = Mock()
        mock_histogram.labels.return_value = mock_labeled_histogram
        mock_histogram_class.return_value = mock_histogram

        config = PrometheusConfig()
        metrics = PrometheusMetrics(config)

        # Test without labels
        metrics.timer("test_timer", 0.5)
        mock_histogram.observe.assert_called_once_with(0.5)

        # Reset mock
        mock_histogram.reset_mock()
        mock_labeled_histogram.reset_mock()

        # Test with labels
        metrics.timer("test_timer", 1.0, {"env": "test"})
        mock_histogram.labels.assert_called_once_with(env="test")
        mock_labeled_histogram.observe.assert_called_once_with(1.0)

    @patch("cadence._internal.visibility.prometheus.Histogram")
    def test_histogram(self, mock_histogram_class):
        """Test histogram metric."""
        mock_histogram = Mock()
        mock_labeled_histogram = Mock()
        mock_histogram.labels.return_value = mock_labeled_histogram
        mock_histogram_class.return_value = mock_histogram

        config = PrometheusConfig()
        metrics = PrometheusMetrics(config)

        # Test without labels
        metrics.histogram("test_histogram", 2.5)
        mock_histogram.observe.assert_called_once_with(2.5)

        # Reset mock
        mock_histogram.reset_mock()
        mock_labeled_histogram.reset_mock()

        # Test with labels
        metrics.histogram("test_histogram", 3.0, {"env": "test"})
        mock_histogram.labels.assert_called_once_with(env="test")
        mock_labeled_histogram.observe.assert_called_once_with(3.0)

    @patch("cadence._internal.visibility.prometheus.push_to_gateway")
    def test_push_to_gateway(self, mock_push):
        """Test pushing metrics to gateway."""
        config = PrometheusConfig(
            enable_push_gateway=True,
            push_gateway_url="localhost:9091",
            push_job_name="test_job",
        )
        metrics = PrometheusMetrics(config)

        metrics.push_to_gateway()

        mock_push.assert_called_once_with(
            "localhost:9091", job="test_job", registry=metrics.registry
        )

    def test_push_to_gateway_disabled(self):
        """Test push to gateway when disabled."""
        config = PrometheusConfig(enable_push_gateway=False)
        metrics = PrometheusMetrics(config)

        # Should not raise exception
        metrics.push_to_gateway()

    @patch("cadence._internal.visibility.prometheus.generate_latest")
    def test_get_metrics_text(self, mock_generate):
        """Test getting metrics as text."""
        mock_generate.return_value = (
            b"# HELP test_counter Test counter\ntest_counter 1.0\n"
        )

        config = PrometheusConfig()
        metrics = PrometheusMetrics(config)

        text = metrics.get_metrics_text()

        assert text == "# HELP test_counter Test counter\ntest_counter 1.0\n"
        mock_generate.assert_called_once_with(metrics.registry)

    def test_shutdown(self):
        """Test metrics shutdown."""
        config = PrometheusConfig(enable_http_server=False)
        metrics = PrometheusMetrics(config)

        # Mock HTTP server
        mock_server = Mock()
        metrics._http_server = mock_server  # type: ignore

        metrics.shutdown()

        mock_server.shutdown.assert_called_once()
        assert metrics._http_server is None


class TestCadenceMetrics:
    """Test cases for CadenceMetrics constants."""

    def test_workflow_metrics(self):
        """Test workflow metric names."""
        assert CadenceMetrics.WORKFLOW_STARTED_TOTAL == "workflow_started_total"
        assert CadenceMetrics.WORKFLOW_COMPLETED_TOTAL == "workflow_completed_total"
        assert CadenceMetrics.WORKFLOW_FAILED_TOTAL == "workflow_failed_total"
        assert CadenceMetrics.WORKFLOW_DURATION_SECONDS == "workflow_duration_seconds"

    def test_activity_metrics(self):
        """Test activity metric names."""
        assert CadenceMetrics.ACTIVITY_STARTED_TOTAL == "activity_started_total"
        assert CadenceMetrics.ACTIVITY_COMPLETED_TOTAL == "activity_completed_total"
        assert CadenceMetrics.ACTIVITY_FAILED_TOTAL == "activity_failed_total"
        assert CadenceMetrics.ACTIVITY_DURATION_SECONDS == "activity_duration_seconds"

    def test_worker_metrics(self):
        """Test worker metric names."""
        assert CadenceMetrics.WORKER_TASK_POLLS_TOTAL == "worker_task_polls_total"
        assert (
            CadenceMetrics.WORKER_TASK_POLL_ERRORS_TOTAL
            == "worker_task_poll_errors_total"
        )
        assert CadenceMetrics.WORKER_ACTIVE_TASKS == "worker_active_tasks"

    def test_client_metrics(self):
        """Test client metric names."""
        assert CadenceMetrics.CLIENT_REQUESTS_TOTAL == "client_requests_total"
        assert (
            CadenceMetrics.CLIENT_REQUEST_DURATION_SECONDS
            == "client_request_duration_seconds"
        )
        assert (
            CadenceMetrics.CLIENT_REQUEST_ERRORS_TOTAL == "client_request_errors_total"
        )


