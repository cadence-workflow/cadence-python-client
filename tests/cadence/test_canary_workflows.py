import pytest

from cadence import Registry, workflow
from cadence.testing import TestWorkflowEnvironment
from tests.integration_tests.canary import ALL_WORKFLOW_TYPES, registry
from tests.integration_tests.canary.constants import (
    ALL_SANITY_CHILD_WORKFLOWS,
    DEFAULT_EXCLUDED_SANITY_WORKFLOWS,
    DEFAULT_SANITY_CHILD_WORKFLOWS,
    WORKFLOW_TYPE_LOCAL_ACTIVITY,
    WORKFLOW_TYPE_SANITY,
)
from tests.integration_tests.canary.unsupported import UnsupportedCanaryError
import tests.integration_tests.canary.sanity as sanity_module


def test_canary_registry_contains_every_go_workflow_type() -> None:
    assert len(ALL_WORKFLOW_TYPES) == 19
    assert len(set(ALL_WORKFLOW_TYPES)) == len(ALL_WORKFLOW_TYPES)
    for workflow_type in ALL_WORKFLOW_TYPES:
        assert registry.get_workflow(workflow_type).name == workflow_type


def test_default_sanity_exclusions_are_explicit() -> None:
    assert set(DEFAULT_SANITY_CHILD_WORKFLOWS) == (
        set(ALL_SANITY_CHILD_WORKFLOWS) - DEFAULT_EXCLUDED_SANITY_WORKFLOWS
    )
    assert not (set(DEFAULT_SANITY_CHILD_WORKFLOWS) & DEFAULT_EXCLUDED_SANITY_WORKFLOWS)


async def test_unsupported_canary_fails_with_prerequisite() -> None:
    with TestWorkflowEnvironment(registry) as environment:
        execution = await environment.client.start_workflow(
            WORKFLOW_TYPE_LOCAL_ACTIVITY,
            task_list="canary-test",
        )

        error = environment.get_workflow_error(execution.workflow_id)
        assert isinstance(error, UnsupportedCanaryError)
        assert "local activities are not implemented" in str(error)


async def test_sanity_aggregates_child_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_workflow_type = "workflow.test.canary-failure"
    failing_registry = Registry()

    @failing_registry.workflow(name=failing_workflow_type)
    class FailingCanaryWorkflow:
        @workflow.run
        async def run(self) -> None:
            raise ValueError("expected canary failure")

    monkeypatch.setattr(
        sanity_module,
        "DEFAULT_SANITY_CHILD_WORKFLOWS",
        (failing_workflow_type,),
    )

    with TestWorkflowEnvironment(
        Registry.of(registry, failing_registry)
    ) as environment:
        execution = await environment.client.start_workflow(
            WORKFLOW_TYPE_SANITY,
            task_list="canary-test",
        )

        error = environment.get_workflow_error(execution.workflow_id)
        assert isinstance(error, RuntimeError)
        assert failing_workflow_type in str(error)
        assert "expected canary failure" in str(error)
