from datetime import timedelta

ACTIVITY_TYPE_ECHO = "activity.echo"
ACTIVITY_TYPE_SIGNAL = "activity.signal"
ACTIVITY_TYPE_CONCURRENT_EXECUTION = "activity.concurrent-execution"
ACTIVITY_TYPE_QUERY_ONE = "activity.query1"
ACTIVITY_TYPE_QUERY_TWO = "activity.query2"
ACTIVITY_TYPE_TIMEOUT = "activity.timeout"
ACTIVITY_TYPE_RETRY_ON_TIMEOUT = "activity.retry-on-timeout"
ACTIVITY_TYPE_RETRY_ON_FAILURE = "activity.retry-on-failure"
ACTIVITY_TYPE_CRON = "activity.cron"

WORKFLOW_TYPE_CRON = "workflow.cron"
WORKFLOW_TYPE_ECHO = "workflow.echo"
WORKFLOW_TYPE_SANITY = "workflow.sanity"
WORKFLOW_TYPE_SIGNAL = "workflow.signal"
WORKFLOW_TYPE_SIGNAL_EXTERNAL = "workflow.signal.external"
WORKFLOW_TYPE_VISIBILITY = "workflow.visibility"
WORKFLOW_TYPE_SEARCH_ATTRIBUTES = "workflow.searchAttributes"
WORKFLOW_TYPE_CONCURRENT_EXECUTION = "workflow.concurrent-execution"
WORKFLOW_TYPE_QUERY = "workflow.query"
WORKFLOW_TYPE_TIMEOUT = "workflow.timeout"
WORKFLOW_TYPE_LOCAL_ACTIVITY = "workflow.localactivity"
WORKFLOW_TYPE_CANCELLATION = "workflow.cancellation"
WORKFLOW_TYPE_CANCELLATION_EXTERNAL = "workflow.cancellation.external"
WORKFLOW_TYPE_RETRY = "workflow.retry"
WORKFLOW_TYPE_RESET = "workflow.reset"
WORKFLOW_TYPE_RESET_BASE = "workflow.reset.base"
WORKFLOW_TYPE_HISTORY_ARCHIVAL = "workflow.archival.history"
WORKFLOW_TYPE_VISIBILITY_ARCHIVAL = "workflow.archival.visibility"
WORKFLOW_TYPE_ARCHIVAL_EXTERNAL = "workflow.archival.external"

ACTIVITY_TIMEOUT = timedelta(seconds=10)
CHILD_WORKFLOW_TIMEOUT = timedelta(minutes=2)
SANITY_WORKFLOW_TIMEOUT = timedelta(minutes=5)

ALL_SANITY_CHILD_WORKFLOWS = (
    WORKFLOW_TYPE_ECHO,
    WORKFLOW_TYPE_SIGNAL,
    WORKFLOW_TYPE_VISIBILITY,
    WORKFLOW_TYPE_SEARCH_ATTRIBUTES,
    WORKFLOW_TYPE_CONCURRENT_EXECUTION,
    WORKFLOW_TYPE_QUERY,
    WORKFLOW_TYPE_TIMEOUT,
    WORKFLOW_TYPE_LOCAL_ACTIVITY,
    WORKFLOW_TYPE_CANCELLATION,
    WORKFLOW_TYPE_RETRY,
    WORKFLOW_TYPE_RESET,
    WORKFLOW_TYPE_HISTORY_ARCHIVAL,
    WORKFLOW_TYPE_VISIBILITY_ARCHIVAL,
)

DEFAULT_EXCLUDED_SANITY_WORKFLOWS = frozenset(
    {
        WORKFLOW_TYPE_VISIBILITY,
        WORKFLOW_TYPE_SEARCH_ATTRIBUTES,
        WORKFLOW_TYPE_LOCAL_ACTIVITY,
        WORKFLOW_TYPE_RESET,
        WORKFLOW_TYPE_HISTORY_ARCHIVAL,
        WORKFLOW_TYPE_VISIBILITY_ARCHIVAL,
    }
)

DEFAULT_SANITY_CHILD_WORKFLOWS = tuple(
    workflow_type
    for workflow_type in ALL_SANITY_CHILD_WORKFLOWS
    if workflow_type not in DEFAULT_EXCLUDED_SANITY_WORKFLOWS
)

ALL_WORKFLOW_TYPES = (
    WORKFLOW_TYPE_CRON,
    WORKFLOW_TYPE_SANITY,
    WORKFLOW_TYPE_ECHO,
    WORKFLOW_TYPE_SIGNAL,
    WORKFLOW_TYPE_SIGNAL_EXTERNAL,
    WORKFLOW_TYPE_VISIBILITY,
    WORKFLOW_TYPE_SEARCH_ATTRIBUTES,
    WORKFLOW_TYPE_CONCURRENT_EXECUTION,
    WORKFLOW_TYPE_QUERY,
    WORKFLOW_TYPE_TIMEOUT,
    WORKFLOW_TYPE_LOCAL_ACTIVITY,
    WORKFLOW_TYPE_CANCELLATION,
    WORKFLOW_TYPE_CANCELLATION_EXTERNAL,
    WORKFLOW_TYPE_RETRY,
    WORKFLOW_TYPE_RESET,
    WORKFLOW_TYPE_RESET_BASE,
    WORKFLOW_TYPE_HISTORY_ARCHIVAL,
    WORKFLOW_TYPE_VISIBILITY_ARCHIVAL,
    WORKFLOW_TYPE_ARCHIVAL_EXTERNAL,
)

UNSUPPORTED_WORKFLOW_REASONS = {
    WORKFLOW_TYPE_VISIBILITY: (
        "requires a public Python visibility client or configured raw visibility stub"
    ),
    WORKFLOW_TYPE_SEARCH_ATTRIBUTES: (
        "requires advanced visibility and an indexed CustomKeywordField"
    ),
    WORKFLOW_TYPE_LOCAL_ACTIVITY: "local activities are not implemented by this SDK",
    WORKFLOW_TYPE_RESET: "requires the reset API and long-running reset test setup",
    WORKFLOW_TYPE_RESET_BASE: "is an internal helper for the unsupported reset canary",
    WORKFLOW_TYPE_HISTORY_ARCHIVAL: (
        "requires an archival-enabled domain and archival worker"
    ),
    WORKFLOW_TYPE_VISIBILITY_ARCHIVAL: (
        "requires visibility archival and an archival-enabled domain"
    ),
    WORKFLOW_TYPE_ARCHIVAL_EXTERNAL: (
        "requires an archival-enabled domain and archival worker"
    ),
}
