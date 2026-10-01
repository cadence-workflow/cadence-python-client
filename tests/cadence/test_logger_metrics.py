"""Tests for workflow/activity logger and metrics context APIs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import pytest

from cadence import activity, workflow
from cadence._internal.activity._context import _Context
from cadence._internal.activity._definition import AsyncImpl
from cadence._internal.activity._heartbeat import _HeartbeatSender
from cadence._internal.fn_signature import FnSignature
from cadence._internal.replay_aware import ReplayAwareLoggerAdapter
from cadence._internal.workflow.context import Context
from cadence._internal.workflow.statemachine.decision_manager import DecisionManager
from cadence.activity import ActivityInfo
from cadence.data_converter import DefaultDataConverter
from cadence.metrics import MetricsEmitter, NoOpMetricsEmitter
from cadence.workflow import WorkflowInfo


def _workflow_info() -> WorkflowInfo:
    return WorkflowInfo(
        workflow_type="TestWorkflow",
        workflow_domain="domain",
        workflow_id="wf-id",
        workflow_run_id="run-id",
        workflow_task_list="task-list",
        data_converter=DefaultDataConverter(),
    )


def _activity_info() -> ActivityInfo:
    now = datetime.now(timezone.utc)
    return ActivityInfo(
        task_token=b"token",
        workflow_type="TestWorkflow",
        workflow_domain="domain",
        workflow_id="wf-id",
        workflow_run_id="run-id",
        activity_id="act-id",
        activity_type="TestActivity",
        task_list="task-list",
        heartbeat_timeout=timedelta(seconds=10),
        scheduled_timestamp=now,
        started_timestamp=now,
        start_to_close_timeout=timedelta(seconds=10),
        attempt=1,
    )


class TestWorkflowLoggerAndMetrics:
    def test_suppresses_during_replay(self) -> None:
        metrics = Mock(spec=MetricsEmitter)
        metrics.with_tags.return_value = metrics
        base_logger = logging.getLogger("test.workflow.replay")
        handler = _RecordingHandler()
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.DEBUG)
        dm = MagicMock(spec=DecisionManager)
        try:
            ctx = Context(
                _workflow_info(),
                dm,
                metrics_emitter=metrics,
                logger=base_logger,
            )
            with ctx._activate():
                assert workflow.is_replaying() is True
                assert isinstance(workflow.logger(), ReplayAwareLoggerAdapter)
                workflow.logger().info("should be skipped")
                workflow.metrics().counter("user_metric")
                assert handler.records == []
                metrics.counter.assert_not_called()
        finally:
            base_logger.removeHandler(handler)

    def test_emits_when_not_replaying(self) -> None:
        metrics = Mock(spec=MetricsEmitter)
        metrics.with_tags.return_value = metrics
        base_logger = logging.getLogger("test.workflow.live")
        handler = _RecordingHandler()
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.DEBUG)
        dm = MagicMock(spec=DecisionManager)
        try:
            ctx = Context(
                _workflow_info(),
                dm,
                metrics_emitter=metrics,
                logger=base_logger,
            )
            ctx.set_replay_mode(False)
            with ctx._activate():
                assert workflow.is_replaying() is False
                assert workflow.info().workflow_id == "wf-id"
                workflow.logger().info("live log")
                workflow.metrics().counter("user_metric", 3)
                assert len(handler.records) == 1
                assert handler.records[0].workflow_id == "wf-id"
                metrics.counter.assert_called_once_with("user_metric", 3, None)
        finally:
            base_logger.removeHandler(handler)


class TestActivityLoggerAndMetrics:
    @pytest.mark.asyncio
    async def test_logger_and_metrics_available(self) -> None:
        async def _act() -> str:
            activity.logger().info("activity running")
            activity.metrics().counter("activity_metric")
            return "ok"

        metrics = Mock(spec=MetricsEmitter)
        metrics.with_tags.return_value = metrics
        base_logger = logging.getLogger("test.activity.logger")
        handler = _RecordingHandler()
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.DEBUG)

        defn = AsyncImpl(_act, "TestActivity", FnSignature.of(_act))
        heartbeat = MagicMock(spec=_HeartbeatSender)
        client = MagicMock()
        client.data_converter = DefaultDataConverter()
        try:
            ctx = _Context(
                client,
                _activity_info(),
                defn,
                heartbeat,
                metrics_emitter=metrics,
                logger=base_logger,
            )
            with ctx._activate():
                assert activity.info().activity_id == "act-id"
                activity.logger().info("activity running")
                activity.metrics().counter("activity_metric")
                assert len(handler.records) == 1
                assert handler.records[0].activity_id == "act-id"
                metrics.counter.assert_called_once_with("activity_metric")
        finally:
            base_logger.removeHandler(handler)

    def test_defaults_to_noop_metrics(self) -> None:
        async def _act() -> None:
            return None

        defn = AsyncImpl(_act, "TestActivity", FnSignature.of(_act))
        ctx = _Context(
            MagicMock(),
            _activity_info(),
            defn,
            MagicMock(spec=_HeartbeatSender),
        )
        with ctx._activate():
            assert isinstance(activity.metrics(), NoOpMetricsEmitter)


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
