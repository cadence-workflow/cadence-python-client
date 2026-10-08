import asyncio
import logging
import uuid
from types import TracebackType
from typing import Unpack, cast

from cadence.client import Client
from cadence.worker._registry import Registry
from cadence.worker._activity import ActivityWorker
from cadence.worker._decision import DecisionWorker
from cadence.worker._types import WorkerOptions, _DEFAULT_WORKER_OPTIONS
from cadence._internal.context import validate_propagators

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        client: Client,
        task_list: str,
        registry: Registry,
        **kwargs: Unpack[WorkerOptions],
    ) -> None:
        self._client = client
        self._task_list = task_list

        # Prevents a Worker instance from being started more than once.
        self._started = False

        # fields used by run, close
        # run() exclusively owns, cancels, and joins internal worker tasks.
        # close() only sends a cooperative request and waits for acknowledgment.
        self._close_requested = asyncio.Event()
        self._close_complete = asyncio.Event()

        # fields used by context manager
        self._context_entered = False
        self._context_task_group: asyncio.TaskGroup  # TODO: TaskGroup leaks owner cancel count on Py3.11/3.12 when run() fails in exit

        options = WorkerOptions(**kwargs)
        _validate_and_copy_defaults(client, task_list, options)
        self._options = options
        self._activity_worker = ActivityWorker(client, task_list, registry, options)
        self._decision_worker = DecisionWorker(client, task_list, registry, options)

    @property
    def client(self) -> Client:
        return self._client

    @property
    def task_list(self) -> str:
        return self._task_list

    async def run(self) -> None:
        """Run until close is requested or an internal worker fails."""
        if self._started:
            raise RuntimeError("Worker already started")
        self._started = True

        worker_tasks: list[tuple[str, asyncio.Task[None]]] = []
        if not self._options["disable_workflow_worker"]:
            worker_tasks.append(
                (
                    "Workflow",
                    asyncio.create_task(self._decision_worker.run()),
                )
            )
        if not self._options["disable_activity_worker"]:
            worker_tasks.append(
                (
                    "Activity",
                    asyncio.create_task(self._activity_worker.run()),
                )
            )

        async def wait_for_close() -> None:
            await self._close_requested.wait()

        close_task = asyncio.create_task(wait_for_close())
        tasks = [close_task, *(task for _, task in worker_tasks)]

        try:
            done, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for worker_name, task in worker_tasks:
                if task not in done:
                    continue
                if task.cancelled():
                    raise RuntimeError(f"{worker_name} worker was cancelled")
                error = task.exception()
                if error is not None:
                    raise error
                raise RuntimeError(f"{worker_name} worker exited unexpectedly")
        finally:
            self._close_requested.set()
            for task in tasks:
                task.cancel()
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results[1:]:
                    if isinstance(result, BaseException) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        logger.error("Worker task failed", exc_info=result)
            finally:
                self._close_complete.set()

    async def close(self) -> None:
        """Request close and wait for the worker to finish."""
        self._close_requested.set()
        if self._started:
            await self._close_complete.wait()

    async def __aenter__(self) -> "Worker":
        if self._context_entered or self._started:
            raise RuntimeError("Worker already started")
        self._context_entered = True

        self._context_task_group = asyncio.TaskGroup()
        await self._context_task_group.__aenter__()
        self._context_task_group.create_task(self.run())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self._close_requested.set()
        try:
            await self._context_task_group.__aexit__(None, None, None)
        except BaseExceptionGroup as errors:
            # If the context body raised an exception, do not raise the worker error here.
            if exc_type is not None and exc_type is not asyncio.CancelledError:
                return
            # run() is the task group's only child, so expose its original error.
            if len(errors.exceptions) == 1:
                raise errors.exceptions[0]
            raise RuntimeError(
                f"Worker task group unexpectedly produced {len(errors.exceptions)} errors"
            ) from errors


def _validate_and_copy_defaults(
    client: Client, task_list: str, options: WorkerOptions
) -> None:
    if "identity" not in options:
        options["identity"] = f"{client.identity}@{task_list}@{uuid.uuid4()}"

    if "metrics_emitter" not in options:
        cast(dict, options)["metrics_emitter"] = client.metrics_emitter
    if "context_propagators" not in options:
        cast(dict, options)["context_propagators"] = client.context_propagators

    # TODO: More validation

    # Set default values for missing options
    for key, value in _DEFAULT_WORKER_OPTIONS.items():
        if key not in options:
            cast(dict, options)[key] = value
    cast(dict, options)["context_propagators"] = tuple(
        options.get("context_propagators") or ()
    )
    validate_propagators(options["context_propagators"])
