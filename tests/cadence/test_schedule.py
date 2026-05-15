"""Unit tests for schedule client methods."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
import grpc.aio
import pytest

from cadence.api.v1 import schedule_pb2
from cadence.api.v1.service_schedule_pb2 import (
    BackfillScheduleRequest,
    BackfillScheduleResponse,
    CreateScheduleRequest,
    CreateScheduleResponse,
    DeleteScheduleRequest,
    DeleteScheduleResponse,
    DescribeScheduleRequest,
    DescribeScheduleResponse,
    ListSchedulesRequest,
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

    async def CreateSchedule(self, request, context):
        self.last_create = request
        return CreateScheduleResponse(schedule_id=request.schedule_id)

    async def DescribeSchedule(self, request, context):
        self.last_describe = request
        return DescribeScheduleResponse(
            spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
        )

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


class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_returns_response(self, client, servicer):
        resp = await client.create_schedule(
            "my-schedule",
            spec=schedule_pb2.ScheduleSpec(cron_expression="0 9 * * *"),
        )
        assert isinstance(resp, CreateScheduleResponse)
        assert resp.schedule_id == "my-schedule"

    @pytest.mark.asyncio
    async def test_request_fields(self, client, servicer):
        spec = schedule_pb2.ScheduleSpec(cron_expression="0 6 * * 1")
        await client.create_schedule("sched-1", spec=spec)
        req = servicer.last_create
        assert req.domain == "test-domain"
        assert req.schedule_id == "sched-1"
        assert req.spec.cron_expression == "0 6 * * 1"

    @pytest.mark.asyncio
    async def test_none_fields_not_sent(self, client, servicer):
        await client.create_schedule("sched-2")
        req = servicer.last_create
        assert not req.HasField("spec")
        assert not req.HasField("action")
        assert not req.HasField("policies")


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
        new_spec = schedule_pb2.ScheduleSpec(cron_expression="0 12 * * *")
        await client.update_schedule("sched-upd", spec=new_spec)
        assert servicer.last_update.spec.cron_expression == "0 12 * * *"

    @pytest.mark.asyncio
    async def test_update_no_fields_sends_empty(self, client, servicer):
        await client.update_schedule("sched-upd")
        assert not servicer.last_update.HasField("spec")


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
            await client.backfill_schedule(
                "sched-bf", datetime(2025, 1, 1), self._T1
            )

    @pytest.mark.asyncio
    async def test_naive_end_raises(self, client):
        with pytest.raises(ValueError, match="end_time must be timezone-aware"):
            await client.backfill_schedule(
                "sched-bf", self._T0, datetime(2025, 1, 2)
            )

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
