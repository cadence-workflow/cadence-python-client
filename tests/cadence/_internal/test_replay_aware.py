"""Tests for replay-aware logger and metrics wrappers."""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import Mock

from cadence._internal.replay_aware import (
    ReplayAwareLoggerAdapter,
    ReplayAwareMetricsEmitter,
    TaggedLoggerAdapter,
)
from cadence.metrics import MetricsEmitter


class TestReplayAwareLoggerAdapter:
    def test_suppresses_logs_during_replay(self) -> None:
        base = Mock(spec=logging.Logger)
        base.isEnabledFor.return_value = True
        replaying = True
        adapter = ReplayAwareLoggerAdapter(
            base, {"workflow_id": "wf"}, lambda: replaying
        )

        assert adapter.isEnabledFor(logging.INFO) is False
        adapter.info("hello")
        base.log.assert_not_called()

    def test_emits_logs_when_not_replaying(self) -> None:
        base = logging.getLogger("test.replay.logger.emit")
        base.setLevel(logging.DEBUG)
        handler = _RecordingHandler()
        base.addHandler(handler)
        try:
            adapter = ReplayAwareLoggerAdapter(
                base, {"workflow_id": "wf-1"}, lambda: False
            )
            adapter.info("hello %s", "world")
            assert len(handler.records) == 1
            assert handler.records[0].getMessage() == "hello world"
            assert handler.records[0].workflow_id == "wf-1"
        finally:
            base.removeHandler(handler)

    def test_enable_logging_in_replay(self) -> None:
        base = logging.getLogger("test.replay.logger.enabled")
        base.setLevel(logging.DEBUG)
        handler = _RecordingHandler()
        base.addHandler(handler)
        try:
            adapter = ReplayAwareLoggerAdapter(
                base,
                {"workflow_id": "wf"},
                lambda: True,
                enable_logging_in_replay=True,
            )
            assert adapter.isEnabledFor(logging.INFO) is True
            adapter.info("during replay")
            assert len(handler.records) == 1
        finally:
            base.removeHandler(handler)


class TestReplayAwareMetricsEmitter:
    def test_suppresses_metrics_during_replay(self) -> None:
        base = Mock(spec=MetricsEmitter)
        base.with_tags.return_value = base
        emitter = ReplayAwareMetricsEmitter(base, lambda: True)

        emitter.counter("c")
        emitter.gauge("g", 1.0)
        emitter.histogram("h", timedelta(seconds=1))
        tagged = emitter.with_tags({"k": "v"})
        tagged.counter("c2")

        base.counter.assert_not_called()
        base.gauge.assert_not_called()
        base.histogram.assert_not_called()

    def test_emits_metrics_when_not_replaying(self) -> None:
        base = Mock(spec=MetricsEmitter)
        base.with_tags.return_value = base
        emitter = ReplayAwareMetricsEmitter(base, lambda: False)

        emitter.counter("c", 2)
        emitter.gauge("g", 3.5)
        emitter.histogram("h", timedelta(milliseconds=10))

        base.counter.assert_called_once_with("c", 2, None)
        base.gauge.assert_called_once_with("g", 3.5, None)
        base.histogram.assert_called_once_with("h", timedelta(milliseconds=10), None)


class TestTaggedLoggerAdapter:
    def test_merges_extras(self) -> None:
        base = logging.getLogger("test.tagged.logger")
        base.setLevel(logging.DEBUG)
        handler = _RecordingHandler()
        base.addHandler(handler)
        try:
            adapter = TaggedLoggerAdapter(base, {"activity_id": "a1"})
            adapter.info("hi", extra={"attempt": 2})
            assert handler.records[0].activity_id == "a1"
            assert handler.records[0].attempt == 2
        finally:
            base.removeHandler(handler)


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
