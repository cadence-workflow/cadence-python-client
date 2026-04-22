from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from typing import (
    Iterator,
    Callable,
    TypeVar,
    TypedDict,
    Type,
    cast,
    Any,
    Optional,
    Union,
    Unpack,
    Generic,
    NoReturn,
)
import inspect

from cadence._internal.fn_signature import FnSignature
from cadence.data_converter import DataConverter
from cadence.error import ContinueAsNewError
from cadence.signal import SignalDefinition, SignalDefinitionOptions

ResultType = TypeVar("ResultType")


class RetryPolicy(TypedDict, total=False):
    initial_interval: timedelta
    backoff_coefficient: float
    maximum_interval: timedelta
    maximum_attempts: int
    non_retryable_error_reasons: list[str]
    expiration_interval: timedelta


class ActivityOptions(TypedDict, total=False):
    task_list: str
    schedule_to_close_timeout: timedelta
    schedule_to_start_timeout: timedelta
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta
    retry_policy: RetryPolicy


async def execute_activity(
    activity: str,
    result_type: Type[ResultType],
    *args: Any,
    **kwargs: Unpack[ActivityOptions],
) -> ResultType:
    return await WorkflowContext.get().execute_activity(
        activity, result_type, *args, **kwargs
    )


async def sleep(duration: timedelta) -> None:
    return await WorkflowContext.get().start_timer(duration)


async def wait_condition(predicate: Callable[[], bool]) -> None:
    """Block until predicate returns True.

    The predicate is re-evaluated after any workflow state change
    (signal delivery, activity completion, timer firing).
    If the predicate is already True, returns immediately.
    """
    await WorkflowContext.get().wait_condition(predicate)


def continue_as_new(
    *args: Any,
    workflow_type: str | None = None,
    task_list: str | None = None,
    execution_start_to_close_timeout: timedelta | None = None,
    task_start_to_close_timeout: timedelta | None = None,
) -> NoReturn:
    """Continue this workflow as a new execution.

    This function never returns. It raises ContinueAsNewError which
    propagates out of the workflow to signal the worker to create a
    continue-as-new decision.

    This is different from go sdk

    Args:
        *args: Arguments for the new workflow execution.
        workflow_type: Override workflow type (default: same type).
        task_list: Override task list (default: same task list).
        execution_start_to_close_timeout: Override execution timeout.
        task_start_to_close_timeout: Override task timeout.
    """
    raise ContinueAsNewError(
        *args,
        workflow_type=workflow_type,
        task_list=task_list,
        execution_start_to_close_timeout=execution_start_to_close_timeout,
        task_start_to_close_timeout=task_start_to_close_timeout,
    )


T = TypeVar("T", bound=Callable[..., Any])
C = TypeVar("C")


class WorkflowDefinitionOptions(TypedDict, total=False):
    """Options for defining a workflow."""

    name: str


class WorkflowDefinition(Generic[C]):
    """
    Definition of a workflow class with metadata.

    Similar to ActivityDefinition but for workflow classes.
    Provides type safety and metadata for workflow classes.
    """

    def __init__(
        self,
        cls: Type[C],
        name: str,
        run_method_name: str,
        signals: dict[str, SignalDefinition[..., Any]],
        run_signature: FnSignature,
    ):
        self._cls: Type[C] = cls
        self._name = name
        self._run_method_name = run_method_name
        self._signals = signals
        self._run_signature = run_signature

    @property
    def signals(self) -> dict[str, SignalDefinition[..., Any]]:
        """Get the signal definitions."""
        return self._signals

    @property
    def name(self) -> str:
        """Get the workflow name."""
        return self._name

    @property
    def cls(self) -> Type[C]:
        """Get the workflow class."""
        return self._cls

    def get_run_method(self, instance: Any) -> Callable:
        """Get the workflow run method from an instance of the workflow class."""
        return cast(Callable, getattr(instance, self._run_method_name))

    @staticmethod
    def wrap(cls: Type, opts: WorkflowDefinitionOptions) -> "WorkflowDefinition":
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
        # Also validate that class does not have multiple signal methods with the same name
        signals: dict[str, SignalDefinition[..., Any]] = {}
        signal_names: dict[
            str, str
        ] = {}  # Map signal name to method name for duplicate detection
        run_method_name = None
        run_signature = None
        for attr_name in dir(cls):
            if attr_name.startswith("_"):
                continue

            attr = getattr(cls, attr_name)
            if not callable(attr):
                continue

            # Check for workflow run method
            if hasattr(attr, "_workflow_run"):
                if run_method_name is not None:
                    raise ValueError(
                        f"Multiple @workflow.run methods found in class {cls.__name__}"
                    )
                run_method_name = attr_name
                run_signature = FnSignature.of(attr)

            if hasattr(attr, "_workflow_signal"):
                signal_name = getattr(attr, "_workflow_signal")
                if signal_name in signal_names:
                    raise ValueError(
                        f"Multiple @workflow.signal methods found in class {cls.__name__} "
                        f"with signal name '{signal_name}': '{attr_name}' and '{signal_names[signal_name]}'"
                    )
                # Create SignalDefinition from the decorated method
                signal_def = SignalDefinition.wrap(
                    attr, SignalDefinitionOptions(name=signal_name)
                )
                signals[signal_name] = signal_def
                signal_names[signal_name] = attr_name

        if run_method_name is None or run_signature is None:
            raise ValueError(f"No @workflow.run method found in class {cls.__name__}")

        return WorkflowDefinition(cls, name, run_method_name, signals, run_signature)


