from typing import TypedDict


class WorkerOptions(TypedDict, total=False):
    max_concurrent_activity_execution_size: int
    max_concurrent_decision_task_execution_size: int
    task_list_activities_per_second: float
    # Remove these in favor of introducing automatic scaling prior to release
    activity_task_pollers: int
    decision_task_pollers: int
    disable_workflow_worker: bool
    disable_activity_worker: bool
    identity: str


_DEFAULT_WORKER_OPTIONS: WorkerOptions = {
    "max_concurrent_activity_execution_size": 1000,
    "max_concurrent_decision_task_execution_size": 1000,
    "task_list_activities_per_second": 0.0,
    "activity_task_pollers": 2,
    "decision_task_pollers": 2,
    "disable_workflow_worker": False,
    "disable_activity_worker": False,
}

_LONG_POLL_TIMEOUT = 60.0
