import asyncio
from unittest.mock import MagicMock

import pytest

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.deterministic_event_loop import FatalDecisionError
from cadence._internal.workflow.statemachine.decision_state_machine import DecisionState
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.statemachine.marker_state_machine import (
    MARKER_HEADER_KEY,
    MarkerStateMachine,
    VERSION_MARKER_NAME,
    encode_marker_header,
    marker_context_id,
    marker_decision_id,
)
from cadence._internal.workflow.versioning import encode_version_marker_details
from cadence.testing._workflow_environment import _InMemoryWorkflowContext
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Header, Payload
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import (
    DEFAULT_VERSION,
    WorkflowInfo,
    get_version,
)


def _info() -> WorkflowInfo:
    return WorkflowInfo(
        workflow_type="Wf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id="rid",
        workflow_task_list="tl",
        data_converter=DefaultDataConverter(),
    )


def _context(*, replay: bool = False) -> tuple[Context, DecisionManager]:
    manager = DecisionManager(MagicMock())
    context = Context(_info(), manager)
    context.set_replay_mode(replay)
    return context, manager


def _version_machine(manager: DecisionManager, change_id: str) -> MarkerStateMachine:
    machine = manager.state_machines[marker_decision_id(VERSION_MARKER_NAME, change_id)]
    assert isinstance(machine, MarkerStateMachine)
    return machine


def _load_version_marker(
    manager: DecisionManager, marker_event: history.HistoryEvent
) -> None:
    with manager.track_nondeterminism(True, [marker_event]):
        pass


def test_get_version_records_max_version_for_new_execution():
    context, manager = _context()

    assert context.get_version("change", 1, 2) == 2
    machine = _version_machine(manager, "change")
    assert machine.state is DecisionState.REQUESTED
    assert machine.get_result() == encode_version_marker_details(2)
    pending = manager.collect_pending_decisions()
    assert len(pending) == 1
    assert pending[0].record_marker_decision_attributes.details == (
        encode_version_marker_details(2)
    )


def test_get_version_explicit_default_does_not_record_a_marker():
    context, manager = _context()

    assert context.get_version("change", DEFAULT_VERSION, DEFAULT_VERSION) == (
        DEFAULT_VERSION
    )
    machine = _version_machine(manager, "change")
    assert machine.state is DecisionState.COMPLETED
    assert manager.collect_pending_decisions() == []


def test_repeated_get_version_reads_the_same_state_machine():
    context, manager = _context()

    for _ in range(3):
        assert context.get_version("change", DEFAULT_VERSION, 2) == 2

    assert not hasattr(context, "_versions")
    assert [decision_id.id for decision_id in manager.state_machines] == [
        "Version_change"
    ]
    assert manager.collect_pending_decisions()[0].record_marker_decision_attributes.details == (
        encode_version_marker_details(2)
    )


def test_get_version_old_replay_without_marker_returns_default_and_emits_nothing():
    context, manager = _context(replay=True)

    assert context.get_version("change", DEFAULT_VERSION, 1) == DEFAULT_VERSION
    assert manager.collect_pending_decisions() == []


def test_get_version_markerless_replay_rejects_an_unsupported_default_version():
    context, manager = _context(replay=True)

    with pytest.raises(FatalDecisionError, match="version -1"):
        context.get_version("change", 0, 1)

    assert manager.collect_pending_decisions() == []


def test_get_version_recorded_version_is_revalidated():
    context, manager = _context(replay=True)
    _load_version_marker(
        manager,
        history.HistoryEvent(
            event_id=1,
            marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                marker_name=VERSION_MARKER_NAME,
                details=encode_version_marker_details(2),
                header=Header(
                    fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                ),
            ),
        ),
    )

    assert context.get_version("change", 1, 3) == 2

    with pytest.raises(FatalDecisionError, match="version 2"):
        context.get_version("change", 3, 4)


@pytest.mark.parametrize(
    ("change_id", "minimum", "maximum"),
    [
        ("", 1, 1),
        ("change", True, 1),
        ("change", 1, False),
        ("change", 2, 1),
    ],
)
def test_get_version_validates_arguments(change_id: str, minimum: int, maximum: int):
    context, _ = _context()

    with pytest.raises(ValueError):
        context.get_version(change_id, minimum, maximum)


def test_get_version_malformed_recorded_marker_is_a_fatal_decision_error():
    context, manager = _context(replay=True)
    _load_version_marker(
        manager,
        history.HistoryEvent(
            event_id=1,
            marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                marker_name=VERSION_MARKER_NAME,
                details=Payload(data=b'"not an int"'),
                header=Header(
                    fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                ),
            ),
        ),
    )

    with pytest.raises(FatalDecisionError, match="Unable to decode Version marker"):
        context.get_version("change", 1, 2)