class WorkflowDecorator:
    def __init__(
        self,
        options: WorkflowDefinitionOptions,
        callback_fn: Callable[[WorkflowDefinition], None] | None = None,
    ):
        self._options = options
        self._callback_fn = callback_fn

    def __call__(self, cls: Type[C]) -> Type[C]:
        workflow_opts = WorkflowDefinitionOptions(**self._options)
        workflow_opts["name"] = self._options.get("name") or cls.__name__
        workflow_def = WorkflowDefinition.wrap(cls, workflow_opts)
        if self._callback_fn is not None:
            self._callback_fn(workflow_def)

        return cls


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
        setattr(f, "_workflow_run", None)
        return f

    # Support both @workflow.run and @workflow.run()
    if func is None:
        # Called with parentheses: @workflow.run()
        return decorator
    else:
        # Called without parentheses: @workflow.run
        return decorator(func)


def signal(name: str | None = None) -> Callable[[T], T]:
    """
    Decorator to mark a method as a workflow signal handler.

    Signal handlers must be **synchronous** functions that mutate workflow
    state and return ``None``.  They run on the deterministic event loop
    in the same thread as the workflow; keep them fast and free of I/O.

    Async signal handlers are not supported and will be rejected at
    definition time.  The SDK's deterministic event loop does not track
    detached tasks, so an ``async def`` handler could silently diverge
    from the replay-safe execution model.

    Example::

        @workflow.signal(name="approval_channel")
        def approve(self, approved: bool) -> None:
            self.approved = approved

    Concurrency constraints:
        * Do **not** use native threads or ``asyncio`` primitives
          (``asyncio.Event``, ``asyncio.Lock``, etc.) inside signal
          handlers — they are not replay-safe.
        * Do **not** rely on the GIL for thread-safety; CPython now
          supports free-threaded builds where the GIL can be disabled.
        * Signal handlers should be short, synchronous, state-mutating
          functions.  Use :func:`wait_condition` in the main workflow
          coroutine to react to state changes made by signal handlers.

    Args:
        name: The name of the signal

    Returns:
        The decorated method with workflow signal metadata

    Raises:
        ValueError: If name is not provided
        TypeError: If the handler is async

    """
    if name is None:
        raise ValueError("name is required")

    def decorator(f: T) -> T:
        if inspect.iscoroutinefunction(f):
            raise TypeError(
                f"Signal handler '{f.__qualname__}' must be synchronous. "
                f"Async signal handlers are not supported. "
                f"Use a synchronous handler that mutates workflow state, "
                f"then use workflow.wait_condition() in the main workflow coroutine."
            )
        f._workflow_signal = name  # type: ignore
        return f

    return decorator


@dataclass(frozen=True)
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str
    workflow_task_list: str
    data_converter: DataConverter


class WorkflowContext(ABC):
    _var: ContextVar["WorkflowContext"] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo: ...

    @abstractmethod
    def data_converter(self) -> DataConverter: ...

    @abstractmethod
    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType: ...

    @abstractmethod
    async def start_timer(self, duration: timedelta) -> None: ...

    @abstractmethod
    async def wait_condition(self, predicate: Callable[[], bool]) -> None: ...

    @contextmanager
    def _activate(self) -> Iterator["WorkflowContext"]:
        token = WorkflowContext._var.set(self)
        try:
            yield self
        finally:
            WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> "WorkflowContext":
        res = WorkflowContext._var.get(None)
        if res is None:
            raise RuntimeError("Workflow function used outside of workflow context")
        return res
