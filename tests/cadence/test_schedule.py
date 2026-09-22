"""Unit tests for schedule client methods."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc.aio
import pytest

from google.protobuf.duration_pb2 import Duration

from cadence.api.v1 import schedule_pb2
from cadence.api.v1.common_pb2 import WorkflowType
from cadence.api.v1.tasklist_pb2 import TaskList
from cadence.api.v1.service_schedule_pb2 import (
    BackfillScheduleRequest,
    BackfillScheduleResponse,
    CreateScheduleRequest,
    CreateScheduleResponse,
    DeleteScheduleRequest,
    DeleteScheduleResponse,
    DescribeScheduleRequest,
    DescribeScheduleResponse,
    ListSchedulesResponse,
    PauseScheduleRequest,
    PauseScheduleResponse,
    UnpauseScheduleRequest,
    UnpauseScheduleResponse,
    UpdateScheduleRequest,
    UpdateScheduleResponse,
)
from cadence.api.v1.service_schedule_pb2_grpc import (
    ScheduleAPIServicer,
    add_ScheduleAPIServicer_to_server,
)
from cadence.client import Client


class _FakeScheduleServicer(ScheduleAPIServicer):
    """Records the last request received for each RPC so tests can inspect it."""

    def __init__(self) -> None:
        self.last_create: CreateScheduleRequest | None = None
        self.last_describe: DescribeScheduleRequest | None = None
        self.last_pause: PauseScheduleRequest | None = None
        self.last_unpause: UnpauseScheduleRequest | None = None
        self.last_delete: DeleteScheduleRequest | None = None
        self.last_update: UpdateScheduleRequest | None = None
        self.last_backfill: BackfillScheduleRequest | None = None
        self.list_pages: list[ListSchedulesResponse] = []
        self._list_call_count = 0
        self.describe_response: DescribeScheduleResponse = DescribeScheduleResponse(
            spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
        )

    async def CreateSchedule(self, request, context):
        self.last_create = request
        return CreateScheduleResponse(schedule_id=request.schedule_id)

    async def DescribeSchedule(self, request, context):
        self.last_describe = request
        return self.describe_response

    async def PauseSchedule(self, request, context):
        self.last_pause = request
        return PauseScheduleResponse()

    async def UnpauseSchedule(self, request, context):
        self.last_unpause = request
        return UnpauseScheduleResponse()

    async def DeleteSchedule(self, request, context):
        self.last_delete = request
        return DeleteScheduleResponse()

    async def UpdateSchedule(self, request, context):
        self.last_update = request
        return UpdateScheduleResponse()

    async def BackfillSchedule(self, request, context):
        self.last_backfill = request
        return BackfillScheduleResponse()

    async def ListSchedules(self, request, context):
        self.last_list = request
        if self._list_call_count < len(self.list_pages):
            page = self.list_pages[self._list_call_count]
        else:
            page = ListSchedulesResponse()
        self._list_call_count += 1
        return page


@pytest.fixture()
def servicer():
    return _FakeScheduleServicer()


@pytest.fixture()
async def schedule_server(servicer):
    server = grpc.aio.server()
    add_ScheduleAPIServicer_to_server(servicer, server)
    port = server.add_insecure_port("localhost:0")
    await server.start()
    yield port
    await server.stop(grace=0)


@pytest.fixture()
async def client(schedule_server):
    c = Client(domain="test-domain", target=f"localhost:{schedule_server}")
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# create_schedule
# ---------------------------------------------------------------------------


def _spec(cron: str = "0 9 * * *") -> schedule_pb2.ScheduleSpec:
    return schedule_pb2.ScheduleSpec(cron_expression=cron)


def _start_workflow_action(
    *,
    workflow_type: str | None = "MyWorkflow",
    task_list: str | None = "my-task-list",
    execution_timeout_seconds: int | None = 3600,
    decision_timeout_seconds: int | None = 30,
) -> schedule_pb2.ScheduleAction:
    """Build a ScheduleAction, omitting any field whose argument is None."""
    start = schedule_pb2.ScheduleAction.StartWorkflowAction()
    if workflow_type is not None:
        start.workflow_type.CopyFrom(WorkflowType(name=workflow_type))
    if task_list is not None:
        start.task_list.CopyFrom(TaskList(name=task_list))
    if execution_timeout_seconds is not None:
        start.execution_start_to_close_timeout.CopyFrom(
            Duration(seconds=execution_timeout_seconds)
        )
    if decision_timeout_seconds is not None:
        start.task_start_to_close_timeout.CopyFrom(
            Duration(seconds=decision_timeout_seconds)
        )
    return schedule_pb2.ScheduleAction(start_workflow=start)


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_returns_response(self, client, servicer):
        resp = await client.create_schedule(
            "my-schedule", spec=_spec(), action=_start_workflow_action()
        )
        assert isinstance(resp, CreateScheduleResponse)
        assert resp.schedule_id == "my-schedule"

    @pytest.mark.asyncio
    async def test_request_fields(self, client, servicer):
        await client.create_schedule(
            "sched-1", spec=_spec("0 6 * * 1"), action=_start_workflow_action()
        )
        req = servicer.last_create
        assert req.domain == "test-domain"
        assert req.schedule_id == "sched-1"
        assert req.spec.cron_expression == "0 6 * * 1"
        assert req.action.start_workflow.workflow_type.name == "MyWorkflow"

    @pytest.mark.asyncio
    async def test_optional_fields_not_sent(self, client, servicer):
        await client.create_schedule(
            "sched-2", spec=_spec(), action=_start_workflow_action()
        )
        req = servicer.last_create
        # Optional fields left unset are not sent.
        assert not req.HasField("policies")
        assert not req.HasField("memo")
        assert not req.HasField("search_attributes")
        assert not req.HasField("state")

    @pytest.mark.asyncio
    async def test_empty_schedule_id_raises(self, client, servicer):
        with pytest.raises(ValueError, match="schedule_id"):
            await client.create_schedule(
                "", spec=_spec(), action=_start_workflow_action()
            )
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_missing_spec_raises(self, client, servicer):
        with pytest.raises(ValueError, match="cron_expression"):
            await client.create_schedule("sched-2", action=_start_workflow_action())
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_empty_cron_raises(self, client, servicer):
        with pytest.raises(ValueError, match="cron_expression"):
            await client.create_schedule(
                "sched-2", spec=_spec(cron=""), action=_start_workflow_action()
            )
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_missing_action_raises(self, client, servicer):
        with pytest.raises(ValueError, match="action is required"):
            await client.create_schedule("sched-2", spec=_spec())
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_create_with_initial_paused_state(self, client, servicer):
        state = schedule_pb2.ScheduleState(
            paused=True,
            pause_info=schedule_pb2.SchedulePauseInfo(
                reason="deploying", paused_by="ci"
            ),
        )
        await client.create_schedule(
            "sched-3", spec=_spec(), action=_start_workflow_action(), state=state
        )
        req = servicer.last_create
        assert req.HasField("state")
        assert req.state.paused is True
        assert req.state.pause_info.reason == "deploying"
        assert req.state.pause_info.paused_by == "ci"

    @pytest.mark.asyncio
    async def test_create_paused_no_pause_info(self, client, servicer):
        state = schedule_pb2.ScheduleState(paused=True)
        await client.create_schedule(
            "sched-4", spec=_spec(), action=_start_workflow_action(), state=state
        )
        req = servicer.last_create
        assert req.HasField("state")
        assert req.state.paused is True
        assert not req.state.HasField("pause_info")


class TestCreateScheduleActionValidation:
    @pytest.mark.asyncio
    async def test_valid_action_passed_through(self, client, servicer):
        action = _start_workflow_action(decision_timeout_seconds=45)
        await client.create_schedule("sched-a", spec=_spec(), action=action)
        req = servicer.last_create
        assert req.HasField("action")
        sw = req.action.start_workflow
        assert sw.workflow_type.name == "MyWorkflow"
        assert sw.task_list.name == "my-task-list"
        assert sw.execution_start_to_close_timeout.seconds == 3600
        assert sw.task_start_to_close_timeout.seconds == 45

    @pytest.mark.asyncio
    async def test_decision_timeout_defaulted_when_unset(self, client, servicer):
        action = _start_workflow_action(decision_timeout_seconds=None)
        await client.create_schedule("sched-b", spec=_spec(), action=action)
        sw = servicer.last_create.action.start_workflow
        assert sw.task_start_to_close_timeout.seconds == 10
        assert sw.task_start_to_close_timeout.nanos == 0

    @pytest.mark.asyncio
    async def test_caller_action_not_mutated_by_default(self, client, servicer):
        action = _start_workflow_action(decision_timeout_seconds=None)
        await client.create_schedule("sched-c", spec=_spec(), action=action)
        # The default is applied to the request copy, not the caller's object.
        assert not action.start_workflow.HasField("task_start_to_close_timeout")

    @pytest.mark.asyncio
    async def test_missing_workflow_type_raises(self, client, servicer):
        action = _start_workflow_action(workflow_type=None)
        with pytest.raises(ValueError, match="workflow_type"):
            await client.create_schedule("sched-d", spec=_spec(), action=action)
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_missing_task_list_raises(self, client, servicer):
        action = _start_workflow_action(task_list=None)
        with pytest.raises(ValueError, match="task_list"):
            await client.create_schedule("sched-e", spec=_spec(), action=action)
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_missing_execution_timeout_raises(self, client, servicer):
        action = _start_workflow_action(execution_timeout_seconds=None)
        with pytest.raises(ValueError, match="execution_start_to_close_timeout"):
            await client.create_schedule("sched-f", spec=_spec(), action=action)
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_nonpositive_execution_timeout_raises(self, client, servicer):
        action = _start_workflow_action(execution_timeout_seconds=0)
        with pytest.raises(ValueError, match="execution_start_to_close_timeout"):
            await client.create_schedule("sched-g", spec=_spec(), action=action)
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_negative_decision_timeout_raises(self, client, servicer):
        action = _start_workflow_action()
        action.start_workflow.task_start_to_close_timeout.CopyFrom(Duration(seconds=-1))
        with pytest.raises(ValueError, match="must not be negative"):
            await client.create_schedule("sched-h", spec=_spec(), action=action)
        assert servicer.last_create is None

    @pytest.mark.asyncio
    async def test_action_without_start_workflow_raises(self, client, servicer):
        with pytest.raises(ValueError, match="start_workflow"):
            await client.create_schedule(
                "sched-i", spec=_spec(), action=schedule_pb2.ScheduleAction()
            )
        assert servicer.last_create is None


# ---------------------------------------------------------------------------
# describe_schedule
# ---------------------------------------------------------------------------


class TestDescribeSchedule:
    @pytest.mark.asyncio
    async def test_calls_describe(self, client, servicer):
        resp = await client.describe_schedule("sched-x")
        assert servicer.last_describe.schedule_id == "sched-x"
        assert servicer.last_describe.domain == "test-domain"
        assert resp.spec.cron_expression == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_returns_queue_state(self, client, servicer):
        servicer.describe_response = DescribeScheduleResponse(
            info=schedule_pb2.ScheduleInfo(
                buffered_fire_count=3,
                running_workflow_count=2,
            ),
        )
        resp = await client.describe_schedule("sched-x")
        assert resp.info.buffered_fire_count == 3
        assert resp.info.running_workflow_count == 2


# ---------------------------------------------------------------------------
# pause_schedule / unpause_schedule
# ---------------------------------------------------------------------------


class TestPauseSchedule:
    @pytest.mark.asyncio
    async def test_pause_sends_reason(self, client, servicer):
        await client.pause_schedule("sched-p", reason="maintenance")
        assert servicer.last_pause.schedule_id == "sched-p"
        assert servicer.last_pause.reason == "maintenance"

    @pytest.mark.asyncio
    async def test_pause_defaults_identity(self, client, servicer):
        await client.pause_schedule("sched-p")
        assert servicer.last_pause.identity == client.identity

    @pytest.mark.asyncio
    async def test_pause_custom_identity(self, client, servicer):
        await client.pause_schedule("sched-p", identity="ops-bot")
        assert servicer.last_pause.identity == "ops-bot"


class TestUnpauseSchedule:
    @pytest.mark.asyncio
    async def test_unpause_sends_reason(self, client, servicer):
        await client.unpause_schedule("sched-u", reason="resolved")
        assert servicer.last_unpause.schedule_id == "sched-u"
        assert servicer.last_unpause.reason == "resolved"

    @pytest.mark.asyncio
    async def test_unpause_catch_up_policy(self, client, servicer):
        await client.unpause_schedule(
            "sched-u",
            catch_up_policy=schedule_pb2.SCHEDULE_CATCH_UP_POLICY_ONE,
        )
        assert (
            servicer.last_unpause.catch_up_policy
            == schedule_pb2.SCHEDULE_CATCH_UP_POLICY_ONE
        )


# ---------------------------------------------------------------------------
# delete_schedule
# ---------------------------------------------------------------------------


class TestDeleteSchedule:
    @pytest.mark.asyncio
    async def test_delete(self, client, servicer):
        await client.delete_schedule("sched-d")
        assert servicer.last_delete.schedule_id == "sched-d"
        assert servicer.last_delete.domain == "test-domain"


# ---------------------------------------------------------------------------
# update_schedule
# ---------------------------------------------------------------------------


class TestUpdateSchedule:
    @pytest.mark.asyncio
    async def test_update_spec(self, client, servicer):
        """A changed spec is sent; domain/schedule_id are always populated."""
        new_spec = schedule_pb2.ScheduleSpec(cron_expression="0 12 * * *")
        await client.update_schedule("sched-upd", lambda d: d.spec.CopyFrom(new_spec))
        assert servicer.last_update.spec.cron_expression == "0 12 * * *"
        assert servicer.last_update.domain == "test-domain"
        assert servicer.last_update.schedule_id == "sched-upd"

    @pytest.mark.asyncio
    async def test_update_omits_unmodified_fields(self, client, servicer):
        """Fields the updater doesn't change are omitted so the server preserves them."""
        original_action = schedule_pb2.ScheduleAction(
            start_workflow=schedule_pb2.ScheduleAction.StartWorkflowAction(
                workflow_type=WorkflowType(name="my-workflow"),
            )
        )
        servicer.describe_response = DescribeScheduleResponse(
            spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
            action=original_action,
            policies=schedule_pb2.SchedulePolicies(
                overlap_policy=schedule_pb2.SCHEDULE_OVERLAP_POLICY_SKIP_NEW,
            ),
        )
        new_spec = schedule_pb2.ScheduleSpec(cron_expression="0 18 * * *")
        await client.update_schedule("sched-upd", lambda d: d.spec.CopyFrom(new_spec))
        # Only the changed field is sent; unchanged action/policies are omitted.
        assert servicer.last_update.spec.cron_expression == "0 18 * * *"
        assert not servicer.last_update.HasField("action")
        assert not servicer.last_update.HasField("policies")

    @pytest.mark.asyncio
    async def test_update_noop_sends_no_rpc(self, client, servicer):
        """An updater that changes nothing issues no UpdateSchedule RPC."""
        await client.update_schedule("sched-upd", lambda d: None)
        assert servicer.last_update is None

    @pytest.mark.asyncio
    async def test_update_only_changed_field_sent(self, client, servicer):
        """Changing policies sends policies but not the untouched spec."""
        servicer.describe_response = DescribeScheduleResponse(
            spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
            policies=schedule_pb2.SchedulePolicies(
                overlap_policy=schedule_pb2.SCHEDULE_OVERLAP_POLICY_SKIP_NEW,
            ),
        )

        def _mutate(d):
            d.policies.overlap_policy = schedule_pb2.SCHEDULE_OVERLAP_POLICY_BUFFER

        await client.update_schedule("sched-upd", _mutate)
        assert servicer.last_update.HasField("policies")
        assert (
            servicer.last_update.policies.overlap_policy
            == schedule_pb2.SCHEDULE_OVERLAP_POLICY_BUFFER
        )
        assert not servicer.last_update.HasField("spec")

    @pytest.mark.asyncio
    async def test_update_empty_cron_raises(self, client, servicer):
        """Changing spec to an empty cron expression is rejected."""

        def _mutate(d):
            d.spec.CopyFrom(schedule_pb2.ScheduleSpec(cron_expression=""))
            d.spec.jitter.seconds = 5  # force a diff without a cron

        with pytest.raises(ValueError, match="cron_expression"):
            await client.update_schedule("sched-upd", _mutate)
        assert servicer.last_update is None

    @pytest.mark.asyncio
    async def test_update_action_validated_and_defaulted(self, client, servicer):
        """A changed action is validated and its decision timeout defaulted."""

        def _mutate(d):
            d.action.CopyFrom(_start_workflow_action(decision_timeout_seconds=None))

        await client.update_schedule("sched-upd", _mutate)
        sw = servicer.last_update.action.start_workflow
        assert sw.workflow_type.name == "MyWorkflow"
        assert sw.task_start_to_close_timeout.seconds == 10

    @pytest.mark.asyncio
    async def test_update_invalid_action_raises(self, client, servicer):
        """A changed action missing a required field is rejected before the RPC."""

        def _mutate(d):
            d.action.CopyFrom(_start_workflow_action(task_list=None))

        with pytest.raises(ValueError, match="task_list"):
            await client.update_schedule("sched-upd", _mutate)
        assert servicer.last_update is None


