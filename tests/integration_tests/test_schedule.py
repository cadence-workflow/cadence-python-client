"""Integration tests for schedule client methods.

Requires a running Cadence server. Run with:
    uv run pytest tests/integration_tests/test_schedule.py --integration-tests -v
"""

import asyncio
import time
import uuid

import pytest
from google.protobuf import text_format

from cadence.api.v1 import common_pb2, schedule_pb2, tasklist_pb2
from cadence.api.v1.service_schedule_pb2 import DescribeScheduleResponse
from cadence.client import Client
from cadence.error import QueryFailedError
from tests.integration_tests.helper import CadenceHelper


def _dummy_schedule_action() -> schedule_pb2.ScheduleAction:
    """Cadence rejects CreateSchedule without Action.start_workflow set."""
    return schedule_pb2.ScheduleAction(
        start_workflow=schedule_pb2.ScheduleAction.StartWorkflowAction(
            workflow_type=common_pb2.WorkflowType(
                name="ScheduleIntegrationDummyWorkflow"
            ),
            task_list=tasklist_pb2.TaskList(name="schedule-integration-task-list"),
        )
    )


async def _describe_schedule_when_ready(
    client: Client,
    schedule_id: str,
    *,
    timeout_s: float = 90.0,
) -> DescribeScheduleResponse:
    """DescribeSchedule is backed by a query; the schedule workflow may not be queryable immediately."""
    deadline = time.monotonic() + timeout_s
    backoff = 0.25
    last_err: QueryFailedError | None = None
    while time.monotonic() < deadline:
        try:
            return await client.describe_schedule(schedule_id)
        except QueryFailedError as exc:
            msg = str(exc.args[0]) if exc.args else ""
            if "decision task" in msg or "queried" in msg.lower():
                last_err = exc
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 2.0)
                continue
            raise
    assert last_err is not None
    raise last_err


def _assert_describe_spec_and_action(
    resp: DescribeScheduleResponse,
    expected_spec: schedule_pb2.ScheduleSpec,
    expected_action: schedule_pb2.ScheduleAction,
) -> None:
    """Assert describe returns the same schedule config we stored (full proto equality)."""
    if resp.spec != expected_spec:
        raise AssertionError(
            "DescribeSchedule spec mismatch:\n"
            f"--- expected ---\n{text_format.MessageToString(expected_spec)}\n"
            f"--- got ---\n{text_format.MessageToString(resp.spec)}"
        )
    if resp.action != expected_action:
        raise AssertionError(
            "DescribeSchedule action mismatch:\n"
            f"--- expected ---\n{text_format.MessageToString(expected_action)}\n"
            f"--- got ---\n{text_format.MessageToString(resp.action)}"
        )


@pytest.mark.usefixtures("helper")
async def test_create_describe_delete(helper: CadenceHelper):
    """Create a schedule, describe it to verify spec round-trips, then delete it."""
    schedule_id = f"test-schedule-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            expected_spec = schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *")
            expected_action = _dummy_schedule_action()
            await client.create_schedule(
                schedule_id,
                spec=expected_spec,
                action=expected_action,
            )

            resp = await _describe_schedule_when_ready(client, schedule_id)
            _assert_describe_spec_and_action(resp, expected_spec, expected_action)
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
async def test_pause_and_unpause(helper: CadenceHelper):
    """Pause a schedule and verify state.paused, then unpause and verify cleared."""
    schedule_id = f"test-schedule-pause-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 10 * * *"),
                action=_dummy_schedule_action(),
            )

            await client.pause_schedule(schedule_id, reason="integration-test")
            paused_resp = await _describe_schedule_when_ready(client, schedule_id)
            assert paused_resp.state.paused

            await client.unpause_schedule(schedule_id, reason="done")
            resumed_resp = await _describe_schedule_when_ready(client, schedule_id)
            assert not resumed_resp.state.paused
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
async def test_update_spec(helper: CadenceHelper):
    """Update a schedule's cron expression and verify describe reflects the change."""
    schedule_id = f"test-schedule-update-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            expected_action = _dummy_schedule_action()
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
                action=expected_action,
            )

            updated_spec = schedule_pb2.ScheduleSpec(cron_expression="0 18 * * *")
            await client.update_schedule(
                schedule_id,
                spec=updated_spec,
            )

            resp = await _describe_schedule_when_ready(client, schedule_id)
            _assert_describe_spec_and_action(resp, updated_spec, expected_action)
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
async def test_list_schedules_contains_created(helper: CadenceHelper):
    """A created schedule appears in list_schedules() results."""
    schedule_id = f"test-schedule-list-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 11 * * *"),
                action=_dummy_schedule_action(),
            )

            ids = [e.schedule_id async for e in client.list_schedules()]
            assert schedule_id in ids
        finally:
            await client.delete_schedule(schedule_id)
