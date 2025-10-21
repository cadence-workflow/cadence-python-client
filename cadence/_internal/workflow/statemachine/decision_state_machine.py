from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol, TypeVar, Optional

from cadence.api.v1 import (
    decision_pb2 as decision,
)


class DecisionState(Enum):
    """Lifecycle states for a decision-producing state machine instance."""

    CREATED = 0
    DECISION_SENT = 1
    CANCELED_BEFORE_INITIATED = 2
    INITIATED = 3
    STARTED = 4
    CANCELED_AFTER_INITIATED = 5
    CANCELED_AFTER_STARTED = 6
    CANCELLATION_DECISION_SENT = 7
    COMPLETED_AFTER_CANCELLATION_DECISION_SENT = 8
    COMPLETED = 9

    @classmethod
    def to_string(cls, state: DecisionState) -> str:
        mapping = {
            DecisionState.CREATED: "Created",
            DecisionState.DECISION_SENT: "DecisionSent",
            DecisionState.CANCELED_BEFORE_INITIATED: "CanceledBeforeInitiated",
            DecisionState.INITIATED: "Initiated",
            DecisionState.STARTED: "Started",
            DecisionState.CANCELED_AFTER_INITIATED: "CanceledAfterInitiated",
            DecisionState.CANCELED_AFTER_STARTED: "CanceledAfterStarted",
            DecisionState.CANCELLATION_DECISION_SENT: "CancellationDecisionSent",
            DecisionState.COMPLETED_AFTER_CANCELLATION_DECISION_SENT: "CompletedAfterCancellationDecisionSent",
            DecisionState.COMPLETED: "Completed",
        }
        return mapping.get(state, "Unknown")


class DecisionType(Enum):
    """Types of decisions that can be made by state machines."""

    ACTIVITY = 0
    CHILD_WORKFLOW = 1
    CANCELLATION = 2
    MARKER = 3
    TIMER = 4
    SIGNAL = 5
    UPSERT_SEARCH_ATTRIBUTES = 6

    @classmethod
    def to_string(cls, dt: DecisionType) -> str:
        mapping = {
            DecisionType.ACTIVITY: "Activity",
            DecisionType.CHILD_WORKFLOW: "ChildWorkflow",
            DecisionType.CANCELLATION: "Cancellation",
            DecisionType.MARKER: "Marker",
            DecisionType.TIMER: "Timer",
            DecisionType.SIGNAL: "Signal",
            DecisionType.UPSERT_SEARCH_ATTRIBUTES: "UpsertSearchAttributes",
        }
        return mapping.get(dt, "Unknown")


@dataclass(frozen=True)
class DecisionId:
    decision_type: DecisionType
    id: str

    def __str__(self) -> str:
        return (
            f"DecisionType: {DecisionType.to_string(self.decision_type)}, ID: {self.id}"
        )


class DecisionStateMachine(Protocol):
    def get_id(self) -> DecisionId: ...

    def get_decision(self) -> decision.Decision | None: ...

    def request_cancel(self) -> bool: ...


T = TypeVar("T")
CancelFn = Callable[[], bool]


class MachineFuture(asyncio.Future[T]):
    def __init__(self, _request_cancel: CancelFn | None = None) -> None:
        super().__init__()
        if _request_cancel is None:
            _request_cancel = self.force_cancel
        self._request_cancel = _request_cancel

    def force_cancel(self, message: Optional[str] = None) -> bool:
        return super().cancel(message)

    def cancel(self, msg=None) -> bool:
        return self._request_cancel()
