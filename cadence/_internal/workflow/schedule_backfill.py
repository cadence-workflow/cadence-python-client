"""Validate Backfill TypedDict inputs for BackfillSchedule requests."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, cast

from cadence.schedule import Backfill


def validate_backfill(backfill: Backfill | Mapping[str, object]) -> None:
    """Validate a Backfill before sending a BackfillSchedule RPC.

    The full proto request (including domain and schedule_id) is built by the
    client method in PR 5. This function validates only the user-supplied fields.

    Raises:
        ValueError: If start_time or end_time are missing, naive, or end_time
            is not strictly after start_time.
    """
    start = backfill.get("start_time")
    end = backfill.get("end_time")

    if start is None:
        raise ValueError("Backfill.start_time is required")
    if end is None:
        raise ValueError("Backfill.end_time is required")

    start_dt = cast(datetime, start)
    end_dt = cast(datetime, end)

    if start_dt.tzinfo is None:
        raise ValueError(
            "Backfill.start_time must be timezone-aware. "
            "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
        )
    if end_dt.tzinfo is None:
        raise ValueError(
            "Backfill.end_time must be timezone-aware. "
            "Use datetime.now(timezone.utc) or datetime(..., tzinfo=timezone.utc)"
        )
    if end_dt <= start_dt:
        raise ValueError("Backfill.end_time must be strictly after start_time")
