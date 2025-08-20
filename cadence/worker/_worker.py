import asyncio
import uuid
from typing import Unpack

from cadence.client import Client
from cadence.worker._activity import ActivityWorker
from cadence.worker._decision import DecisionWorker
from cadence.worker._types import WorkerOptions, _DEFAULT_WORKER_OPTIONS


class Worker:

    def __init__(self, client: Client, task_list: str, **kwargs: Unpack[WorkerOptions]):
        self._client = client
        self._task_list = task_list

        options = WorkerOptions(**kwargs)
        _validate_and_copy_defaults(client, task_list, options)
        self._options = options
        self._activity_worker = ActivityWorker(client, task_list, options)
        self._decision_worker = DecisionWorker(client, task_list, options)


    async def run(self):
        async with asyncio.TaskGroup() as tg:
            if not self._options["disable_workflow_worker"]:
                tg.create_task(self._decision_worker.run())
            if not self._options["disable_activity_worker"]:
                tg.create_task(self._activity_worker.run())



def _validate_and_copy_defaults(client: Client, task_list: str, options: WorkerOptions):
    if "identity" not in options:
        options["identity"] = f"{client.identity}@{task_list}@{uuid.uuid4()}"

    # TODO: More validation

    for (key, value) in _DEFAULT_WORKER_OPTIONS.items():
        if key not in options:
            # noinspection PyTypedDict
            options[key] = value
