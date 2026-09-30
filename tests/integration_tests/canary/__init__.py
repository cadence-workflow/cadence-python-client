from cadence import Registry

from tests.integration_tests.canary.cancellation import cancellation_registry
from tests.integration_tests.canary.concurrent_exec import concurrent_exec_registry
from tests.integration_tests.canary.constants import (
    ALL_WORKFLOW_TYPES,
    WORKFLOW_TYPE_SANITY,
)
from tests.integration_tests.canary.cron import cron_registry
from tests.integration_tests.canary.echo import echo_registry
from tests.integration_tests.canary.history_archival import history_archival_registry
from tests.integration_tests.canary.local_activity import local_activity_registry
from tests.integration_tests.canary.query import query_registry
from tests.integration_tests.canary.reset import reset_registry
from tests.integration_tests.canary.retry import retry_registry
from tests.integration_tests.canary.sanity import sanity_registry
from tests.integration_tests.canary.search_attributes import (
    search_attributes_registry,
)
from tests.integration_tests.canary.signal import signal_registry
from tests.integration_tests.canary.timeout import timeout_registry
from tests.integration_tests.canary.visibility import visibility_registry
from tests.integration_tests.canary.visibility_archival import (
    visibility_archival_registry,
)

registry = Registry.of(
    cancellation_registry,
    concurrent_exec_registry,
    cron_registry,
    echo_registry,
    history_archival_registry,
    local_activity_registry,
    query_registry,
    reset_registry,
    retry_registry,
    sanity_registry,
    search_attributes_registry,
    signal_registry,
    timeout_registry,
    visibility_registry,
    visibility_archival_registry,
)

__all__ = ["ALL_WORKFLOW_TYPES", "WORKFLOW_TYPE_SANITY", "registry"]
