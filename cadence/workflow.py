from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Callable, TypeVar, TypedDict, Type, cast, Any
from functools import wraps

from cadence.client import Client

T = TypeVar('T')


class WorkflowDefinitionOptions(TypedDict, total=False):
    """Options for defining a workflow."""
    name: str


class WorkflowDefinition:
    """
    Definition of a workflow class with metadata.

    Similar to ActivityDefinition but for workflow classes.
    Provides type safety and metadata for workflow classes.
    """

    def __init__(self, cls: Type, name: str):
        self._cls = cls
        self._name = name

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
        for attr_name in dir(instance):
            if attr_name.startswith('_'):
                continue
            attr = getattr(instance, attr_name)
            if callable(attr) and hasattr(attr, '_workflow_run'):
                return cast(Callable, attr)
        raise ValueError(f"No @workflow.run method found in class {self._cls.__name__}")

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

        # Validate that the class has exactly one run method
        run_method_count = 0
        for attr_name in dir(cls):
            if attr_name.startswith('_'):
                continue

            attr = getattr(cls, attr_name)
            if not callable(attr):
                continue

            # Check for workflow run method
            if hasattr(attr, '_workflow_run'):
                run_method_count += 1

        if run_method_count == 0:
            raise ValueError(f"No @workflow.run method found in class {cls.__name__}")
        elif run_method_count > 1:
            raise ValueError(f"Multiple @workflow.run methods found in class {cls.__name__}")

        return WorkflowDefinition(cls, name)


def run(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to mark a method as the main workflow run method.

    Args:
        func: The method to mark as the workflow run method

    Returns:
        The decorated method with workflow run metadata
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    # Attach metadata to the function
    wrapper._workflow_run = True  # type: ignore
    return wrapper


# Create a simple namespace object for the workflow decorators
class _WorkflowNamespace:
    run = staticmethod(run)

workflow = _WorkflowNamespace()


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
