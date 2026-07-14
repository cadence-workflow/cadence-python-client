"""Context propagation interfaces for Cadence workflow boundaries.

Propagators carry application-owned, request-scoped metadata through Cadence
headers. Implementations commonly use :mod:`contextvars` so values are scoped
to each client, workflow, or activity invocation.
"""

from collections.abc import Mapping
from typing import ContextManager, Protocol

from cadence.error import ContextPropagationError

__all__ = ["ContextPropagationError", "ContextPropagator"]


class ContextPropagator(Protocol):
    """Serialize and scope application context across Cadence boundaries.

    ``inject`` is called before the SDK writes a Cadence header. ``extract`` is
    called for an incoming header and must return a context manager that restores
    any ambient state when its scope exits.

    Workflow-side ``inject`` calls are replay-sensitive: implementations must
    return identical bytes for identical persisted workflow state.
    """

    def inject(self) -> Mapping[str, bytes]:
        """Return the current context as opaque header fields."""

    def extract(self, headers: Mapping[str, bytes]) -> ContextManager[None]:
        """Return a scope that installs context decoded from ``headers``."""
