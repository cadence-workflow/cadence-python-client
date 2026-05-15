"""
Cadence Python Client

A Python framework for authoring workflows and activities for Cadence.
"""

# Import main client functionality
from .client import Client
from .schedule_handle import ScheduleHandle
from .worker import Registry
from . import workflow

__version__ = "0.1.0"

__all__ = [
    "Client",
    "ScheduleHandle",
    "Registry",
    "workflow",
]