@pytest.mark.parametrize(
    "details",
    [
        Payload(),
        Payload(data=b"1 2"),
        Payload(data=b"1 trailing"),
        Payload(data=b"1x"),
    ],
)
def test_get_version_rejects_invalid_default_converter_marker_details(
    details: Payload,
):
    context, manager = _context(replay=True)
    _load_version_marker(
        manager,
        history.HistoryEvent(
            event_id=1,
            marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                marker_name=VERSION_MARKER_NAME,
                details=details,
                header=Header(
                    fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                ),
            ),
        ),
    )

    with pytest.raises(FatalDecisionError):
        context.get_version("change", 1, 2)


def test_get_version_marker_codec_does_not_use_custom_data_converter():
    converter = MagicMock()
    converter.from_data.side_effect = AssertionError("must not decode marker details")
    converter.to_data.side_effect = AssertionError("must not encode marker details")
    info = _info()
    custom_info = WorkflowInfo(
        workflow_type=info.workflow_type,
        workflow_domain=info.workflow_domain,
        workflow_id=info.workflow_id,
        workflow_run_id=info.workflow_run_id,
        workflow_task_list=info.workflow_task_list,
        data_converter=converter,
    )

    live_manager = DecisionManager(MagicMock())
    live_context = Context(custom_info, live_manager)
    live_context.set_replay_mode(False)

    assert live_context.get_version("change", DEFAULT_VERSION, 3) == 3

    replay_manager = DecisionManager(MagicMock())
    details = encode_version_marker_details(3)
    _load_version_marker(
        replay_manager,
        history.HistoryEvent(
            event_id=1,
            marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
                marker_name=VERSION_MARKER_NAME,
                details=details,
                header=Header(
                    fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                ),
            ),
        ),
    )
    replay_context = Context(
        WorkflowInfo(
            workflow_type=info.workflow_type,
            workflow_domain=info.workflow_domain,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            workflow_task_list=info.workflow_task_list,
            data_converter=converter,
        ),
        replay_manager,
    )
    replay_context.set_replay_mode(True)

    assert replay_context.get_version("change", 1, 3) == 3
    converter.to_data.assert_not_called()
    converter.from_data.assert_not_called()


def test_in_memory_context_selects_max_version():
    context = _InMemoryWorkflowContext(MagicMock(), _info())

    assert context.get_version("change", DEFAULT_VERSION, 2) == 2


def test_in_memory_context_revalidates_cached_version():
    context = _InMemoryWorkflowContext(MagicMock(), _info())
    assert context.get_version("change", DEFAULT_VERSION, 2) == 2

    with pytest.raises(FatalDecisionError, match="version 2"):
        context.get_version("change", 3, 4)


@pytest.mark.parametrize("change_id", [None, True, 1, b"change"])
def test_production_context_requires_a_non_empty_string_change_id(change_id: object):
    context, manager = _context()

    with pytest.raises(ValueError, match="non-empty str"):
        context.get_version(change_id, 1, 2)  # type: ignore[arg-type]

    assert manager.state_machines == {}


@pytest.mark.parametrize("change_id", [None, True, 1, b"change"])
def test_in_memory_context_requires_a_non_empty_string_change_id(change_id: object):
    context = _InMemoryWorkflowContext(MagicMock(), _info())

    with pytest.raises(ValueError, match="non-empty str"):
        context.get_version(change_id, 1, 2)  # type: ignore[arg-type]


def test_public_get_version_dispatches_through_context():
    context, _ = _context()

    with context._activate():
        assert get_version("change", DEFAULT_VERSION, 2) == 2


async def test_version_marker_has_stable_id_header_and_does_not_consume_sequence():
    manager = DecisionManager(asyncio.get_event_loop())
    details = encode_version_marker_details(DEFAULT_VERSION)

    manager.version_marker_result("change", details)
    machine = _version_machine(manager, "change")
    timer = decision.StartTimerDecisionAttributes()
    manager.start_timer(timer)

    pending = manager.collect_pending_decisions()
    assert machine.get_result() == details
    assert marker_context_id(machine.request) == "change"
    assert timer.timer_id == "0"
    assert [key.id for key in manager.state_machines] == ["Version_change", "0"]
    assert len(pending) == 1
    assert pending[0].HasField("start_timer_decision_attributes")


async def test_replay_preloads_python_version_marker_and_completes_its_state_machine():
    manager = DecisionManager(asyncio.get_event_loop())
    details = DefaultDataConverter().to_data([2])
    marker_event = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )
    context = Context(_info(), manager)
    context.set_replay_mode(True)

    with manager.track_nondeterminism(True, [marker_event]):
        assert context.get_version("change", 1, 3) == 2
        assert manager.collect_pending_decisions() == []
        manager.handle_history_event(marker_event)
        assert manager.collect_pending_decisions() == []


