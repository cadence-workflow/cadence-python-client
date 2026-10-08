import asyncio
import logging
from datetime import timedelta

import pytest

from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskRequest,
    PollForActivityTaskRequest,
)
from google.protobuf.wrappers_pb2 import DoubleValue

from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind, TaskListMetadata
from cadence.client import Client
from cadence.worker import Worker, Registry


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_kind", ("decision", "activity"))
async def test_worker_context_propagates_background_failure(
    worker_kind: str,
) -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    internal_worker: object
    if worker_kind == "decision":
        worker = Worker(
            client,
            "task_list",
            Registry(),
            disable_activity_worker=True,
            identity="identity",
        )
        internal_worker = worker._decision_worker
    else:
        worker = Worker(
            client,
            "task_list",
            Registry(),
            disable_workflow_worker=True,
            identity="identity",
        )
        internal_worker = worker._activity_worker

    failure = RuntimeError(f"{worker_kind} worker failed")
    fail_worker = asyncio.Event()

    async def run_internal_worker() -> None:
        await fail_worker.wait()
        raise failure

    owner_task = asyncio.current_task()
    assert owner_task is not None
    cancelling_before = owner_task.cancelling()

    with (
        patch.object(internal_worker, "run", new=run_internal_worker),
        pytest.raises(RuntimeError) as exc_info,
    ):
        async with worker:
            fail_worker.set()
            await asyncio.Event().wait()

    assert exc_info.value is failure
    assert owner_task.cancelling() == cancelling_before


@pytest.mark.asyncio
async def test_worker_context_propagates_failure_after_cancellation_is_swallowed() -> (
    None
):
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_activity_worker=True,
        identity="identity",
    )
    failure = RuntimeError("workflow worker failed")
    fail_worker = asyncio.Event()

    async def run_internal_worker() -> None:
        await fail_worker.wait()
        raise failure

    with (
        patch.object(worker._decision_worker, "run", new=run_internal_worker),
        pytest.raises(RuntimeError) as exc_info,
    ):
        async with worker:
            fail_worker.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass

    assert exc_info.value is failure


@pytest.mark.asyncio
async def test_worker_context_propagates_failure_during_exit() -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_activity_worker=True,
        identity="identity",
    )
    failure = RuntimeError("workflow worker failed during exit")
    worker_started = asyncio.Event()

    async def run_internal_worker() -> None:
        worker_started.set()
        await worker._close_requested.wait()
        raise failure

    owner_task = asyncio.current_task()
    assert owner_task is not None
    cancelling_before = owner_task.cancelling()

    with (
        patch.object(worker._decision_worker, "run", new=run_internal_worker),
        pytest.raises(RuntimeError) as exc_info,
    ):
        async with worker:
            await worker_started.wait()

    assert exc_info.value is failure
    assert owner_task.cancelling() == cancelling_before


@pytest.mark.asyncio
async def test_worker_run_blocks_until_close() -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_workflow_worker=True,
        disable_activity_worker=True,
        identity="identity",
    )
    run_task = asyncio.create_task(worker.run())

    await asyncio.sleep(0)

    assert not run_task.done()

    await worker.close()
    await run_task

    assert worker._close_complete.is_set()

    with pytest.raises(RuntimeError, match="already started"):
        await worker.run()


@pytest.mark.asyncio
async def test_worker_run_cancellation_closes() -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_workflow_worker=True,
        disable_activity_worker=True,
        identity="identity",
    )
    run_task = asyncio.create_task(worker.run())

    await asyncio.sleep(0)

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert worker._close_complete.is_set()


