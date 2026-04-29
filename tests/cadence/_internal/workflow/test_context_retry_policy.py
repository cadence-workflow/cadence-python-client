from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.protobuf.duration_pb2 import Duration

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence.api.v1.common_pb2 import ActivityType
from cadence.api.v1.decision_pb2 import ScheduleActivityTaskDecisionAttributes
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo


@pytest.mark.asyncio
async def test_execute_activity_passes_retry_policy_to_schedule():
    dm = MagicMock()
    dm.schedule_activity = AsyncMock(
        return_value=DefaultDataConverter().to_data(["result"])
    )

    info = WorkflowInfo(
        workflow_type="Wf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id="rid",
        workflow_task_list="tl",
        data_converter=DefaultDataConverter(),
    )
    ctx = Context(info, dm, DeterministicEventLoop())

    await ctx.execute_activity(
        "Act",
        str,
        retry_policy={
            "initial_interval": timedelta(seconds=2),
            "backoff_coefficient": 2.0,
            "maximum_attempts": 3,
        },
    )

    dm.schedule_activity.assert_awaited_once()
    attrs: ScheduleActivityTaskDecisionAttributes = dm.schedule_activity.call_args[0][0]
    assert attrs.activity_type == ActivityType(name="Act")
    assert attrs.domain == "domain"
    assert attrs.task_list == TaskList(
        kind=TaskListKind.TASK_LIST_KIND_NORMAL, name="tl"
    )
    rp = attrs.retry_policy
    assert rp is not None
    assert rp.initial_interval == Duration(seconds=2)
    assert rp.backoff_coefficient == 2.0
    assert rp.maximum_attempts == 3
