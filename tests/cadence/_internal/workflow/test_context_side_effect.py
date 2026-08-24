from unittest.mock import MagicMock

import pytest

from cadence._internal.workflow.context import Context
from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo
import cadence.workflow as workflow_module


def _make_ctx(*, replay: bool = False) -> tuple[Context, MagicMock]:
    dm = MagicMock()
    dc = DefaultDataConverter()
    info = WorkflowInfo(
        workflow_type="Wf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id="rid",
        workflow_task_list="tl",
        data_converter=dc,
    )
    ctx = Context(info, dm)
    ctx.set_replay_mode(replay)
    return ctx, dm


def _dc() -> DefaultDataConverter:
    return DefaultDataConverter()


def test_side_effect_calls_fn_and_returns_result():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.record_marker.return_value = dc.to_data([42])

    result = ctx.side_effect(lambda: 42, int)

    assert result == 42
    dm.record_marker.assert_called_once()
    attrs = dm.record_marker.call_args[0][0]
    assert attrs.marker_name == "SideEffect"
    assert attrs.details == dc.to_data([42])


def test_side_effect_fn_is_called_on_first_run():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.record_marker.return_value = dc.to_data([0])

    calls: list[int] = []

    def record_call() -> int:
        calls.append(1)
        return 1

    ctx.side_effect(record_call, int)

    assert len(calls) == 1


def test_side_effect_fn_is_skipped_on_replay():
    ctx, dm = _make_ctx(replay=True)
    dc = _dc()
    dm.record_marker.return_value = dc.to_data(["history-value"])

    calls: list[int] = []

    def record_call() -> str:
        calls.append(1)
        return "current-value"

    result = ctx.side_effect(record_call, str)

    assert len(calls) == 0
    assert result == "history-value"


def test_side_effect_on_replay_returns_history_value():
    ctx, dm = _make_ctx(replay=True)
    dc = _dc()
    dm.record_marker.return_value = dc.to_data(["history-value"])

    result = ctx.side_effect(lambda: "current-value", str)

    assert result == "history-value"


def test_side_effect_on_first_run_passes_fn_result_as_details():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.record_marker.return_value = dc.to_data(["x"])

    ctx.side_effect(lambda: "x", str)

    attrs = dm.record_marker.call_args[0][0]
    assert attrs.details == dc.to_data(["x"])


def test_side_effect_on_replay_passes_empty_details():
    ctx, dm = _make_ctx(replay=True)
    dc = _dc()
    dm.record_marker.return_value = dc.to_data(["history"])

    ctx.side_effect(lambda: "current", str)

    attrs = dm.record_marker.call_args[0][0]
    assert attrs.details == Payload()


def _raises_value_error() -> int:
    raise ValueError("boom")


def test_side_effect_raises_if_fn_raises():
    ctx, _ = _make_ctx()

    with pytest.raises(ValueError, match="boom"):
        ctx.side_effect(_raises_value_error, int)


def test_side_effect_module_level_dispatches_through_context():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.record_marker.return_value = dc.to_data([7])

    with ctx._activate():
        result = workflow_module.side_effect(lambda: 7, int)

    assert result == 7
    dm.record_marker.assert_called_once()


def test_mutable_side_effect_records_first_value():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.mutable_side_effect_value.return_value = (0, None, False)
    dm.record_mutable_side_effect.return_value = dc.to_data(["first"])

    result = ctx.mutable_side_effect(
        "config", lambda: "first", str, lambda old, new: old != new
    )

    assert result == "first"
    dm.record_mutable_side_effect.assert_called_once_with(
        "config", 0, dc.to_data(["first"])
    )


def test_mutable_side_effect_reuses_unchanged_value_without_marker():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.mutable_side_effect_value.return_value = (3, dc.to_data(["stored"]), False)

    result = ctx.mutable_side_effect(
        "config", lambda: "candidate", str, lambda old, new: old == new
    )

    assert result == "stored"
    dm.record_mutable_side_effect.assert_not_called()


def test_mutable_side_effect_records_changed_value():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.mutable_side_effect_value.return_value = (1, dc.to_data(["old"]), False)
    dm.record_mutable_side_effect.return_value = dc.to_data(["new"])

    result = ctx.mutable_side_effect(
        "config", lambda: "new", str, lambda old, new: old != new
    )

    assert result == "new"
    dm.record_mutable_side_effect.assert_called_once_with(
        "config", 1, dc.to_data(["new"])
    )


def test_mutable_side_effect_replay_skips_callbacks_and_uses_history():
    ctx, dm = _make_ctx(replay=True)
    dc = _dc()
    dm.mutable_side_effect_value.return_value = (2, dc.to_data(["history"]), True)
    fn = MagicMock()
    updated = MagicMock()
    dm.record_mutable_side_effect.return_value = dc.to_data(["history"])

    result = ctx.mutable_side_effect("config", fn, str, updated)

    assert result == "history"
    fn.assert_not_called()
    updated.assert_not_called()
    dm.record_mutable_side_effect.assert_called_once_with("config", 2, Payload())


def test_mutable_side_effect_replay_without_recorded_value_fails():
    ctx, dm = _make_ctx(replay=True)
    dm.mutable_side_effect_value.return_value = (0, None, False)

    with pytest.raises(ValueError, match="No recorded value"):
        ctx.mutable_side_effect(
            "config", lambda: "value", str, lambda old, new: old != new
        )


def test_mutable_side_effect_requires_id():
    ctx, _ = _make_ctx()

    with pytest.raises(ValueError, match="id must not be empty"):
        ctx.mutable_side_effect("", lambda: "value", str, lambda old, new: old != new)


def test_mutable_side_effect_module_level_dispatches_through_context():
    ctx, dm = _make_ctx()
    dc = _dc()
    dm.mutable_side_effect_value.return_value = (0, None, False)
    dm.record_mutable_side_effect.return_value = dc.to_data([7])

    with ctx._activate():
        result = workflow_module.mutable_side_effect(
            "value", lambda: 7, int, lambda old, new: old != new
        )

    assert result == 7
    dm.record_mutable_side_effect.assert_called_once()
