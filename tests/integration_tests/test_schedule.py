"""Integration tests for schedule client methods.

Requires a running Cadence server. Run with:
    uv run pytest tests/integration_tests/test_schedule.py --integration-tests -v
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from google.protobuf import text_format
from google.protobuf.duration_pb2 import Duration as PbDuration

from cadence.api.v1 import common_pb2, schedule_pb2, tasklist_pb2
from cadence.api.v1.service_schedule_pb2 import DescribeScheduleResponse
from cadence.error import QueryFailedError
from tests.integration_tests.helper import CadenceHelper


def _make_duration(td: timedelta) -> PbDuration:
    d = PbDuration()
    d.FromTimedelta(td)
    return d


def _make_schedule_action() -> schedule_pb2.ScheduleAction:
    """Build a minimal ScheduleAction required by CreateSchedule."""
    return schedule_pb2.ScheduleAction(
        start_workflow=schedule_pb2.ScheduleAction.StartWorkflowAction(
            workflow_type=common_pb2.WorkflowType(
                name="ScheduleIntegrationDummyWorkflow"
            ),
            task_list=tasklist_pb2.TaskList(name="schedule-integration-task-list"),
            execution_start_to_close_timeout=_make_duration(timedelta(hours=1)),
            task_start_to_close_timeout=_make_duration(timedelta(seconds=10)),
        )
    )


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
            expected_action = _make_schedule_action()
            await client.create_schedule(
                schedule_id,
                spec=expected_spec,
                action=expected_action,
            )

            resp = await client.describe_schedule(schedule_id)
            _assert_describe_spec_and_action(resp, expected_spec, expected_action)
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
@pytest.mark.skip(
    reason="skip this test because it is not working as expected, see https://github.com/cadence-workflow/cadence-python-client/issues/117"
)
async def test_pause_and_unpause(helper: CadenceHelper):
    """Pause a schedule and verify state.paused, then unpause and verify cleared."""
    schedule_id = f"test-schedule-pause-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 10 * * *"),
                action=_make_schedule_action(),
            )

            await client.pause_schedule(schedule_id, reason="integration-test")
            paused_resp = await client.describe_schedule(schedule_id)
            assert paused_resp.state.paused

            await client.unpause_schedule(schedule_id, reason="done")
            resumed_resp = await client.describe_schedule(schedule_id)
            assert not resumed_resp.state.paused
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
@pytest.mark.skip(
    reason="skip this test because it is not working as expected, see https://github.com/cadence-workflow/cadence-python-client/issues/117"
)
async def test_update_spec(helper: CadenceHelper):
    """Update a schedule's cron expression and verify describe reflects the change."""
    schedule_id = f"test-schedule-update-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            expected_action = _make_schedule_action()
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

            resp = await client.describe_schedule(schedule_id)
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
                action=_make_schedule_action(),
            )

            ids = [e.schedule_id async for e in client.list_schedules()]
            assert schedule_id in ids
        finally:
            await client.delete_schedule(schedule_id)


@pytest.mark.usefixtures("helper")
async def test_backfill(helper: CadenceHelper):
    """Backfill starts workflow executions for past schedule slots."""
    schedule_id = f"test-schedule-backfill-{uuid.uuid4()}"

    async with helper.client() as client:
        try:
            # Use a yearly cron so no automatic tick can fire during the ~30s
            # poll window and give a false-positive on total_runs.
            await client.create_schedule(
                schedule_id,
                spec=schedule_pb2.ScheduleSpec(cron_expression="0 0 1 1 *"),
                action=_make_schedule_action(),
            )

            now = datetime.now(timezone.utc)
            await client.backfill_schedule(
                schedule_id,
                start_time=now - timedelta(minutes=3),
                end_time=now - timedelta(minutes=1),
            )

            # The scheduler processes the backfill signal asynchronously.
            # Poll until total_runs reflects at least one triggered workflow start.
            deadline = time.monotonic() + 30.0
            resp = None
            while time.monotonic() < deadline:
                try:
                    resp = await client.describe_schedule(schedule_id)
                    if resp.info.total_runs >= 1:
                        break
                except QueryFailedError:
                    pass
                await asyncio.sleep(0.5)

            assert resp is not None, "describe_schedule never succeeded within 30s"
            assert resp.info.total_runs >= 1, (
                f"expected at least one backfilled run, got total_runs={resp.info.total_runs}"
            )
        finally:
            await client.delete_schedule(schedule_id)
