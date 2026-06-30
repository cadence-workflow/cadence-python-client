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
