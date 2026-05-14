import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Optional

from cadence._internal.workflow.history_event_iterator import iterate_history_events
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
from cadence.worker._base_task_handler import BaseTaskHandler
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
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

        Supports two paths:
        1. Query task: task.query is set → replay history, execute query,
           respond with RespondQueryTaskCompleted.
        2. Normal decision task: process decisions normally.

        Args:
            task: The decision task to handle
        """
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

        # Fetch full workflow history
        # TODO sticky cache
        workflow_events = [
            event async for event in iterate_history_events(task, self._client)
        ]

        workflow_info = WorkflowInfo(
            workflow_type=workflow_type_name,
            workflow_domain=self._client.domain,
            workflow_id=workflow_id,
            workflow_run_id=run_id,
            workflow_task_list=self.task_list,
            data_converter=self._client.data_converter,
        )

        workflow_engine = WorkflowEngine(
            info=workflow_info,
            workflow_definition=workflow_definition,
        )

        decision_result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            workflow_engine.process_decision,
            workflow_events,
            task.query if is_query_task else None,
        )
        if is_query_task:
            if not decision_result.query_result:
                raise ValueError("Query result is empty")
            await self._respond_query_task_completed(task, decision_result.query_result)
        else:
            await self._respond_decision_task_completed(task, decision_result)

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

        # For query tasks, respond with a query failure instead of decision failure
        if task.HasField("query"):
            await self._respond_query_task_failed(task, str(error))
            return

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

    async def _respond_decision_task_completed(
        self, task: PollForDecisionTaskResponse, decision_result: DecisionResult
    ) -> None:
        """
        Respond to the service that the decision task has been completed.

        Args:
            task: The original decision task
            decision_result: The result containing decisions
        """
        try:
            request = RespondDecisionTaskCompletedRequest(
                task_token=task.task_token,
                decisions=decision_result.decisions,
                identity=self._identity,
                return_new_decision_task=True,
            )

            await self._client.worker_stub.RespondDecisionTaskCompleted(request)

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

    async def _respond_query_task_completed(
        self, task: PollForDecisionTaskResponse, result: WorkflowQueryResult
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
