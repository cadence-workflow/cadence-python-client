from unittest.mock import MagicMock

import pytest

from cadence._internal.workflow.context import Context
from cadence._internal.workflow.search_attributes import search_attributes_to_proto
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo


def _make_ctx() -> tuple[Context, MagicMock]:
    dm = MagicMock()
    info = WorkflowInfo(
        workflow_type="Wf",
        workflow_domain="domain",
        workflow_id="wid",
        workflow_run_id="rid",
        workflow_task_list="tl",
        data_converter=DefaultDataConverter(),
    )
    return Context(info, dm), dm


def test_upsert_search_attributes_emits_decision():
    ctx, dm = _make_ctx()
    ctx.set_replay_mode(False)

    ctx.upsert_search_attributes({"CustomIntField": 1, "CustomBoolField": True})

    dm.upsert_search_attributes.assert_called_once()
    attrs = dm.upsert_search_attributes.call_args[0][0]
    expected = search_attributes_to_proto(
        {"CustomIntField": 1, "CustomBoolField": True}
    )
    assert attrs.search_attributes == expected


def test_upsert_search_attributes_merges_into_info():
    ctx, _dm = _make_ctx()

    ctx.upsert_search_attributes({"CustomIntField": 1, "CustomBoolField": True})
    ctx.upsert_search_attributes({"CustomIntField": 2, "CustomKeywordField": "seattle"})

    assert ctx.info().search_attributes == {
        "CustomIntField": 2,
        "CustomBoolField": True,
        "CustomKeywordField": "seattle",
    }


def test_upsert_search_attributes_rejects_empty():
    ctx, dm = _make_ctx()

    with pytest.raises(ValueError, match="search attributes must not be empty"):
        ctx.upsert_search_attributes({})

    dm.upsert_search_attributes.assert_not_called()


def test_upsert_search_attributes_is_noop_on_replay():
    ctx, dm = _make_ctx()
    ctx.set_replay_mode(True)

    ctx.upsert_search_attributes(
        {"CustomIntField": 1, "CustomKeywordField": ["a", "b"]}
    )

    dm.upsert_search_attributes.assert_not_called()
    assert ctx.info().search_attributes == {
        "CustomIntField": 1,
        "CustomKeywordField": ["a", "b"],
    }
