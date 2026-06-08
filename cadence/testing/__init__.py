"""Testing utilities for Cadence workflows.

Provides an in-memory :class:`TestWorkflowEnvironment` that runs workflow code
without a Cadence server, exposing a :class:`MockClient` that implements the
public ``Client`` interface.
"""

from cadence.testing._workflow_environment import (
    TestWorkflowEnvironment,
)

__all__ = [
    "TestWorkflowEnvironment",
]
