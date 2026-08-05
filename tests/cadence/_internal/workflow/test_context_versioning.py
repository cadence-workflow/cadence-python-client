import asyncio
from collections.abc import Sequence
from unittest.mock import MagicMock

import pytest

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.deterministic_event_loop import FatalDecisionError
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence._internal.workflow.statemachine.marker_state_machine import (
    MARKER_HEADER_KEY,
    VERSION_MARKER_NAME,
    encode_marker_header,
    marker_context_id,
)
from cadence.testing._workflow_environment import _InMemoryWorkflowContext
from cadence.api.v1 import decision, history
from cadence.api.v1.common_pb2 import Header, Payload
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import (
    DEFAULT_VERSION,
    VersioningOption,
    WorkflowInfo,
    execute_with_min_version,
    execute_with_version,
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


def _context(*, replay: bool = False) -> tuple[Context, MagicMock]:
    manager = MagicMock()
    manager.version_marker_details.return_value = None
    context = Context(_info(), manager)
    context.set_replay_mode(replay)
    return context, manager


def test_get_version_records_native_python_marker():
    context, manager = _context()

    assert context.get_version("change", 1, 2) == 2

    manager.record_version_marker.assert_called_once_with(
        "change", _info().data_converter.to_data([2])
    )


def test_get_version_options_follow_go_precedence_and_cache():
    context, manager = _context()

    assert (
        context.get_version(
            "change",
            1,
            5,
            execute_with_min_version(),
            execute_with_version(2),
            execute_with_version(3),
        )
        == 3
    )
    # Custom selection wins even when ExecuteWithMinVersion is applied last.
    assert (
        context.get_version(
            "change", 1, 5, execute_with_min_version(), execute_with_version(1)
        )
        == 3
    )
    assert manager.record_version_marker.call_count == 1


def test_get_version_execute_with_min_version_selects_minimum():
    context, _ = _context()

    assert context.get_version("change", 2, 5, execute_with_min_version()) == 2


def test_get_version_default_version_does_not_record_a_marker():
    context, manager = _context()

    assert (
        context.get_version(
            "change", DEFAULT_VERSION, 1, execute_with_version(DEFAULT_VERSION)
        )
        == DEFAULT_VERSION
    )
    manager.record_version_marker.assert_not_called()


def test_get_version_old_replay_without_marker_returns_default_and_emits_nothing():
    context, manager = _context(replay=True)

    assert context.get_version("change", DEFAULT_VERSION, 1) == DEFAULT_VERSION
    manager.record_version_marker.assert_not_called()


def test_get_version_markerless_replay_rejects_an_unsupported_default_version():
    context, manager = _context(replay=True)

    with pytest.raises(FatalDecisionError, match="markerless replay version -1"):
        context.get_version("change", 0, 1)

    manager.record_version_marker.assert_not_called()


def test_get_version_recorded_version_ignores_selection_options_and_is_revalidated():
    context, manager = _context(replay=True)
    details = _info().data_converter.to_data([2])
    manager.version_marker_details.return_value = details

    assert context.get_version("change", 1, 3, execute_with_version(1)) == 2
    manager.record_version_marker.assert_called_once_with("change", details)

    with pytest.raises(FatalDecisionError, match="cached version 2"):
        context.get_version("change", 3, 4, execute_with_version(3))


@pytest.mark.parametrize(
    ("change_id", "minimum", "maximum", "option"),
    [
        ("", 1, 1, None),
        ("change", True, 1, None),
        ("change", 1, False, None),
        ("change", 2, 1, None),
        ("change", 1, 2, execute_with_version(3)),
    ],
)
def test_get_version_validates_arguments(
    change_id: str, minimum: int, maximum: int, option: object
):
    context, _ = _context()
    options = () if option is None else (option,)

    with pytest.raises(ValueError):
        context.get_version(change_id, minimum, maximum, *options)


def test_execute_with_version_rejects_bool_and_non_int():
    with pytest.raises(ValueError):
        execute_with_version(True)
    with pytest.raises(ValueError):
        execute_with_version("1")  # type: ignore[arg-type]


def test_get_version_malformed_recorded_marker_is_a_fatal_decision_error():
    context, manager = _context(replay=True)
    manager.version_marker_details.return_value = Payload(data=b'"not an int"')

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
    manager.version_marker_details.return_value = details

    with pytest.raises(FatalDecisionError):
        context.get_version("change", 1, 2)


def test_get_version_accepts_noncanonical_custom_converter_details():
    class RandomizedConverter:
        def __init__(self) -> None:
            self._sequence = 0

        def from_data(
            self, payload: Payload, type_hints: list[type | None]
        ) -> list[int]:
            return [int(payload.data.split(b":", maxsplit=1)[1])]

        def to_data(self, values: list[int]) -> Payload:
            self._sequence += 1
            return Payload(data=f"{self._sequence}:{values[0]}".encode())

    converter = RandomizedConverter()
    manager = MagicMock()
    details = Payload(data=b"99:2")
    manager.version_marker_details.return_value = details
    info = _info()
    info = WorkflowInfo(
        workflow_type=info.workflow_type,
        workflow_domain=info.workflow_domain,
        workflow_id=info.workflow_id,
        workflow_run_id=info.workflow_run_id,
        workflow_task_list=info.workflow_task_list,
        data_converter=converter,
    )
    context = Context(info, manager)
    context.set_replay_mode(True)

    assert context.get_version("change", 1, 3) == 2
    manager.record_version_marker.assert_called_once_with("change", details)


def test_get_version_accepts_noncanonical_default_converter_subclass_details():
    class CustomDefaultConverter(DefaultDataConverter):
        def from_data(
            self, payload: Payload, type_hints: Sequence[type | None]
        ) -> list[int]:
            return [int(payload.data.removeprefix(b"version:"))]

        def to_data(self, values: list[int]) -> Payload:
            return Payload(data=f"version:{values[0]}".encode())

    manager = MagicMock()
    details = Payload(data=b"version:2")
    manager.version_marker_details.return_value = details
    info = _info()
    context = Context(
        WorkflowInfo(
            workflow_type=info.workflow_type,
            workflow_domain=info.workflow_domain,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            workflow_task_list=info.workflow_task_list,
            data_converter=CustomDefaultConverter(),
        ),
        manager,
    )
    context.set_replay_mode(True)

    assert context.get_version("change", 1, 3) == 2
    manager.record_version_marker.assert_called_once_with("change", details)


def test_get_version_accepts_empty_details_from_a_custom_converter():
    class EmptyIntConverter:
        def from_data(
            self, payload: Payload, type_hints: list[type | None]
        ) -> list[int]:
            assert payload == Payload()
            return [2]

        def to_data(self, values: list[int]) -> Payload:
            return Payload()

    manager = MagicMock()
    details = Payload()
    manager.version_marker_details.return_value = details
    info = _info()
    context = Context(
        WorkflowInfo(
            workflow_type=info.workflow_type,
            workflow_domain=info.workflow_domain,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            workflow_task_list=info.workflow_task_list,
            data_converter=EmptyIntConverter(),
        ),
        manager,
    )
    context.set_replay_mode(True)

    assert context.get_version("change", 1, 3) == 2
    manager.record_version_marker.assert_called_once_with("change", details)


def test_get_version_rejects_executable_options_without_running_them():
    context, manager = _context()
    calls: list[None] = []

    def executable_option(_: object) -> None:
        calls.append(None)

    with pytest.raises(ValueError, match="VersioningOption"):
        context.get_version("change", 1, 2, executable_option)  # type: ignore[arg-type]

    assert calls == []
    assert context.get_version("change", 1, 2) == 2
    manager.record_version_marker.assert_called_once()


@pytest.mark.parametrize(
    "args",
    [
        ("unknown", None),
        ("min", 1),
        ("version", None),
        ("version", True),
        ("version", "1"),
    ],
)
def test_versioning_option_constructor_validates_invariants(
    args: tuple[str, object],
):
    with pytest.raises(ValueError):
        VersioningOption(*args)  # type: ignore[arg-type]


def test_in_memory_context_does_not_cache_a_failed_version_selection():
    context = _InMemoryWorkflowContext(MagicMock(), _info())

    with pytest.raises(ValueError):
        context.get_version("change", 1, 2, execute_with_version(3))

    assert context.get_version("change", 1, 2) == 2


def test_in_memory_context_rejects_cached_version_range_with_fatal_error():
    context = _InMemoryWorkflowContext(MagicMock(), _info())
    assert context.get_version("change", 1, 2) == 2

    with pytest.raises(FatalDecisionError, match="cached version 2"):
        context.get_version("change", 3, 4)


@pytest.mark.parametrize("change_id", [None, True, 1, b"change"])
def test_production_context_requires_a_non_empty_string_change_id(change_id: object):
    context, manager = _context()

    with pytest.raises(ValueError, match="non-empty str"):
        context.get_version(change_id, 1, 2)  # type: ignore[arg-type]

    manager.record_version_marker.assert_not_called()


@pytest.mark.parametrize("change_id", [None, True, 1, b"change"])
def test_in_memory_context_requires_a_non_empty_string_change_id(change_id: object):
    context = _InMemoryWorkflowContext(MagicMock(), _info())

    with pytest.raises(ValueError, match="non-empty str"):
        context.get_version(change_id, 1, 2)  # type: ignore[arg-type]


def test_public_get_version_dispatches_through_context():
    context, _ = _context()

    with context._activate():
        assert get_version("change", 1, 2) == 2


async def test_version_marker_has_stable_id_header_and_does_not_consume_sequence():
    manager = DecisionManager(asyncio.get_event_loop())
    details = DefaultDataConverter().to_data([7])

    manager.record_version_marker("change", details)
    timer = decision.StartTimerDecisionAttributes()
    manager.start_timer(timer)

    pending = manager.collect_pending_decisions()
    marker = pending[0].record_marker_decision_attributes
    assert marker.marker_name == VERSION_MARKER_NAME
    assert marker.details == details
    assert marker_context_id(marker) == "change"
    assert timer.timer_id == "0"
    assert [key.id for key in manager.state_machines] == ["Version_change", "0"]


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

    with manager.track_nondeterminism(True, []):
        manager.preload_marker_event(marker_event)
        assert context.get_version("change", 1, 3, execute_with_version(1)) == 2
        assert manager.collect_pending_decisions() == [
            decision.Decision(
                record_marker_decision_attributes=decision.RecordMarkerDecisionAttributes(
                    marker_name=VERSION_MARKER_NAME,
                    details=details,
                    header=Header(
                        fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                    ),
                )
            )
        ]
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

    # The original decision batch did not call get_version, so its marker is
    # consumed without a state machine.
    with manager.track_nondeterminism(True, []):
        manager.preload_marker_event(marker_event)
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
        assert context._versions == {"change": None}

    # A later batch exposes the marker. The provisional default must not mask it.
    with manager.track_nondeterminism(True, []):
        manager.preload_marker_event(marker_event)
        assert context.get_version("change", 1, 2) == 2
        assert context._versions == {"change": 2}
        assert manager.collect_pending_decisions() == [
            decision.Decision(
                record_marker_decision_attributes=decision.RecordMarkerDecisionAttributes(
                    marker_name=VERSION_MARKER_NAME,
                    details=details,
                    header=Header(
                        fields={MARKER_HEADER_KEY: encode_marker_header("change")}
                    ),
                )
            )
        ]
        manager.handle_history_event(marker_event)
        assert manager.collect_pending_decisions() == []


async def test_replay_rejects_distinct_duplicate_version_markers():
    manager = DecisionManager(asyncio.get_event_loop())
    details = DefaultDataConverter().to_data([2])
    first_marker = history.HistoryEvent(
        event_id=1,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )
    second_marker = history.HistoryEvent(
        event_id=2,
        marker_recorded_event_attributes=history.MarkerRecordedEventAttributes(
            marker_name=VERSION_MARKER_NAME,
            details=details,
            header=Header(fields={MARKER_HEADER_KEY: encode_marker_header("change")}),
        ),
    )

    with manager.track_nondeterminism(True, []):
        manager.preload_marker_event(first_marker)
        # Marker preloading and output routing both process this same event.
        manager.handle_history_event(first_marker)
        with pytest.raises(FatalDecisionError, match="duplicate Version marker"):
            manager.preload_marker_event(second_marker)


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

    with manager.track_nondeterminism(True, [side_effect_event]):
        manager.preload_marker_event(version_event)
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

    with manager.track_nondeterminism(True, []):
        manager.preload_marker_event(foreign_marker)
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

    with manager.track_nondeterminism(True, []):
        with pytest.raises(FatalDecisionError, match="invalid Python MarkerHeader"):
            manager.preload_marker_event(malformed_marker)
