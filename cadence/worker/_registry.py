#!/usr/bin/env python3
"""
Workflow and Activity Registry for Cadence Python Client.

This module provides a registry system for managing workflows and activities,
similar to the Go client's registry.go implementation.
"""

import logging
from typing import (
    Callable,
    Dict,
    Optional,
    Unpack,
    overload,
    Type,
    Union,
    TypeVar,
    Awaitable,
    ParamSpec,
    Any,
    Sequence,
)

from cadence._internal.activity._definition import BaseDefinition
from cadence.activity import (
    ActivityDefinitionOptions,
    ActivityDefinition,
    ActivityDecorator,
    P,
    R,
    _AsyncActivityDefinition,
    _SyncActivityDefinition,
)
from cadence.workflow import (
    WorkflowDefinition,
    WorkflowDefinitionOptions,
    WorkflowDecorator,
)

logger = logging.getLogger(__name__)

# TypeVar for workflow class types
W = TypeVar("W")

_P1 = ParamSpec("_P1")
_T1 = TypeVar("_T1")
_P2 = ParamSpec("_P2")
_T2 = TypeVar("_T2")


class Registry:
    """
    Registry for managing workflows and activities.

    This class provides functionality to register, retrieve, and manage
    workflows and activities in a Cadence application.
    """

    def __init__(self) -> None:
        """Initialize the registry."""
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._activities: Dict[str, ActivityDefinition] = {}

    @overload
    def workflow(self, cls: Type[W]) -> Type[W]: ...
    @overload
    def workflow(
        self, **kwargs: Unpack[WorkflowDefinitionOptions]
    ) -> WorkflowDecorator: ...

    def workflow(
        self, cls: Optional[Type[W]] = None, **kwargs: Unpack[WorkflowDefinitionOptions]
    ) -> Union[Type[W], WorkflowDecorator]:
        """
        Register a workflow class.

        This method can be used as a decorator or called directly.
        Only supports class-based workflows.

        Args:
            cls: The workflow class to register
            **kwargs: Options for registration (name, alias)

        Returns:
            The decorated class

        Raises:
            KeyError: If workflow name already exists
            ValueError: If class workflow is invalid
        """
        options = WorkflowDefinitionOptions(**kwargs)

        decorator = WorkflowDecorator(options, self._register_workflow)

        if cls is None:
            return decorator
        return decorator(cls)

    def _register_workflow(self, defn: WorkflowDefinition) -> None:
        if defn.name in self._workflows:
            raise KeyError(f"Workflow '{defn.name}' is already registered")

        self._workflows[defn.name] = defn

    # Order matters, Async must be first
    @overload
    def activity(
        self, func: Callable[P, Awaitable[R]]
    ) -> _AsyncActivityDefinition[P, R]: ...
    @overload
    def activity(self, func: Callable[P, R]) -> _SyncActivityDefinition[P, R]: ...
    @overload
    def activity(
        self, **kwargs: Unpack[ActivityDefinitionOptions]
    ) -> ActivityDecorator: ...

    def activity(
        self,
        func: Union[Callable[_P1, _T1], Callable[_P2, Awaitable[_T2]], None] = None,
        **kwargs: Unpack[ActivityDefinitionOptions],
    ) -> Union[
        ActivityDecorator,
        _SyncActivityDefinition[_P1, _T1],
        _AsyncActivityDefinition[_P2, _T2],
    ]:
        """
        Register an activity function.

        This method can be used as a decorator or called directly.

        Args:
            func: The activity function to register
            **kwargs: Options for registration (name, alias)

        Returns:
            The decorated function or the function itself

        Raises:
            KeyError: If activity name already exists
        """
        options = ActivityDefinitionOptions(**kwargs)
        decorator = ActivityDecorator(options, self._register_activity)

        if func is not None:
            return decorator(func)

        return decorator

    def register_activities(self, obj: object) -> None:
        activities = _find_activity_definitions(obj)
        if not activities:
            raise ValueError(f"No activity definitions found in '{repr(obj)}'")

        for defn in activities:
            self._register_activity(defn)

    def register_activity(self, defn: ActivityDefinition[Any, Any]) -> None:
        if not isinstance(defn, BaseDefinition):
            raise ValueError(f"{defn} must have @activity.defn decorator")
        self._register_activity(defn)

    def _register_activity(self, defn: ActivityDefinition[Any, Any]) -> None:
        if defn.name in self._activities:
            raise KeyError(f"Activity '{defn.name}' is already registered")

        self._activities[defn.name] = defn

    def get_workflow(self, name: str) -> WorkflowDefinition:
        """
        Get a registered workflow by name.

        Args:
            name: Name or alias of the workflow

        Returns:
            The workflow definition

        Raises:
            KeyError: If workflow is not found
        """

        return self._workflows[name]

    def get_activity(self, name: str) -> ActivityDefinition:
        """
        Get a registered activity by name.

        Args:
            name: Name or alias of the activity

        Returns:
            The activity function

        Raises:
            KeyError: If activity is not found
        """
        return self._activities[name]

    def __add__(self, other: "Registry") -> "Registry":
        result = Registry()
        for name, fn in self._activities.items():
            result._register_activity(fn)
        for name, fn in other._activities.items():
            result._register_activity(fn)
        for name, workflow in self._workflows.items():
            result._register_workflow(workflow)
        for name, workflow in other._workflows.items():
            result._register_workflow(workflow)

        return result

    @staticmethod
    def of(*args: "Registry") -> "Registry":
        result = Registry()
        for other in args:
            result += other

        return result


def _find_activity_definitions(instance: object) -> Sequence[ActivityDefinition]:
    attr_to_def: dict[str, BaseDefinition] = {}
    for attr in dir(instance):
        if attr.startswith("_"):
            continue
        value = getattr(instance, attr)
        if isinstance(value, BaseDefinition):
            attr_to_def[attr] = value

    return list(attr_to_def.values())