@pytest.mark.asyncio
async def test_worker_run_propagates_background_failure() -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_activity_worker=True,
        identity="identity",
    )
    failure = RuntimeError("workflow worker failed")

    with (
        patch.object(
            worker._decision_worker,
            "run",
            new=AsyncMock(side_effect=failure),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await worker.run()

    assert exc_info.value is failure
    assert worker._close_complete.is_set()


@pytest.mark.asyncio
async def test_worker_run_logs_all_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(client, "task_list", Registry(), identity="identity")
    workflow_failure = RuntimeError("workflow worker failed")
    activity_failure = RuntimeError("activity worker failed")

    with (
        patch.object(
            worker._decision_worker,
            "run",
            new=AsyncMock(side_effect=workflow_failure),
        ),
        patch.object(
            worker._activity_worker,
            "run",
            new=AsyncMock(side_effect=activity_failure),
        ),
        caplog.at_level(logging.ERROR, logger="cadence.worker._worker"),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await worker.run()

    assert exc_info.value in (workflow_failure, activity_failure)
    failure_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Worker task failed"
    ]
    assert len(failure_records) == 2
    assert {
        record.exc_info[1] for record in failure_records if record.exc_info is not None
    } == {workflow_failure, activity_failure}


@pytest.mark.asyncio
async def test_worker_run_logs_failure_raised_during_close(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_activity_worker=True,
        identity="identity",
    )
    worker_started = asyncio.Event()
    close_failure = RuntimeError("workflow worker failed during close")

    async def fail_during_close() -> None:
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise close_failure

    with patch.object(
        worker._decision_worker,
        "run",
        new=fail_during_close,
    ):
        run_task = asyncio.create_task(worker.run())
        await worker_started.wait()
        with caplog.at_level(logging.ERROR, logger="cadence.worker._worker"):
            await worker.close()
            await run_task

    failure_records = [
        record
        for record in caplog.records
        if record.getMessage() == "Worker task failed"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].exc_info is not None
    assert failure_records[0].exc_info[1] is close_failure


@pytest.mark.asyncio
async def test_worker_context_preserves_body_failure() -> None:
    client = Mock(spec=Client)
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    worker = Worker(
        client,
        "task_list",
        Registry(),
        disable_workflow_worker=True,
        disable_activity_worker=True,
        identity="identity",
    )
    failure = RuntimeError("context body failed")

    with pytest.raises(RuntimeError) as exc_info:
        async with worker:
            raise failure

    assert exc_info.value is failure


@pytest.mark.asyncio
async def test_worker():
    client = Mock(spec=Client)
    done = asyncio.Event()
    both_waited = asyncio.Barrier(3)

    async def poll(_, timeout=0.0):
        await both_waited.wait()
        await done.wait()
        return None

    worker_stub = Mock()
    worker_stub.PollForDecisionTask = AsyncMock(side_effect=poll)
    worker_stub.PollForActivityTask = AsyncMock(side_effect=poll)

    client.worker_stub = worker_stub
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    async with Worker(
        client,
        "task_list",
        Registry(),
        activity_task_pollers=1,
        decision_task_pollers=1,
        identity="identity",
    ) as worker:
        # Wait until both polled
        await both_waited.wait()

    assert worker._options["sticky_schedule_to_start_timeout"] == timedelta(seconds=5)
    assert worker._options["sticky_cache_size"] == 10_000

    worker_stub.PollForDecisionTask.assert_called_once_with(
        PollForDecisionTaskRequest(
            domain="domain",
            identity="identity",
            task_list=TaskList(
                name="task_list", kind=TaskListKind.TASK_LIST_KIND_NORMAL
            ),
        ),
        timeout=60.0,
    )

    worker_stub.PollForActivityTask.assert_called_once_with(
        PollForActivityTaskRequest(
            domain="domain",
            identity="identity",
            task_list=TaskList(
                name="task_list", kind=TaskListKind.TASK_LIST_KIND_NORMAL
            ),
        ),
        timeout=60.0,
    )


@pytest.mark.asyncio
async def test_worker_sends_task_list_activities_per_second():
    client = Mock(spec=Client)
    done = asyncio.Event()
    both_waited = asyncio.Barrier(3)

    async def poll(_, timeout=0.0):
        await both_waited.wait()
        await done.wait()
        return None

    worker_stub = Mock()
    worker_stub.PollForDecisionTask = AsyncMock(side_effect=poll)
    worker_stub.PollForActivityTask = AsyncMock(side_effect=poll)

    client.worker_stub = worker_stub
    type(client).domain = PropertyMock(return_value="domain")
    type(client).identity = PropertyMock(return_value="identity")
    type(client).context_propagators = PropertyMock(return_value=())

    async with Worker(
        client,
        "task_list",
        Registry(),
        activity_task_pollers=1,
        decision_task_pollers=1,
        identity="identity",
        task_list_activities_per_second=12.5,
        sticky_schedule_to_start_timeout=timedelta(seconds=30),
        sticky_cache_size=500,
    ) as worker:
        await both_waited.wait()

    assert worker._options["sticky_schedule_to_start_timeout"] == timedelta(seconds=30)
    assert worker._options["sticky_cache_size"] == 500

    worker_stub.PollForActivityTask.assert_called_once_with(
        PollForActivityTaskRequest(
            domain="domain",
            identity="identity",
            task_list=TaskList(
                name="task_list", kind=TaskListKind.TASK_LIST_KIND_NORMAL
            ),
            task_list_metadata=TaskListMetadata(
                max_tasks_per_second=DoubleValue(value=12.5)
            ),
        ),
        timeout=60.0,
    )
