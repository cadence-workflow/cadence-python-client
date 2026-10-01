"""
Cadence Python Client

A Python framework for authoring workflows and activities for Cadence.
"""

# Import main client functionality
from .auth import (
    AuthorizationProvider,
    CallableAuthorizationProvider,
    StaticAuthorizationProvider,
)
from .client import Client
from .context import ContextPropagator, ContextVarPropagator
from .worker import Registry
from . import workflow

__version__ = "0.1.0"

__all__ = [
    "AuthorizationProvider",
    "CallableAuthorizationProvider",
    "Client",
    "ContextPropagator",
    "ContextVarPropagator",
    "Registry",
    "StaticAuthorizationProvider",
    "workflow",
]
