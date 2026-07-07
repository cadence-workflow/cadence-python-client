import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Optional

from cadence._internal.workflow.history_event_iterator import iterate_history_events
from cadence._internal.workflow.memo import memo_from_proto
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.service_worker_pb2 import (
    PollForDecisionTaskResponse,
    RespondDecisionTaskCompletedRequest,
    RespondDecisionTaskFailedRequest,
    RespondQueryTaskCompletedRequest,
)
from cadence.api.v1.query_pb2 import (
    WorkflowQueryResult,
    QUERY_RESULT_TYPE_FAILED,
)
from cadence.api.v1.workflow_pb2 import DecisionTaskFailedCause
from cadence.client import Client
from cadence.metrics import MetricsEmitter
from cadence.metrics.constants import (
    DECISION_EXECUTION_FAILED_COUNTER,
    DECISION_EXECUTION_LATENCY,
    DECISION_RESPONSE_FAILED_COUNTER,
    DECISION_RESPONSE_LATENCY,
    DECISION_TASK_COMPLETED_COUNTER,
    DECISION_TASK_PANIC_COUNTER,
    TAG_DOMAIN,
    TAG_TASK_LIST,
    TAG_WORKFLOW_TYPE,
    WORKFLOW_CANCELED_COUNTER,
    WORKFLOW_COMPLETED_COUNTER,
    WORKFLOW_CONTINUE_AS_NEW_COUNTER,
    WORKFLOW_END_TO_END_LATENCY,
    WORKFLOW_FAILED_COUNTER,
)
from cadence.worker._base_task_handler import BaseTaskHandler
from cadence._internal.workflow.workflow_engine import (
    WorkflowEngine,
    DecisionResult,
    _outcome_from_decision,
)
from cadence.workflow import WorkflowInfo
from cadence.worker._registry import Registry

logger = logging.getLogger(__name__)


