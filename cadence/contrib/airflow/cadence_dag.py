from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

from airflow import DAG
from airflow.sdk import BaseOperator
from airflow.sdk.api.datamodels._generated import TriggerRule
import msgspec

from cadence import activity, workflow
from cadence.activity import ActivityDefinition
from cadence.workflow import WorkflowDefinition

if TYPE_CHECKING:
    from airflow.sdk.types import Operator

logger = logging.getLogger(__name__)


class TaskState(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class _TaskInstance(msgspec.Struct):
    """Minimal TaskInstance stub supporting xcom operations."""

    task_id: str


def _evaluate_trigger_rule(rule: TriggerRule, upstream_states: list[TaskState]) -> bool:
    """Return True if the task should execute given its upstream states."""
    if not upstream_states:
        return True

    n_success = sum(1 for s in upstream_states if s == TaskState.SUCCESS)
    n_failed = sum(1 for s in upstream_states if s == TaskState.FAILED)
    n_skipped = sum(1 for s in upstream_states if s == TaskState.SKIPPED)
    total = len(upstream_states)

    match rule:
        case TriggerRule.ALL_SUCCESS:
            return n_success == total
        case TriggerRule.ALL_FAILED:
            return n_failed == total
        case TriggerRule.ALL_DONE | TriggerRule.ONE_DONE:
            return True
        case TriggerRule.ALL_DONE_MIN_ONE_SUCCESS:
            return n_success >= 1
        case TriggerRule.ALL_DONE_SETUP_SUCCESS:
            return n_success >= 1
        case TriggerRule.ONE_SUCCESS:
            return n_success >= 1
        case TriggerRule.ONE_FAILED:
            return n_failed >= 1
        case TriggerRule.NONE_FAILED:
            return n_failed == 0
        case TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS:
            return n_failed == 0 and n_success >= 1
        case TriggerRule.NONE_SKIPPED:
            return n_skipped == 0
        case TriggerRule.ALL_SKIPPED:
            return n_skipped == total
        case TriggerRule.ALWAYS:
            return True
        case _:
            return n_success == total


def dag_as_workflow(dag: DAG) -> WorkflowDefinition:
    class DagWorkflow:
        @workflow.run()
        async def run_dag(self) -> dict[str, TaskState]:
            """Execute all tasks in a DAG respecting dependencies and trigger rules.

            Tasks are launched concurrently; each task awaits its upstream
            dependencies before evaluating its trigger rule and executing.

            Returns a mapping of task_id -> final TaskState.
            """
            params = dag.params.dump()
            tasks = dag.topological_sort()

            task_states: dict[str, TaskState] = {}
            done_events: dict[str, asyncio.Event] = {
                task.task_id: asyncio.Event() for task in tasks
            }
            results: dict[str, Any] = {}
            errors: dict[str, BaseException] = {}

            async def _run_task(task: Operator) -> None:
                tid = task.task_id

                for upstream_id in task.upstream_task_ids:
                    await done_events[upstream_id].wait()

                upstream_states = [task_states[uid] for uid in task.upstream_task_ids]

                if not _evaluate_trigger_rule(task.trigger_rule, upstream_states):
                    logger.info(
                        "Skipping task %s (trigger rule: %s)", tid, task.trigger_rule
                    )
                    task_states[tid] = TaskState.SKIPPED
                    done_events[tid].set()
                    return

                ti = _TaskInstance(tid)
                context: dict[str, Any] = {
                    "task_instance": ti,
                    "ti": ti,
                    "params": params,
                }

                try:
                    logger.info("Executing task %s", tid)

                    # use activity
                    operator_run = operator_as_activity(task)
                    result = await operator_run.execute(context)
                    results[tid] = result
                    task_states[tid] = TaskState.SUCCESS
                    logger.info("Task %s succeeded", tid)
                except Exception as exc:
                    task_states[tid] = TaskState.FAILED
                    errors[tid] = exc
                    logger.error("Task %s failed: %s", tid, exc)
                finally:
                    done_events[tid].set()

            async with asyncio.TaskGroup() as tg:
                for task in tasks:
                    tg.create_task(_run_task(task))

            if errors:
                failed = ", ".join(errors)
                raise RuntimeError(
                    f"DAG {dag.dag_id} finished with failed tasks: {failed}"
                ) from next(iter(errors.values()))

            return task_states

    return WorkflowDefinition.wrap(DagWorkflow, {"name": dag.dag_id})


def operator_as_activity(operator: BaseOperator) -> ActivityDefinition:

    # TODO get activity options
    # TODO assume Context is serializable (it's not with XCom)

    return activity.defn(operator.execute, name=operator.task_id)
