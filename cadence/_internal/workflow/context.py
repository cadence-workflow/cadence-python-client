from __future__ import annotations

from contextlib import contextmanager
from asyncio import get_running_loop
from datetime import timedelta
from math import ceil
from typing import Iterator, Optional, Any, Unpack, Type, cast, Callable

from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence._internal.workflow.retry_policy import retry_policy_to_proto
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1 import workflow_pb2
from cadence.api.v1.common_pb2 import ActivityType, WorkflowType
from cadence.api.v1.decision_pb2 import (
    ScheduleActivityTaskDecisionAttributes,
    StartChildWorkflowExecutionDecisionAttributes,
    StartTimerDecisionAttributes,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DataConverter
from cadence.workflow import (
    ActivityOptions,
    ChildWorkflowFuture,
    ChildWorkflowOptions,
    ResultType,
    WorkflowContext,
    WorkflowInfo,
)

_DEFAULT_ACTIVITY_OPTIONS: ActivityOptions = {
    "schedule_to_close_timeout": timedelta(hours=1),
    "schedule_to_start_timeout": timedelta(seconds=10),
}


class Context(WorkflowContext):
    def __init__(
        self,
        info: WorkflowInfo,
        decision_manager: DecisionManager,
    ):
        self._info = info
        self._replay_mode = True
        self._replay_current_time_milliseconds: Optional[int] = None
        self._decision_manager = decision_manager

    def info(self) -> WorkflowInfo:
        return self._info

    def data_converter(self) -> DataConverter:
        return self.info().data_converter

    async def execute_activity(
        self,
        activity: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ActivityOptions],
    ) -> ResultType:
        opts: ActivityOptions = {**_DEFAULT_ACTIVITY_OPTIONS, **kwargs}
        if "schedule_to_close_timeout" not in opts and (
            "schedule_to_start_timeout" not in opts
            or "start_to_close_timeout" not in opts
        ):
            raise ValueError(
                "Either schedule_to_close_timeout or both schedule_to_start_timeout and start_to_close_timeout must be specified"
            )

        schedule_to_close = opts.get("schedule_to_close_timeout", None)
        schedule_to_start = opts.get("schedule_to_start_timeout", None)
        start_to_close = opts.get("start_to_close_timeout", None)
        heartbeat = opts.get("heartbeat_timeout", None)

        if schedule_to_close is None:
            schedule_to_close = schedule_to_start + start_to_close  # type: ignore

        if start_to_close is None:
            start_to_close = schedule_to_close

        if schedule_to_start is None:
            schedule_to_start = schedule_to_close

        if heartbeat is None:
            heartbeat = schedule_to_close

        task_list = (
            opts["task_list"]
            if opts.get("task_list", None)
            else self._info.workflow_task_list
        )

        activity_input = self.data_converter().to_data(list(args))
        schedule_attributes = ScheduleActivityTaskDecisionAttributes(
            activity_type=ActivityType(name=activity),
            domain=self.info().workflow_domain,
            task_list=TaskList(kind=TaskListKind.TASK_LIST_KIND_NORMAL, name=task_list),
            input=activity_input,
            schedule_to_close_timeout=_round_to_nearest_second(schedule_to_close),
            schedule_to_start_timeout=_round_to_nearest_second(schedule_to_start),
            start_to_close_timeout=_round_to_nearest_second(start_to_close),
            heartbeat_timeout=_round_to_nearest_second(heartbeat),
            retry_policy=retry_policy_to_proto(opts.get("retry_policy")),
            header=None,
            request_local_dispatch=False,
        )

        future = self._decision_manager.schedule_activity(schedule_attributes)
        result_payload = await future

        result = self.data_converter().from_data(result_payload, [result_type])[0]

        return cast(ResultType, result)

    async def execute_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ResultType:
        future = await self.start_child_workflow(
            workflow_type, result_type, *args, **kwargs
        )
        return await future

    async def start_child_workflow(
        self,
        workflow_type: str,
        result_type: Type[ResultType],
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> ChildWorkflowFuture[ResultType]:
        schedule_attributes = self._build_child_workflow_attrs(
            workflow_type, *args, **kwargs
        )
        execution_future, result_future = (
            self._decision_manager.schedule_child_workflow(
                schedule_attributes,
                parent_workflow_run_id=self._info.workflow_run_id,
            )
        )
        workflow_execution = await execution_future
        return ChildWorkflowFuture(
            workflow_id=workflow_execution.workflow_id,
            run_id=workflow_execution.run_id,
            result_future=result_future,
            result_type=result_type,
            data_converter=self.data_converter(),
        )

    def _build_child_workflow_attrs(
        self,
        workflow_type: str,
        *args: Any,
        **kwargs: Unpack[ChildWorkflowOptions],
    ) -> StartChildWorkflowExecutionDecisionAttributes:
        execution_timeout = kwargs.get("execution_start_to_close_timeout")
        if execution_timeout is None:
            raise ValueError(
                "execution_start_to_close_timeout is required for child workflow execution"
            )
        if execution_timeout <= timedelta(0):
            raise ValueError("execution_start_to_close_timeout must be greater than 0")

        task_timeout = kwargs.get("task_start_to_close_timeout", timedelta(seconds=10))
        if task_timeout <= timedelta(0):
            raise ValueError("task_start_to_close_timeout must be greater than 0")

        domain = kwargs.get("domain") or self._info.workflow_domain
        task_list = kwargs.get("task_list") or self._info.workflow_task_list

        workflow_id = kwargs.get("workflow_id") or ""

        parent_close_policy = kwargs.get(
            "parent_close_policy",
            workflow_pb2.PARENT_CLOSE_POLICY_TERMINATE,
        )
        workflow_id_reuse_policy = kwargs.get(
            "workflow_id_reuse_policy",
            workflow_pb2.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY,
        )
        if workflow_id_reuse_policy == workflow_pb2.WORKFLOW_ID_REUSE_POLICY_INVALID:
            raise ValueError(
                "workflow_id_reuse_policy cannot be WORKFLOW_ID_REUSE_POLICY_INVALID"
            )

        child_input = self.data_converter().to_data(list(args))
        schedule_attributes = StartChildWorkflowExecutionDecisionAttributes(
            domain=domain,
            workflow_id=workflow_id,
            workflow_type=WorkflowType(name=workflow_type),
            task_list=TaskList(kind=TaskListKind.TASK_LIST_KIND_NORMAL, name=task_list),
            input=child_input,
            execution_start_to_close_timeout=_round_to_nearest_second(
                execution_timeout
            ),
            task_start_to_close_timeout=_round_to_nearest_second(task_timeout),
            parent_close_policy=parent_close_policy,
            workflow_id_reuse_policy=workflow_id_reuse_policy,
            retry_policy=retry_policy_to_proto(kwargs.get("retry_policy")),
        )

        cron_schedule = kwargs.get("cron_schedule")
        if cron_schedule:
            schedule_attributes.cron_schedule = cron_schedule

        return schedule_attributes

    async def start_timer(self, duration: timedelta):
        if duration.total_seconds() <= 0:  # shortcut
            return
        future = self._decision_manager.start_timer(
            StartTimerDecisionAttributes(
                start_to_fire_timeout=duration,
            )
        )
        await future

    def set_replay_mode(self, replay: bool) -> None:
        """Set whether the workflow is currently in replay mode."""
        self._replay_mode = replay

    def is_replay_mode(self) -> bool:
        """Check if the workflow is currently in replay mode."""
        return self._replay_mode

    def set_replay_current_time_milliseconds(self, time_millis: int) -> None:
        """Set the current replay time in milliseconds."""
        self._replay_current_time_milliseconds = time_millis

    def get_replay_current_time_milliseconds(self) -> Optional[int]:
        """Get the current replay time in milliseconds."""
        return self._replay_current_time_milliseconds

    async def wait_condition(self, predicate: Callable[[], bool]) -> None:
        loop = cast(DeterministicEventLoop, get_running_loop())
        await loop.create_waiter(predicate)

    @contextmanager
    def _activate(self) -> Iterator["Context"]:
        token = WorkflowContext._var.set(self)
        try:
            yield self
        finally:
            WorkflowContext._var.reset(token)


def _round_to_nearest_second(delta: timedelta) -> timedelta:
    return timedelta(seconds=ceil(delta.total_seconds()))
