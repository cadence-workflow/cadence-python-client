from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol, TypeVar, Optional

from cadence.api.v1 import (
    decision_pb2 as decision,
)


# TODO: Remove unused states
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


class DecisionType(Enum):
    """Types of decisions that can be made by state machines."""

    ACTIVITY = 0
    CHILD_WORKFLOW = 1
    CANCELLATION = 2
    MARKER = 3
    TIMER = 4
    SIGNAL = 5
    UPSERT_SEARCH_ATTRIBUTES = 6


@dataclass(frozen=True)
class DecisionId:
    decision_type: DecisionType
    id: str


class DecisionStateMachine(Protocol):
    def get_id(self) -> DecisionId: ...

    def get_decision(self) -> decision.Decision | None: ...

    def request_cancel(self) -> bool: ...


class BaseDecisionStateMachine(DecisionStateMachine):
    def __init__(self):
        self._state = DecisionState.CREATED

    def _transition(
        self, to: DecisionState, allowed_from: list[DecisionState] | None = None
    ) -> None:
        # TODO: Maybe track previous states like the other clients
        if allowed_from and self.state not in allowed_from:
            raise RuntimeError(f"unable to transition to {to} from {self.state}")
        self._state = to

    @property
    def state(self) -> DecisionState:
        return self._state


T = TypeVar("T")
CancelFn = Callable[[], bool]


class DecisionFuture(asyncio.Future[T]):
    def __init__(self, request_cancel: CancelFn | None = None) -> None:
        super().__init__()
        if request_cancel is None:
            request_cancel = self.force_cancel
        self._request_cancel = request_cancel

    def force_cancel(self, message: Optional[str] = None) -> bool:
        return super().cancel(message)

    def cancel(self, msg=None) -> bool:
        return self._request_cancel()
