"""Replay-aware logger and metrics wrappers for workflow code.

During workflow history replay, user-facing logs and metrics must be suppressed
so they are not duplicated. Activities are not replayed, so they use plain
tagged loggers and metrics emitters.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
)

from cadence.metrics import MetricsEmitter


class ReplayAwareLoggerAdapter(logging.LoggerAdapter):
    """Logger that suppresses output while a workflow is replaying history."""

    def __init__(
        self,
        logger: logging.Logger,
        extra: Mapping[str, Any] | None,
        is_replaying: Callable[[], bool],
        *,
        enable_logging_in_replay: bool = False,
    ) -> None:
        super().__init__(logger, dict(extra) if extra else {})
        self._is_replaying = is_replaying
        self.enable_logging_in_replay = enable_logging_in_replay

    def isEnabledFor(self, level: int) -> bool:
        if self._is_replaying() and not self.enable_logging_in_replay:
            return False
        return bool(self.logger.isEnabledFor(level))

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        # Merge adapter extras with call-site extras (call-site wins).
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


class ReplayAwareMetricsEmitter:
    """MetricsEmitter that no-ops while a workflow is replaying history."""

    def __init__(
        self,
        base: MetricsEmitter,
        is_replaying: Callable[[], bool],
    ) -> None:
        self._base = base
        self._is_replaying = is_replaying

    def with_tags(self, tags: Dict[str, str]) -> MetricsEmitter:
        return ReplayAwareMetricsEmitter(
            self._base.with_tags(tags), self._is_replaying
        )

    def counter(
        self, key: str, n: int = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        if self._is_replaying():
            return
        self._base.counter(key, n, tags)

    def gauge(
        self, key: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        if self._is_replaying():
            return
        self._base.gauge(key, value, tags)

    def histogram(
        self, key: str, value: timedelta, tags: Optional[Dict[str, str]] = None
    ) -> None:
        if self._is_replaying():
            return
        self._base.histogram(key, value, tags)


class TaggedLoggerAdapter(logging.LoggerAdapter):
    """LoggerAdapter that merges fixed extras with call-site extras."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs
