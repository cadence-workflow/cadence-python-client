from contextlib import contextmanager
from datetime import timedelta
from math import ceil
from typing import Iterator, Optional, Any, Unpack, Type, cast, Callable

from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence._internal.workflow.retry_policy import retry_policy_to_proto
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.api.v1.common_pb2 import ActivityType
from cadence.api.v1.decision_pb2 import (
    ScheduleActivityTaskDecisionAttributes,
    StartTimerDecisionAttributes,
)
from cadence.api.v1.tasklist_pb2 import TaskList, TaskListKind
from cadence.data_converter import DataConverter
from cadence.workflow import (
    ActivityOptions,
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
        event_loop: DeterministicEventLoop,
    ):
        self._info = info
        self._replay_mode = True
        self._replay_current_time_milliseconds: Optional[int] = None
        self._decision_manager = decision_manager
        self._event_loop = event_loop

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
        await self._event_loop.create_waiter(predicate)

    @contextmanager
    def _activate(self) -> Iterator["Context"]:
        token = WorkflowContext._var.set(self)
        try:
            yield self
        finally:
            WorkflowContext._var.reset(token)


def _round_to_nearest_second(delta: timedelta) -> timedelta:
    return timedelta(seconds=ceil(delta.total_seconds()))
