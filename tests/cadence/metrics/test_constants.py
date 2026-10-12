"""Tests for metrics constants — tag keys and metric names match Go SDK."""

from cadence.metrics.constants import (
    # Tag keys
    TAG_DOMAIN,
    TAG_TASK_LIST,
    TAG_WORKFLOW_TYPE,
    TAG_ACTIVITY_TYPE,
    TAG_WORKFLOW_ID,
    TAG_RUN_ID,
    TAG_ATTEMPT,
    TAG_WORKER_TYPE,
    CADENCE_METRICS_PREFIX,
    STICKY_CACHE_HIT,
    STICKY_CACHE_MISS,
    STICKY_CACHE_EVICT,
    STICKY_CACHE_STALL,
    STICKY_CACHE_SIZE,
)


class TestTagConstants:
    def test_tag_keys_match_go_sdk(self):
        assert TAG_DOMAIN == "Domain"
        assert TAG_TASK_LIST == "TaskList"
        assert TAG_WORKFLOW_TYPE == "WorkflowType"
        assert TAG_ACTIVITY_TYPE == "ActivityType"
        assert TAG_WORKFLOW_ID == "WorkflowID"
        assert TAG_RUN_ID == "RunID"
        assert TAG_ATTEMPT == "Attempt"
        assert TAG_WORKER_TYPE == "WorkerType"

    def test_metric_name_prefix(self):
        assert CADENCE_METRICS_PREFIX == "cadence-"


class TestStickyCacheMetricConstants:
    def test_sticky_cache_metric_names_match_go_sdk(self):
        assert STICKY_CACHE_HIT == "cadence-sticky-cache-hit"
        assert STICKY_CACHE_MISS == "cadence-sticky-cache-miss"
        assert STICKY_CACHE_EVICT == "cadence-sticky-cache-evict"
        assert STICKY_CACHE_STALL == "cadence-sticky-cache-stall"
        assert STICKY_CACHE_SIZE == "cadence-sticky-cache-size"
