import logging
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BaseTaskHandler(ABC, Generic[T]):
    """
    Base task handler that provides common functionality for processing tasks.

    This abstract class defines the interface and common behavior for task handlers
    that process different types of tasks (workflow decisions, activities, etc.).
    """

    def __init__(self, client, task_list: str, identity: str, **options):
        self._client = client
        self.task_list = task_list
        self._identity = identity
        self._metrics_emitter: MetricsEmitter = options.get(
            "metrics_emitter", NoOpMetricsEmitter()
        )
        self._options = options

    async def handle_task(self, task: T) -> None:
        """
        Handle a single task.

        This method provides the base implementation for task handling that includes:
        - Error handling
        - Cleanup

        Args:
            task: The task to handle
        """
        try:
            # Handle the task implementation
            await self._handle_task_implementation(task)

        except Exception as e:
            logger.exception(f"Error handling task: {e}")
            await self.handle_task_failure(task, e)

    @abstractmethod
    async def _handle_task_implementation(self, task: T) -> None:
        """
        Handle the actual task implementation.

        Args:
            task: The task to handle
        """
        pass

    @abstractmethod
    async def handle_task_failure(self, task: T, error: Exception) -> None:
        """
        Handle task processing failure.

        Args:
            task: The task that failed
            error: The exception that occurred
        """
        pass
