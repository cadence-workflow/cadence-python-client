"""Convert ScheduleAction TypedDict to/from protobuf."""

from __future__ import annotations

from datetime import timedelta

from cadence.api.v1 import schedule_pb2
from cadence.api.v1.common_pb2 import WorkflowType
from cadence.api.v1.tasklist_pb2 import TaskList
from cadence._internal.workflow.retry_policy import _set_duration_field, retry_policy_to_proto
from cadence.data_converter import DataConverter
from cadence.schedule import ScheduleAction, StartWorkflowAction


def schedule_action_to_proto(
    action: ScheduleAction,
    data_converter: DataConverter,
) -> schedule_pb2.ScheduleAction:
    """Convert a ScheduleAction TypedDict to protobuf.

    Raises:
        ValueError: If action is empty, start_workflow is missing, or required
            fields within start_workflow are absent.
    """
    if not action or "start_workflow" not in action:
        raise ValueError(
            "ScheduleAction must have exactly one action field set "
            "(only 'start_workflow' is supported today)"
        )

    swa: StartWorkflowAction = action["start_workflow"]

    if not swa.get("workflow_type"):
        raise ValueError("StartWorkflowAction.workflow_type is required")
    if not swa.get("task_list"):
        raise ValueError("StartWorkflowAction.task_list is required")
    if not swa.get("execution_start_to_close_timeout"):
        raise ValueError(
            "StartWorkflowAction.execution_start_to_close_timeout is required"
        )

    proto_swa = schedule_pb2.ScheduleAction.StartWorkflowAction(
        workflow_type=WorkflowType(name=swa["workflow_type"]),
        task_list=TaskList(name=swa["task_list"]),
        workflow_id_prefix=swa.get("workflow_id_prefix", ""),
    )

    _set_duration_field(
        proto_swa.execution_start_to_close_timeout,
        swa["execution_start_to_close_timeout"],
    )

    task_timeout = swa.get("task_start_to_close_timeout", timedelta(seconds=10))
    _set_duration_field(proto_swa.task_start_to_close_timeout, task_timeout)

    args = swa.get("args")
    if args:
        try:
            input_payload = data_converter.to_data(list(args))
            proto_swa.input.CopyFrom(input_payload)
        except Exception as e:
            raise ValueError(f"Failed to encode StartWorkflowAction.args: {e}") from e

    retry_proto = retry_policy_to_proto(swa.get("retry_policy"))
    if retry_proto is not None:
        proto_swa.retry_policy.CopyFrom(retry_proto)

    return schedule_pb2.ScheduleAction(start_workflow=proto_swa)


def schedule_action_from_proto(proto: schedule_pb2.ScheduleAction) -> ScheduleAction:
    """Convert a protobuf ScheduleAction to a ScheduleAction TypedDict.

    Note: StartWorkflowAction.args are encoded bytes and cannot be decoded
    without a DataConverter; the ``args`` key will be absent in the result.
    """
    if not proto.HasField("start_workflow"):
        raise ValueError("ScheduleAction proto has no start_workflow field set")

    swa = proto.start_workflow
    start_workflow: StartWorkflowAction = {
        "workflow_type": swa.workflow_type.name,
        "task_list": swa.task_list.name,
    }

    if swa.workflow_id_prefix:
        start_workflow["workflow_id_prefix"] = swa.workflow_id_prefix

    if swa.HasField("execution_start_to_close_timeout"):
        start_workflow["execution_start_to_close_timeout"] = (
            swa.execution_start_to_close_timeout.ToTimedelta()
        )

    if swa.HasField("task_start_to_close_timeout"):
        start_workflow["task_start_to_close_timeout"] = (
            swa.task_start_to_close_timeout.ToTimedelta()
        )

    return ScheduleAction(start_workflow=start_workflow)
