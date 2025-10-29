from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Callable, TypeVar, TypedDict, Type, cast, Any, Optional, Union
import inspect

from cadence.client import Client

T = TypeVar('T', bound=Callable[..., Any])


class WorkflowDefinitionOptions(TypedDict, total=False):
    """Options for defining a workflow."""
    name: str


class WorkflowDefinition:
    """
    Definition of a workflow class with metadata.

    Similar to ActivityDefinition but for workflow classes.
    Provides type safety and metadata for workflow classes.
    """

    def __init__(self, cls: Type, name: str, run_method_name: str):
        self._cls = cls
        self._name = name
        self._run_method_name = run_method_name

    @property
    def name(self) -> str:
        """Get the workflow name."""
        return self._name

    @property
    def cls(self) -> Type:
        """Get the workflow class."""
        return self._cls

    def get_run_method(self, instance: Any) -> Callable:
        """Get the workflow run method from an instance of the workflow class."""
        return cast(Callable, getattr(instance, self._run_method_name))

    @staticmethod
    def wrap(cls: Type, opts: WorkflowDefinitionOptions) -> 'WorkflowDefinition':
        """
        Wrap a class as a WorkflowDefinition.

        Args:
            cls: The workflow class to wrap
            opts: Options for the workflow definition

        Returns:
            A WorkflowDefinition instance

        Raises:
            ValueError: If no run method is found or multiple run methods exist
        """
        name = cls.__name__
        if "name" in opts and opts["name"]:
            name = opts["name"]

        # Validate that the class has exactly one run method and find it
        run_method_name = None
        for attr_name in dir(cls):
            if attr_name.startswith('_'):
                continue

            attr = getattr(cls, attr_name)
            if not callable(attr):
                continue

            # Check for workflow run method
            if hasattr(attr, '_workflow_run'):
                if run_method_name is not None:
                    raise ValueError(f"Multiple @workflow.run methods found in class {cls.__name__}")
                run_method_name = attr_name

        if run_method_name is None:
            raise ValueError(f"No @workflow.run method found in class {cls.__name__}")

        return WorkflowDefinition(cls, name, run_method_name) 


def run(func: Optional[T] = None) -> Union[T, Callable[[T], T]]:
    """
    Decorator to mark a method as the main workflow run method.

    Can be used with or without parentheses:
        @workflow.run
        async def my_workflow(self):
            ...

        @workflow.run()
        async def my_workflow(self):
            ...

    Args:
        func: The method to mark as the workflow run method

    Returns:
        The decorated method with workflow run metadata
    
    Raises:
        ValueError: If the function is not async
    """
    def decorator(f: T) -> T:
        # Validate that the function is async
        if not inspect.iscoroutinefunction(f):
            raise ValueError(f"Workflow run method '{f.__name__}' must be async")
        
        # Attach metadata to the function
        f._workflow_run = True  # type: ignore
        return f

    # Support both @workflow.run and @workflow.run()
    if func is None:
        # Called with parentheses: @workflow.run()
        return decorator
    else:
        # Called without parentheses: @workflow.run
        return decorator(func)


@dataclass
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str

class WorkflowContext(ABC):
    _var: ContextVar['WorkflowContext'] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo:
        ...

    @abstractmethod
    def client(self) -> Client:
        ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = WorkflowContext._var.set(self)
        yield None
        WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> 'WorkflowContext':
        return WorkflowContext._var.get()
