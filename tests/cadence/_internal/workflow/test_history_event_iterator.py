import pytest
from unittest.mock import Mock, AsyncMock

from cadence.client import Client
from cadence.api.v1.common_pb2 import WorkflowExecution
from cadence.api.v1.history_pb2 import HistoryEvent, History
from cadence.api.v1.service_worker_pb2 import PollForDecisionTaskResponse
from cadence.api.v1.service_workflow_pb2 import GetWorkflowExecutionHistoryResponse
from cadence._internal.workflow.history_event_iterator import iterate_history_events


@pytest.fixture
def mock_client():
    """Create a mock client with workflow_stub."""
    client = Mock(spec=Client)
    client.workflow_stub = AsyncMock()
    client.domain = "test-domain"
    return client


@pytest.fixture
def mock_workflow_execution():
    """Create a mock workflow execution."""
    return WorkflowExecution(
        workflow_id="test-workflow-id",
        run_id="test-run-id"
    )


def create_history_event(event_id: int) -> HistoryEvent:
    return HistoryEvent(event_id=event_id)


async def test_iterate_history_events_single_page_no_next_token(mock_client, mock_workflow_execution):
    """Test iterating over a single page of events with no next page token."""
    # Create test events
    events = [
        create_history_event(1),
        create_history_event(2),
        create_history_event(3)
    ]

    # Create decision task response with events but no next page token
    decision_task = PollForDecisionTaskResponse(
        history=History(events=events),
        next_page_token=b"",  # Empty token means no more pages
        workflow_execution=mock_workflow_execution
    )

    # Iterate and collect events
    result_events = [e async for e in iterate_history_events(decision_task, mock_client)]

    # Verify all events were returned
    assert len(result_events) == 3
    assert result_events[0].event_id == 1
    assert result_events[1].event_id == 2
    assert result_events[2].event_id == 3

    # Verify no additional API calls were made
    mock_client.workflow_stub.GetWorkflowExecutionHistory.assert_not_called()


async def test_iterate_history_events_empty_events(mock_client, mock_workflow_execution):
    """Test iterating over empty events list."""
    # Create decision task response with no events
    decision_task = PollForDecisionTaskResponse(
        history=History(events=[]),
        next_page_token=b"",
        workflow_execution=mock_workflow_execution
    )

    # Iterate and collect events
    result_events = [e async for e in iterate_history_events(decision_task, mock_client)]

    # Verify no events were returned
    assert len(result_events) == 0

    # Verify no additional API calls were made
    mock_client.workflow_stub.GetWorkflowExecutionHistory.assert_not_called()

async def test_iterate_history_events_multiple_pages(mock_client, mock_workflow_execution):
    """Test iterating over multiple pages of events."""

    # Create decision task response with first page and next page token
    decision_task = PollForDecisionTaskResponse(
        history=History(events=[
            create_history_event(1),
            create_history_event(2)
        ]),
        next_page_token=b"page2_token",
        workflow_execution=mock_workflow_execution
    )

    # Mock the subsequent API calls
    second_response = GetWorkflowExecutionHistoryResponse(
        history=History(events=[
            create_history_event(3),
            create_history_event(4)
        ]),
        next_page_token=b"page3_token"
    )

    third_response = GetWorkflowExecutionHistoryResponse(
        history=History(events=[
            create_history_event(5)
        ]),
        next_page_token=b""  # No more pages
    )

    # Configure mock to return responses in sequence
    mock_client.workflow_stub.GetWorkflowExecutionHistory.side_effect = [
        second_response,
        third_response
    ]

    # Iterate and collect events
    result_events = [e async for e in iterate_history_events(decision_task, mock_client)]

    # Verify all events from all pages were returned
    assert len(result_events) == 5
    assert result_events[0].event_id == 1
    assert result_events[1].event_id == 2
    assert result_events[2].event_id == 3
    assert result_events[3].event_id == 4
    assert result_events[4].event_id == 5

    # Verify correct API calls were made
    assert mock_client.workflow_stub.GetWorkflowExecutionHistory.call_count == 2

    # Verify first API call
    first_call = mock_client.workflow_stub.GetWorkflowExecutionHistory.call_args_list[0]
    first_request = first_call[0][0]
    assert first_request.domain == "test-domain"
    assert first_request.workflow_execution == mock_workflow_execution
    assert first_request.next_page_token == b"page2_token"
    assert first_request.page_size == 1000

    # Verify second API call
    second_call = mock_client.workflow_stub.GetWorkflowExecutionHistory.call_args_list[1]
    second_request = second_call[0][0]
    assert second_request.domain == "test-domain"
    assert second_request.workflow_execution == mock_workflow_execution
    assert second_request.next_page_token == b"page3_token"
    assert second_request.page_size == 1000

async def test_iterate_history_events_single_page_with_next_token_then_empty(mock_client, mock_workflow_execution):
    """Test case where first page has next token but second page is empty."""
    # Create first page of events
    first_page_events = [
        create_history_event(1),
        create_history_event(2)
    ]

    # Create decision task response with first page and next page token
    decision_task = PollForDecisionTaskResponse(
        history=History(events=first_page_events),
        next_page_token=b"page2_token",
        workflow_execution=mock_workflow_execution
    )

    # Mock the second API call to return empty page
    second_response = GetWorkflowExecutionHistoryResponse(
        history=History(events=[]),
        next_page_token=b""  # No more pages
    )

    mock_client.workflow_stub.GetWorkflowExecutionHistory.return_value = second_response

    # Iterate and collect events
    result_events = [e async for e in iterate_history_events(decision_task, mock_client)]

    # Verify only first page events were returned
    assert len(result_events) == 2
    assert result_events[0].event_id == 1
    assert result_events[1].event_id == 2

    # Verify one API call was made
    assert mock_client.workflow_stub.GetWorkflowExecutionHistory.call_count == 1
