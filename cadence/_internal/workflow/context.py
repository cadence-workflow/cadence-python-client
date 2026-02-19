from contextlib import contextmanager
from datetime import timedelta
from math import ceil
from typing import Iterator, Optional, Any, Unpack, Type, cast

from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1.common_pb2 import ActivityType
from cadence.api.v1.decision_pb2 import ScheduleActivityTaskDecisionAttributes
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DataConverter
from cadence.workflow import WorkflowContext, WorkflowInfo, ResultType, ActivityOptions


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
        opts = ActivityOptions(**kwargs)
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
            retry_policy=None,
            header=None,
            request_local_dispatch=False,
        )

        result_payload = await self._decision_manager.schedule_activity(
            schedule_attributes
        )

        result = self.data_converter().from_data(result_payload, [result_type])[0]

        return cast(ResultType, result)

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

    @contextmanager
    def _activate(self) -> Iterator["Context"]:
        token = WorkflowContext._var.set(self)
        yield self
        WorkflowContext._var.reset(token)


def _round_to_nearest_second(delta: timedelta) -> timedelta:
    return timedelta(seconds=ceil(delta.total_seconds()))