async def test_replay_does_not_recreate_consumed_version_marker_in_later_batch():
    manager = DecisionManager(asyncio.get_event_loop())
    details = DefaultDataConverter().to_data([2])
    marker_event = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )
    context = Context(_info(), manager)
    context.set_replay_mode(True)

    with manager.track_nondeterminism(True, [marker_event]):
        manager.handle_history_event(marker_event)
        assert manager.collect_pending_decisions() == []

    # A moved get_version call still observes the recorded value, but must not
    # recreate a decision for a marker whose output event is already consumed.
    with manager.track_nondeterminism(True, []):
        assert context.get_version("change", 1, 3) == 2
        assert manager.collect_pending_decisions() == []


async def test_markerless_replay_default_is_replaced_by_later_version_marker():
    manager = DecisionManager(asyncio.get_event_loop())
    context = Context(_info(), manager)
    context.set_replay_mode(True)
    details = DefaultDataConverter().to_data([2])
    marker_event = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )

    # First replay batch predates the Version marker.
    with manager.track_nondeterminism(True, []):
        assert context.get_version("change", DEFAULT_VERSION, 2) == DEFAULT_VERSION
        machine = _version_machine(manager, "change")
        assert machine.get_result() == encode_version_marker_details(DEFAULT_VERSION)

    with manager.track_nondeterminism(True, [marker_event]):
        assert context.get_version("change", 1, 2) == 2
        assert _version_machine(manager, "change") is machine
        assert machine.get_result() == details
        assert manager.collect_pending_decisions() == []
        manager.handle_history_event(marker_event)
        assert manager.collect_pending_decisions() == []


async def test_replay_rejects_conflicting_recorded_version_markers():
    manager = DecisionManager(asyncio.get_event_loop())
    first_details = encode_version_marker_details(2)
    second_details = encode_version_marker_details(3)
    first_marker = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=first_details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )
    second_marker = history.HistoryEvent(
        event_id=2,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=second_details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )

    with manager.track_nondeterminism(True, [first_marker]):
        machine = _version_machine(manager, "change")
        assert machine.get_result() == first_details
        manager.handle_history_event(first_marker)

    with pytest.raises(FatalDecisionError, match="conflicting Version marker"):
        with manager.track_nondeterminism(True, [second_marker]):
            pass
    assert manager._replaying is False
    with manager.track_nondeterminism(False, []):
        pass


async def test_version_markers_coexist_with_existing_markers_without_shifting_ids():
    manager = DecisionManager(asyncio.get_event_loop())
    details = DefaultDataConverter().to_data([2])
    version_event = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )
    side_effect_event = history.HistoryEvent(
        event_id=2,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name="SideEffect",
            details=Payload(data=b"side-effect"),
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("0")}),
        ),
    )
    context = Context(_info(), manager)
    context.set_replay_mode(True)
    side_effect = decision.RecordMarkerDecisionAttributes(
        marker_name="SideEffect", details=Payload(data=b"new-value")
    )

    with manager.track_nondeterminism(True, [version_event, side_effect_event]):
        assert context.get_version("change", 1, 3) == 2
        manager.record_marker(side_effect)
        assert marker_context_id(side_effect) == "0"
        assert [item.get_id().id for item in manager.state_machines.values()] == [
            "Version_change",
            "SideEffect_0",
        ]
        manager.handle_history_event(version_event)
        manager.handle_history_event(side_effect_event)


async def test_replay_ignores_foreign_version_marker_format():
    manager = DecisionManager(asyncio.get_event_loop())
    context = Context(_info(), manager)
    context.set_replay_mode(True)
    foreign_marker = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=Payload(data=b'{"version": 2}'),
        ),
    )

    with manager.track_nondeterminism(True, [foreign_marker]):
        assert context.get_version("change", DEFAULT_VERSION, 2) == DEFAULT_VERSION
        assert manager.collect_pending_decisions() == []


@pytest.mark.parametrize(
    "header_data",
    [b"not-json", b"{}", b'{"context_id":""}'],
)
async def test_replay_rejects_malformed_python_version_marker_header(
    header_data: bytes,
):
    manager = DecisionManager(asyncio.get_event_loop())
    malformed_marker = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=DefaultDataConverter().to_data([2]),
            header=Header(fields={MARKER_HEADER_KEY: Payload(data=header_data)}),
        ),
    )

    with pytest.raises(FatalDecisionError, match="invalid Python MarkerHeader"):
        with manager.track_nondeterminism(True, [malformed_marker]):
            pass
