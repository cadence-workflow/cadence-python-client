import pytest
from unittest.mock import Mock

from cadence.worker._base_task_handler import BaseTaskHandler


class ConcreteTaskHandler(BaseTaskHandler[str]):
    """Concrete implementation of BaseTaskHandler for testing."""

    def __init__(self, client, task_list: str, identity: str, **options):
        super().__init__(client, task_list, identity, **options)
        self._handle_task_implementation_called = False
        self._handle_task_failure_called = False
        self._last_task: str = ""
        self._last_error: Exception | None = None

    async def _handle_task_implementation(self, task: str) -> None:
        """Test implementation of task handling."""
        self._handle_task_implementation_called = True
        self._last_task = task
        if task == "raise_error":
            raise ValueError("Test error")

    async def handle_task_failure(self, task: str, error: Exception) -> None:
        """Test implementation of task failure handling."""
        self._handle_task_failure_called = True
        self._last_task = task
        self._last_error = error


class TestBaseTaskHandler:
    """Test cases for BaseTaskHandler."""

    def test_initialization(self):
        """Test BaseTaskHandler initialization."""
        client = Mock()
        handler = ConcreteTaskHandler(
            client=client,
            task_list="test_task_list",
            identity="test_identity",
            option1="value1",
            option2="value2",
        )

        assert handler._client == client
        assert handler.task_list == "test_task_list"
        assert handler._identity == "test_identity"
        assert handler._options == {"option1": "value1", "option2": "value2"}

    @pytest.mark.asyncio
    async def test_handle_task_success(self):
        """Test successful task handling."""
        client = Mock()
        handler = ConcreteTaskHandler(client, "test_task_list", "test_identity")

        await handler.handle_task("test_task")

        # Verify implementation was called
        assert handler._handle_task_implementation_called
        assert not handler._handle_task_failure_called
        assert handler._last_task == "test_task"
        assert handler._last_error is None

    @pytest.mark.asyncio
    async def test_handle_task_failure(self):
        """Test task handling with error."""
        client = Mock()
        handler = ConcreteTaskHandler(client, "test_task_list", "test_identity")

        await handler.handle_task("raise_error")

        # Verify error handling was called
        assert handler._handle_task_implementation_called
        assert handler._handle_task_failure_called
        assert handler._last_task == "raise_error"
        assert isinstance(handler._last_error, ValueError)
        assert str(handler._last_error) == "Test error"

    @pytest.mark.asyncio
    async def test_abstract_methods_not_implemented(self):
        """Test that abstract methods raise NotImplementedError when not implemented."""
        client = Mock()

        class IncompleteHandler(BaseTaskHandler[str]):
            async def _handle_task_implementation(self, task: str) -> None:
                raise NotImplementedError()

            async def handle_task_failure(self, task: str, error: Exception) -> None:
                raise NotImplementedError()

        handler = IncompleteHandler(client, "test_task_list", "test_identity")

        with pytest.raises(NotImplementedError):
            await handler._handle_task_implementation("test")

        with pytest.raises(NotImplementedError):
            await handler.handle_task_failure("test", Exception("test"))

    @pytest.mark.asyncio
    async def test_generic_type_parameter(self):
        """Test that the generic type parameter works correctly."""
        client = Mock()

        class IntHandler(BaseTaskHandler[int]):
            async def _handle_task_implementation(self, task: int) -> None:
                pass

            async def handle_task_failure(self, task: int, error: Exception) -> None:
                pass

        handler = IntHandler(client, "test_task_list", "test_identity")

        # Should accept int tasks
        await handler.handle_task(42)

        # Type checker should catch type mismatches (this is more of a static analysis test)
        # In runtime, Python won't enforce the type, but the type hints are there for static analysis
