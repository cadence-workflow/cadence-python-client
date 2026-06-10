"""Tests for metrics_emitter propagation through Worker → sub-workers → executors."""

from unittest.mock import AsyncMock, Mock, PropertyMock

from cadence.activity import ActivityDefinition
from cadence.client import Client
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.worker._base_task_handler import BaseTaskHandler
from cadence.worker._activity import ActivityWorker
from cadence.worker._registry import Registry
from cadence.worker._types import WorkerOptions
from cadence.worker._worker import _validate_and_copy_defaults


def _mock_client(metrics_emitter=None):
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="test-domain")
    type(client).identity = PropertyMock(return_value="test-identity")
    client.metrics_emitter = metrics_emitter or NoOpMetricsEmitter()
    worker_stub = Mock()
    worker_stub.PollForDecisionTask = AsyncMock(return_value=Mock(task_token=b""))
    worker_stub.PollForActivityTask = AsyncMock(return_value=Mock(task_token=b""))
    client.worker_stub = worker_stub
    return client


class ConcreteHandler(BaseTaskHandler[str]):
    async def _handle_task_implementation(self, task: str) -> None:
        pass

    async def handle_task_failure(self, task: str, error: Exception) -> None:
        pass


class TestMetricsEmitterPropagation:
    def test_validate_defaults_uses_client_emitter_when_not_set(self):
        custom_emitter = Mock(spec=MetricsEmitter)
        client = _mock_client(metrics_emitter=custom_emitter)
        options: WorkerOptions = {"identity": "id"}
        _validate_and_copy_defaults(client, "tl", options)
        assert options["metrics_emitter"] is custom_emitter

    def test_validate_defaults_preserves_explicit_emitter(self):
        client_emitter = Mock(spec=MetricsEmitter)
        explicit_emitter = Mock(spec=MetricsEmitter)
        client = _mock_client(metrics_emitter=client_emitter)
        options: WorkerOptions = {"identity": "id", "metrics_emitter": explicit_emitter}
        _validate_and_copy_defaults(client, "tl", options)
        assert options["metrics_emitter"] is explicit_emitter

    def test_base_task_handler_stores_metrics_emitter(self):
        custom_emitter = Mock(spec=MetricsEmitter)
        handler = ConcreteHandler(Mock(), "tl", "id", metrics_emitter=custom_emitter)
        assert handler._metrics_emitter is custom_emitter

    def test_base_task_handler_defaults_to_noop_emitter(self):
        handler = ConcreteHandler(Mock(), "tl", "id")
        assert isinstance(handler._metrics_emitter, NoOpMetricsEmitter)

    def test_activity_executor_stores_metrics_emitter(self):
        from cadence._internal.activity._activity_executor import ActivityExecutor

        custom_emitter = Mock(spec=MetricsEmitter)
        client = _mock_client()
        mock_registry: Mock = Mock(return_value=Mock(spec=ActivityDefinition))
        executor = ActivityExecutor(
            client, "tl", "id", 1, mock_registry, custom_emitter
        )
        assert executor._metrics_emitter is custom_emitter

    def test_activity_executor_defaults_to_noop_emitter(self):
        from cadence._internal.activity._activity_executor import ActivityExecutor

        client = _mock_client()
        mock_registry: Mock = Mock(return_value=Mock(spec=ActivityDefinition))
        executor = ActivityExecutor(client, "tl", "id", 1, mock_registry)
        assert isinstance(executor._metrics_emitter, NoOpMetricsEmitter)

    def test_activity_worker_passes_emitter_to_executor(self):
        custom_emitter = Mock(spec=MetricsEmitter)
        client = _mock_client()
        registry = Registry()
        options: WorkerOptions = {
            "identity": "id",
            "metrics_emitter": custom_emitter,
            "max_concurrent_activity_execution_size": 10,
            "activity_task_pollers": 1,
        }
        worker = ActivityWorker(client, "tl", registry, options)
        assert worker._executor._metrics_emitter is custom_emitter

    def test_decision_task_handler_stores_emitter_from_options(self):
        from cadence.worker._decision_task_handler import DecisionTaskHandler

        custom_emitter = Mock(spec=MetricsEmitter)
        client = _mock_client()
        registry = Registry()
        handler = DecisionTaskHandler(
            client, "tl", registry, identity="id", metrics_emitter=custom_emitter
        )
        assert handler._metrics_emitter is custom_emitter
