"""
Cadence Python Client

A Python framework for authoring workflows and activities for Cadence.
"""

# Import main client functionality
from .client import Client
from .worker import Registry
from . import workflow
from .search_attributes import (
    SearchAttributeConverter,
    SearchAttributeValue,
    CADENCE_CHANGE_VERSION,
    validate_search_attributes,
)

__version__ = "0.1.0"

__all__ = [
    # Core
    "Client",
    "Registry",
    "workflow",
    # Search Attributes
    "SearchAttributeConverter",
    "SearchAttributeValue",
    "CADENCE_CHANGE_VERSION",
    "validate_search_attributes",
]
