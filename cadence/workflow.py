from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from cadence.client import Client

@dataclass
class WorkflowInfo:
    workflow_type: str
    workflow_domain: str
    workflow_id: str
    workflow_run_id: str

class WorkflowContext(ABC):
    _var: ContextVar['WorkflowContext'] = ContextVar("workflow")

    @abstractmethod
    def info(self) -> WorkflowInfo:
        ...

    @abstractmethod
    def client(self) -> Client:
        ...

    @contextmanager
    def _activate(self) -> Iterator[None]:
        token = WorkflowContext._var.set(self)
        yield None
        WorkflowContext._var.reset(token)

    @staticmethod
    def is_set() -> bool:
        return WorkflowContext._var.get(None) is not None

    @staticmethod
    def get() -> 'WorkflowContext':
        return WorkflowContext._var.get()
