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

    # Indicates that user code requested the operation. For example, this is the state immediately after calling
    # schedule_activity. From this state, state machines should yield a decision to initiate the operation.
    REQUESTED = 0
    # The Decision was canceled before it was ever sent to the server. State machines should yield a marker.
    CANCELED_AFTER_REQUESTED = 1
    # Indicates the Decision was recorded in history. For example, this is the state after
    # history.ActivityTaskScheduledEventAttributes is received.
    # It's effectively started, but "started" is a loaded term.
    RECORDED = 2
    # The Decision was canceled after it was recorded in history. We need to yield another decision to cancel it.
    CANCELED_AFTER_RECORDED = 3
    # Most types don't use this state.
    # Child Workflows are unique in that they have an intermediate state between "recorded" and "completed". Unlike
    # an activity starting, it's an observable event. It's needed to communicate the WorkflowID and whether it actually
    # could start.
    # Currently unused.
    STARTED = 4
    # Maybe also needed for ChildWorkflows depending on how we model them.
    # Currently unused.
    CANCELED_AFTER_STARTED = 5
    # The Decision to cancel the operation was recorded in history.
    CANCELLATION_RECORDED = 6
    # Completed, maybe successfully, maybe not.
    COMPLETED = 7


class DecisionType(Enum):
    """Types of decisions that can be made by state machines."""

    ACTIVITY = 0
    CHILD_WORKFLOW = 1
    CANCELLATION = 2
    MARKER = 3
    TIMER = 4
    SIGNAL = 5
    UPSERT_SEARCH_ATTRIBUTES = 6
    WORKFLOW_COMPLETE = 7


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
        self._state = DecisionState.REQUESTED

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
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        request_cancel: CancelFn | None = None,
    ) -> None:
        super().__init__(loop=loop)
        if request_cancel is None:
            request_cancel = self.force_cancel
        self._request_cancel = request_cancel

    def force_cancel(self, message: Optional[str] = None) -> bool:
        return super().cancel(message)

    def cancel(self, msg=None) -> bool:
        return self._request_cancel()
