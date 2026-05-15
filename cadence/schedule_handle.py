"""ScheduleHandle: per-schedule facade for control-plane operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, cast

from cadence.api.v1 import schedule_pb2
from cadence.api.v1.common_pb2 import SearchAttributes
from cadence.api.v1.service_schedule_pb2 import (
    BackfillScheduleRequest,
    DeleteScheduleRequest,
    DescribeScheduleRequest,
    DescribeScheduleResponse,
    PauseScheduleRequest,
    UnpauseScheduleRequest,
    UpdateScheduleRequest,
)

if TYPE_CHECKING:
    from cadence.client import Client


class ScheduleHandle:
    """Per-schedule facade for control-plane operations.

    Obtain an instance via :meth:`Client.create_schedule` or
    :meth:`Client.get_schedule_handle`. The handle holds no cached state —
    each method builds its own proto request and calls the server.
    """

    def __init__(self, client: "Client", schedule_id: str) -> None:
        self._client = client
        self._schedule_id = schedule_id

    @property
    def schedule_id(self) -> str:
        return self._schedule_id

    async def describe(self) -> DescribeScheduleResponse:
        """Return the current configuration and state of the schedule."""
        return cast(
            DescribeScheduleResponse,
            await self._client.schedule_stub.DescribeSchedule(
                DescribeScheduleRequest(
                    domain=self._client.domain,
                    schedule_id=self._schedule_id,
                )
            ),
        )

    async def pause(self, *, reason: str = "", identity: str | None = None) -> None:
        """Pause the schedule, stopping new workflow starts.

        Running workflows already started by the schedule are not affected.
        ``identity`` defaults to ``client.identity`` if not supplied.
        """
        await self._client.schedule_stub.PauseSchedule(
            PauseScheduleRequest(
                domain=self._client.domain,
                schedule_id=self._schedule_id,
                reason=reason,
                identity=identity or self._client.identity,
            )
        )

    async def unpause(
        self,
        *,
        reason: str = "",
        catch_up_policy: schedule_pb2.ScheduleCatchUpPolicy = schedule_pb2.SCHEDULE_CATCH_UP_POLICY_INVALID,
    ) -> None:
        """Resume a paused schedule."""
        await self._client.schedule_stub.UnpauseSchedule(
            UnpauseScheduleRequest(
                domain=self._client.domain,
                schedule_id=self._schedule_id,
                reason=reason,
                catch_up_policy=catch_up_policy,
            )
        )

    async def delete(self) -> None:
        """Delete the schedule. Running workflows are not affected."""
        await self._client.schedule_stub.DeleteSchedule(
            DeleteScheduleRequest(
                domain=self._client.domain,
                schedule_id=self._schedule_id,
            )
        )

    async def update(
        self,
        *,
        spec: schedule_pb2.ScheduleSpec | None = None,
        action: schedule_pb2.ScheduleAction | None = None,
        policies: schedule_pb2.SchedulePolicies | None = None,
        search_attributes: SearchAttributes | None = None,
    ) -> None:
        """Update the schedule configuration.

        Only supplied fields are applied; omitted fields are left unchanged.
        Note: ``memo`` cannot be updated after creation (not in the proto).
        """
        req = UpdateScheduleRequest(
            domain=self._client.domain,
            schedule_id=self._schedule_id,
        )
        if spec is not None:
            req.spec.CopyFrom(spec)
        if action is not None:
            req.action.CopyFrom(action)
        if policies is not None:
            req.policies.CopyFrom(policies)
        if search_attributes is not None:
            req.search_attributes.CopyFrom(search_attributes)
        await self._client.schedule_stub.UpdateSchedule(req)

    async def backfill(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        overlap_policy: schedule_pb2.ScheduleOverlapPolicy = schedule_pb2.SCHEDULE_OVERLAP_POLICY_INVALID,
        backfill_id: str | None = None,
    ) -> None:
        """Trigger runs for a historical time range.

        ``backfill_id`` defaults to a UUID; the server deduplicates on this
        value so retrying with the same ID is safe.

        Raises:
            ValueError: If datetimes are naive or ``end_time <= start_time``.
        """
        if start_time.tzinfo is None:
            raise ValueError(
                "backfill start_time must be timezone-aware. "
                "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
            )
        if end_time.tzinfo is None:
            raise ValueError(
                "backfill end_time must be timezone-aware. "
                "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
            )
        if end_time <= start_time:
            raise ValueError("backfill end_time must be strictly after start_time")

        req = BackfillScheduleRequest(
            domain=self._client.domain,
            schedule_id=self._schedule_id,
            overlap_policy=overlap_policy,
            backfill_id=backfill_id or str(uuid.uuid4()),
        )
        req.start_time.FromDatetime(start_time)
        req.end_time.FromDatetime(end_time)
        await self._client.schedule_stub.BackfillSchedule(req)
