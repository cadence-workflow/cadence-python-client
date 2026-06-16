from __future__ import annotations

import time
from typing import TYPE_CHECKING, Iterator, List, Optional

from cadence.api.v1.history_pb2 import HistoryEvent
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryRequest,
    GetWorkflowExecutionHistoryResponse,
)
from cadence.client import Client
from cadence.metrics.constants import WORKFLOW_GET_HISTORY_COUNTER, WORKFLOW_GET_HISTORY_LATENCY

if TYPE_CHECKING:
    from cadence.metrics import MetricsEmitter


async def iterate_history_events(
    decision_task: PollForDecisionTaskResponse,
    client: Client,
    metrics_emitter: Optional[MetricsEmitter] = None,
):
    PAGE_SIZE = 1000

    current_page = decision_task.history.events
    next_page_token = decision_task.next_page_token
    workflow_execution = decision_task.workflow_execution

    while True:
        for event in current_page:
            yield event
        if not next_page_token:
            break
        fetch_start = time.monotonic()
        response: GetWorkflowExecutionHistoryResponse = (
            await client.workflow_stub.GetWorkflowExecutionHistory(
                GetWorkflowExecutionHistoryRequest(
                    domain=client.domain,
                    workflow_execution=workflow_execution,
                    next_page_token=next_page_token,
                    page_size=PAGE_SIZE,
                )
            )
        )
        fetch_elapsed = time.monotonic() - fetch_start
        if metrics_emitter is not None:
            metrics_emitter.counter(WORKFLOW_GET_HISTORY_COUNTER)
            metrics_emitter.histogram(WORKFLOW_GET_HISTORY_LATENCY, fetch_elapsed)
        current_page = response.history.events
        next_page_token = response.next_page_token


class HistoryEventsIterator(Iterator[HistoryEvent]):
    def __init__(self, events: List[HistoryEvent]):
        self._iter = iter(events)
        self._current = next(self._iter, None)

    def __iter__(self):
        return self

    def __next__(self) -> HistoryEvent:
        if not self._current:
            raise StopIteration("No more events")
        event = self._current
        self._current = next(self._iter, None)
        return event

    def has_next(self) -> bool:
        return self._current is not None

    def peek(self) -> Optional[HistoryEvent]:
        return self._current
