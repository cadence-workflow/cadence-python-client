"""Nanosecond histogram bucket boundaries for SDK duration metrics.

Ported from the Go and Java Cadence SDKs so that histograms recorded by this
client line up with the same client-side latency dashboards/alerts:

  - Go SDK:   internal/common/metrics/histograms.go, generates the boundaries
    algorithmically as an OTel-style exponential histogram.
    https://github.com/cadence-workflow/cadence-go-client/pull/1489
  - Java SDK: internal/metrics/HistogramBuckets.java, enumerates the same
    boundaries explicitly rather than generating them.
    https://github.com/cadence-workflow/cadence-java-client/pull/1048

This module follows the Java SDK's approach (explicit values) since Python has
no equivalent of the Go client's exponential-histogram builder to port.
"""

from typing import Callable, Sequence, Tuple

_NS_PER_MS = 1_000_000
_NS_PER_S = 1_000_000_000
_NS_PER_MIN = 60 * _NS_PER_S
_NS_PER_HOUR = 60 * _NS_PER_MIN


def _ms(*values: int) -> Tuple[int, ...]:
    return tuple(v * _NS_PER_MS for v in values)


def _s(*values: int) -> Tuple[int, ...]:
    return tuple(v * _NS_PER_S for v in values)


def _min(*values: int) -> Tuple[int, ...]:
    return tuple(v * _NS_PER_MIN for v in values)


def _h(*values: int) -> Tuple[int, ...]:
    return tuple(v * _NS_PER_HOUR for v in values)


# Default bucket configuration for most client-side latency metrics.
# Range: 1ms - 100s. 46 buckets.
# Use for: poll latency, execution latency, response latency, scheduled-to-start
# latency, and most other RPC call latencies.
DEFAULT_1MS_100S: Tuple[int, ...] = (
    *_ms(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
    *_ms(200, 300, 400, 500, 600, 700, 800, 900),
    *_s(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)

# Low-resolution version of DEFAULT_1MS_100S for high-cardinality metrics
# (e.g. per-activity-type or per-workflow-type tags). Range: 1ms - 100s. 16 buckets.
LOW_1MS_100S: Tuple[int, ...] = (
    *_ms(1, 2, 5, 10, 20, 50, 100, 200, 500),
    *_s(1, 2, 5, 10, 20, 50, 100),
)

# Bucket configuration for long-running operations. Range: 1ms - 24h. 27 buckets.
# Use for: workflow end-to-end latency, long-running activity execution latency.
HIGH_1MS_24H: Tuple[int, ...] = (
    *_ms(1, 2, 5, 10, 20, 50, 100, 200, 500),
    *_s(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
    *_min(20, 30),
    *_h(1, 2, 4, 8, 12, 24),
)

# Low-resolution version of HIGH_1MS_24H for high-cardinality long-running
# metrics (e.g. per-workflow-type end-to-end latency). Range: 1ms - 24h. 14 buckets.
MID_1MS_24H: Tuple[int, ...] = (
    *_ms(1, 10, 100),
    *_s(1, 10, 30),
    *_min(1, 5, 10, 30),
    *_h(1, 4, 12, 24),
)

DurationBucketResolver = Callable[[str], Sequence[int]]


def default_buckets_for_metric(metric_name: str) -> Tuple[int, ...]:
    """Pick a default bucket set for a `_ns`-suffixed duration metric name.

    Mirrors the Go/Java SDKs' own default selection: end-to-end latency metrics
    (typically long-running) get the wider 1ms-24h range, everything else uses
    the 1ms-100s range. Pass a different callable as
    ``PrometheusConfig.duration_bucket_resolver`` to change this, or set
    ``PrometheusConfig.histogram_buckets[metric_name]`` to override a single
    metric.
    """
    if "endtoend" in metric_name:
        return HIGH_1MS_24H
    return DEFAULT_1MS_100S
