import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, TypeVar, Generic

logger = logging.getLogger(__name__)

T = TypeVar('T')

class BaseTaskHandler(ABC, Generic[T]):
    """
    Base task handler that provides common functionality for processing tasks.
    
    This abstract class defines the interface and common behavior for task handlers
    that process different types of tasks (workflow decisions, activities, etc.).
    """
    
    def __init__(self, client, task_list: str, identity: str, **options):
        """
        Initialize the base task handler.
        
        Args:
            client: The Cadence client instance
            task_list: The task list name
            identity: Worker identity
            **options: Additional options for the handler
        """
        self._client = client
        self._task_list = task_list
        self._identity = identity
        self._options = options
    
    async def handle_task(self, task: T) -> None:
        """
        Handle a single task.
        
        This method provides the base implementation for task handling that includes:
        - Context propagation
        - Error handling
        - Cleanup
        
        Args:
            task: The task to handle
        """
        try:
            # Propagate context from task parameters
            await self._propagate_context(task)
            
            # Handle the task
            await self._handle_task_implementation(task)
                
        except Exception as e:
            logger.exception(f"Error handling task: {e}")
            await self.handle_task_failure(task, e)
        finally:
            # Clean up context
            await self._unset_current_context()
    
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
    
    async def _propagate_context(self, task: T) -> None:
        """
        Propagate context from task parameters.
        
        Args:
            task: The task containing context information
        """
        # Default implementation - subclasses should override if needed
        pass
    
    async def _unset_current_context(self) -> None:
        """
        Unset the current context after task completion.
        """
        # Default implementation - subclasses should override if needed
        pass