# ---------------------------------------------------------------------------
# backfill_schedule
# ---------------------------------------------------------------------------


class TestBackfillSchedule:
    _T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _T1 = datetime(2025, 1, 2, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_backfill_sends_request(self, client, servicer):
        await client.backfill_schedule("sched-bf", self._T0, self._T1)
        req = servicer.last_backfill
        assert req.schedule_id == "sched-bf"
        assert req.backfill_id  # UUID generated

    @pytest.mark.asyncio
    async def test_backfill_custom_id(self, client, servicer):
        await client.backfill_schedule(
            "sched-bf", self._T0, self._T1, backfill_id="fixed-id"
        )
        assert servicer.last_backfill.backfill_id == "fixed-id"

    @pytest.mark.asyncio
    async def test_naive_start_raises(self, client):
        with pytest.raises(ValueError, match="start_time must be timezone-aware"):
            await client.backfill_schedule("sched-bf", datetime(2025, 1, 1), self._T1)

    @pytest.mark.asyncio
    async def test_naive_end_raises(self, client):
        with pytest.raises(ValueError, match="end_time must be timezone-aware"):
            await client.backfill_schedule("sched-bf", self._T0, datetime(2025, 1, 2))

    @pytest.mark.asyncio
    async def test_end_before_start_raises(self, client):
        with pytest.raises(ValueError, match="end_time must be strictly after"):
            await client.backfill_schedule("sched-bf", self._T1, self._T0)

    @pytest.mark.asyncio
    async def test_equal_times_raises(self, client):
        with pytest.raises(ValueError, match="end_time must be strictly after"):
            await client.backfill_schedule("sched-bf", self._T0, self._T0)


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


class TestListSchedules:
    @pytest.mark.asyncio
    async def test_single_page(self, client, servicer):
        servicer.list_pages = [
            ListSchedulesResponse(
                schedules=[
                    schedule_pb2.ScheduleListEntry(
                        schedule_id="s1", cron_expression="0 9 * * *"
                    ),
                    schedule_pb2.ScheduleListEntry(schedule_id="s2"),
                ],
                next_page_token=b"",
            )
        ]
        results = [e async for e in client.list_schedules()]
        assert len(results) == 2
        assert results[0].schedule_id == "s1"
        assert results[1].schedule_id == "s2"

    @pytest.mark.asyncio
    async def test_pagination(self, client, servicer):
        servicer.list_pages = [
            ListSchedulesResponse(
                schedules=[schedule_pb2.ScheduleListEntry(schedule_id="s1")],
                next_page_token=b"token1",
            ),
            ListSchedulesResponse(
                schedules=[schedule_pb2.ScheduleListEntry(schedule_id="s2")],
                next_page_token=b"",
            ),
        ]
        results = [e async for e in client.list_schedules()]
        assert len(results) == 2
        assert results[0].schedule_id == "s1"
        assert results[1].schedule_id == "s2"

    @pytest.mark.asyncio
    async def test_empty_domain(self, client, servicer):
        servicer.list_pages = [ListSchedulesResponse()]
        results = [e async for e in client.list_schedules()]
        assert results == []