class DecisionTaskHandler(BaseTaskHandler[PollForDecisionTaskResponse]):
    """
    Task handler for processing decision tasks.

    This handler processes decision tasks and generates decisions using workflow engines.
    Uses a thread-safe cache to hold workflow engines for concurrent decision task handling.
    """

    def __init__(
        self,
        client: Client,
        task_list: str,
        registry: Registry,
        identity: str = "unknown",
        executor: Optional[ThreadPoolExecutor] = None,
        **options,
    ):
        """
        Initialize the decision task handler.

        Args:
            client: The Cadence client instance
            task_list: The task list name
            registry: Registry containing workflow functions
            identity: The worker identity
            **options: Additional options for the handler
        """
        super().__init__(client, task_list, identity, **options)
        self._registry = registry
        self._executor = executor

    async def _handle_task_implementation(
        self, task: PollForDecisionTaskResponse
    ) -> None:
        """
        Handle a decision task implementation.

        Args:
            task: The decision task to handle
        """
        # Extract workflow execution info
        workflow_execution = task.workflow_execution
        workflow_type = task.workflow_type

        if not workflow_execution or not workflow_type:
            logger.error(
                "Decision task missing workflow execution or type. Task: %r", task
            )
            raise ValueError("Missing workflow execution or type")

        workflow_id = workflow_execution.workflow_id
        run_id = workflow_execution.run_id
        workflow_type_name = workflow_type.name

        is_query_task = task.HasField("query")

        wf_tags = {
            TAG_WORKFLOW_TYPE: workflow_type_name,
            TAG_DOMAIN: self._client.domain,
            TAG_TASK_LIST: self.task_list,
        }
        emitter = self._metrics_emitter.with_tags(wf_tags)

        logger.info(
            "Received decision task for workflow",
            extra={
                "workflow_type": workflow_type_name,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "started_event_id": task.started_event_id,
                "attempt": task.attempt,
                "is_query_task": is_query_task,
                "task_token": task.task_token[:16].hex() if task.task_token else None,
            },
        )

        try:
            workflow_definition = self._registry.get_workflow(workflow_type_name)
        except KeyError:
            logger.error(
                "Workflow type not found in registry",
                extra={
                    "workflow_type": workflow_type_name,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "error_type": "workflow_not_registered",
                },
            )
            if is_query_task:
                await self._respond_query_task_failed(
                    task, f"Workflow type '{workflow_type_name}' not found"
                )
                return
            raise KeyError(f"Workflow type '{workflow_type_name}' not found")

        # fetch full workflow history
        # TODO sticky cache
        workflow_events = [
            event async for event in iterate_history_events(task, self._client, emitter)
        ]

        if not workflow_events:
            raise ValueError(
                "Workflow history yielded no events; cannot process decision task."
            )

        if not workflow_events[0].HasField(
            "workflow_execution_started_event_attributes"
        ):
            raise ValueError(
                "Workflow history does not contain a WorkflowExecutionStarted event."
            )
        started_attrs = workflow_events[0].workflow_execution_started_event_attributes

        memo = (
            memo_from_proto(self._client.data_converter, started_attrs.memo)
            if started_attrs.HasField("memo")
            else None
        )

        workflow_info = WorkflowInfo(
            workflow_type=workflow_type_name,
            workflow_domain=self._client.domain,
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            workflow_task_list=self.task_list,
            data_converter=self._client.data_converter,
            memo=memo,
        )

        workflow_engine = WorkflowEngine(
            info=workflow_info,
            workflow_definition=workflow_definition,
        )

        exec_start = time.monotonic()
        try:
            decision_result = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                workflow_engine.process_decision,
                workflow_events,
                task.query if is_query_task else None,
            )
        except Exception:
            emitter.counter(DECISION_EXECUTION_FAILED_COUNTER)
            emitter.counter(DECISION_TASK_PANIC_COUNTER)
            raise
        finally:
            emitter.histogram(
                DECISION_EXECUTION_LATENCY, (time.monotonic() - exec_start) * 1e9
            )
        if is_query_task:
            if not decision_result.query_result:
                raise ValueError("Query result is empty")
            await self._respond_query_task_completed(task, decision_result.query_result)
        else:
            await self._respond_decision_task_completed(task, decision_result, emitter)
            outcome = next(
                (
                    o
                    for d in decision_result.decisions
                    if (o := _outcome_from_decision(d))
                ),
                None,
            )
            if outcome is not None:
                self._emit_workflow_outcome_metrics(outcome, workflow_events, emitter)

        logger.info(
            "Successfully processed decision task",
            extra={
                "workflow_type": workflow_type_name,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "started_event_id": task.started_event_id,
                "is_query_task": is_query_task,
            },
        )

    async def handle_task_failure(
        self, task: PollForDecisionTaskResponse, error: Exception
    ) -> None:
        """
        Handle decision task processing failure.

        For query tasks, responds with RespondQueryTaskCompleted with an error.
        For normal decision tasks, responds with RespondDecisionTaskFailed.

        Args:
            task: The task that failed
            error: The exception that occurred
        """
        workflow_execution = task.workflow_execution
        workflow_id = (
            workflow_execution.workflow_id if workflow_execution else "unknown"
        )
        run_id = workflow_execution.run_id if workflow_execution else "unknown"
        workflow_type = task.workflow_type.name if task.workflow_type else "unknown"

        # For query tasks, respond with a query failure instead of decision failure
        if task.HasField("query"):
            await self._respond_query_task_failed(task, str(error))
            return

        logger.error(
            "Decision task processing failure",
            extra={
                "workflow_type": workflow_type,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "started_event_id": task.started_event_id,
                "attempt": task.attempt,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "is_query_task": task.HasField("query"),
            },
            exc_info=True,
        )

        # Determine the failure cause
        # TODO revisit failure cause logic
        cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_UNHANDLED_DECISION
        if isinstance(error, KeyError):
            cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_WORKFLOW_WORKER_UNHANDLED_FAILURE
        elif isinstance(error, ValueError):
            cause = DecisionTaskFailedCause.DECISION_TASK_FAILED_CAUSE_BAD_SCHEDULE_ACTIVITY_ATTRIBUTES

        # TODO: Use a data converter for error details serialization
        error_message = str(error).encode("utf-8")
        details = Payload(data=error_message)

        try:
            await self._client.worker_stub.RespondDecisionTaskFailed(
                RespondDecisionTaskFailedRequest(
                    task_token=task.task_token,
                    cause=cause,
                    identity=self._identity,
                    details=details,
                )
            )
            logger.info(
                "Decision task failure response sent",
                extra={
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "cause": cause,
                    "task_token": task.task_token[:16].hex()
                    if task.task_token
                    else None,
                },
            )
        except Exception as e:
            logger.error(
                "Error responding to decision task failure",
                extra={
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "original_error": type(error).__name__,
                    "response_error": type(e).__name__,
                },
                exc_info=True,
            )

    def _emit_workflow_outcome_metrics(
        self, outcome: str, workflow_events: list, emitter: MetricsEmitter
    ) -> None:
        counter_map = {
            "completed": WORKFLOW_COMPLETED_COUNTER,
            "failed": WORKFLOW_FAILED_COUNTER,
            "canceled": WORKFLOW_CANCELED_COUNTER,
            "continue_as_new": WORKFLOW_CONTINUE_AS_NEW_COUNTER,
        }
        if counter := counter_map.get(outcome):
            emitter.counter(counter)

        if workflow_events and workflow_events[0].event_time.seconds:
            start_ts = (
                workflow_events[0].event_time.seconds
                + workflow_events[0].event_time.nanos / 1e9
            )
            e2e = time.time() - start_ts
            emitter.histogram(WORKFLOW_END_TO_END_LATENCY, max(0.0, e2e) * 1e9)

    async def _respond_decision_task_completed(
        self,
        task: PollForDecisionTaskResponse,
        decision_result: DecisionResult,
        emitter: Optional[MetricsEmitter] = None,
    ) -> None:
        """
        Respond to the service that the decision task has been completed.

        Args:
            task: The original decision task
            decision_result: The result containing decisions
        """
        emitter = emitter if emitter is not None else self._metrics_emitter
        resp_start = time.monotonic()
        try:
            request = RespondDecisionTaskCompletedRequest(
                task_token=task.task_token,
                decisions=decision_result.decisions,
                identity=self._identity,
                return_new_decision_task=True,
            )

            await self._client.worker_stub.RespondDecisionTaskCompleted(request)
            emitter.counter(DECISION_TASK_COMPLETED_COUNTER)

            workflow_execution = task.workflow_execution
            logger.debug(
                "Decision task completion response sent",
                extra={
                    "workflow_type": task.workflow_type.name
                    if task.workflow_type
                    else "unknown",
                    "workflow_id": workflow_execution.workflow_id
                    if workflow_execution
                    else "unknown",
                    "run_id": workflow_execution.run_id
                    if workflow_execution
                    else "unknown",
                    "started_event_id": task.started_event_id,
                    "decisions_count": len(decision_result.decisions),
                    "return_new_decision_task": True,
                    "task_token": task.task_token[:16].hex()
                    if task.task_token
                    else None,
                },
            )

        except Exception as e:
            emitter.counter(DECISION_RESPONSE_FAILED_COUNTER)
            workflow_execution = task.workflow_execution
            logger.error(
                "Error responding to decision task completion",
                extra={
                    "workflow_type": task.workflow_type.name
                    if task.workflow_type
                    else "unknown",
                    "workflow_id": workflow_execution.workflow_id
                    if workflow_execution
                    else "unknown",
                    "run_id": workflow_execution.run_id
                    if workflow_execution
                    else "unknown",
                    "started_event_id": task.started_event_id,
                    "decisions_count": len(decision_result.decisions),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise
        finally:
            emitter.histogram(
                DECISION_RESPONSE_LATENCY, (time.monotonic() - resp_start) * 1e9
            )

    async def _respond_query_task_completed(
        self,
        task: PollForDecisionTaskResponse,
        result: WorkflowQueryResult,
    ) -> None:
        try:
            request = RespondQueryTaskCompletedRequest(
                task_token=task.task_token,
                result=result,
            )
            await self._client.worker_stub.RespondQueryTaskCompleted(request)

            logger.debug(
                "Query task completion response sent",
                extra={
                    "workflow_type": task.workflow_type.name
                    if task.workflow_type
                    else "unknown",
                    "query_type": task.query.query_type
                    if task.HasField("query")
                    else "unknown",
                    "result_type": result.result_type,
                },
            )
        except Exception as e:
            logger.error(
                "Error responding to query task completion",
                extra={
                    "workflow_type": task.workflow_type.name
                    if task.workflow_type
                    else "unknown",
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            raise

    async def _respond_query_task_failed(
        self, task: PollForDecisionTaskResponse, error_message: str
    ) -> None:
        """Respond to a legacy query task with a failure."""
        try:
            result = WorkflowQueryResult(
                result_type=QUERY_RESULT_TYPE_FAILED,
                error_message=error_message,
            )
            request = RespondQueryTaskCompletedRequest(
                task_token=task.task_token,
                result=result,
            )
            await self._client.worker_stub.RespondQueryTaskCompleted(request)
        except Exception as e:
            logger.error(
                "Error responding to query task failure",
                extra={"error_type": type(e).__name__},
                exc_info=True,
            )
            raise
