import asyncio
import uuid
from typing import Unpack, cast

from cadence.client import Client
from cadence.worker._registry import Registry
from cadence.worker._activity import ActivityWorker
from cadence.worker._decision import DecisionWorker
from cadence.worker._types import WorkerOptions, _DEFAULT_WORKER_OPTIONS


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

        options = WorkerOptions(**kwargs)
        _validate_and_copy_defaults(client, task_list, options)
        self._options = options
        self._activity_worker = ActivityWorker(client, task_list, registry, options)
        self._decision_worker = DecisionWorker(client, task_list, registry, options)

    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            if not self._options["disable_workflow_worker"]:
                tg.create_task(self._decision_worker.run())
            if not self._options["disable_activity_worker"]:
                tg.create_task(self._activity_worker.run())


def _validate_and_copy_defaults(
    client: Client, task_list: str, options: WorkerOptions
) -> None:
    if "identity" not in options:
        options["identity"] = f"{client.identity}@{task_list}@{uuid.uuid4()}"

    # TODO: More validation

    # Set default values for missing options
    for key, value in _DEFAULT_WORKER_OPTIONS.items():
        if key not in options:
            cast(dict, options)[key] = value
