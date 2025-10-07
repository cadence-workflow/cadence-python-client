#!/usr/bin/env python3
"""
Workflow and Activity Registry for Cadence Python Client.

This module provides a registry system for managing workflows and activities,
similar to the Go client's registry.go implementation.
"""

import logging
from typing import Callable, Dict, Optional, Unpack, TypedDict, Sequence, overload
from cadence.activity import ActivityDefinitionOptions, ActivityDefinition, ActivityDecorator, P, T
from cadence.workflow import WorkflowDefinition, WorkflowDefinitionOptions

logger = logging.getLogger(__name__)


class RegisterWorkflowOptions(TypedDict, total=False):
    """Options for registering a workflow."""
    name: Optional[str]
    alias: Optional[str]

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
        self._workflow_aliases: Dict[str, str] = {}  # alias -> name mapping

    def workflow(
        self,
        func: Optional[Callable] = None,
        **kwargs: Unpack[RegisterWorkflowOptions]
    ) -> Callable:
        """
        Register a workflow function.
        
        This method can be used as a decorator or called directly.
        
        Args:
            func: The workflow function to register
            **kwargs: Options for registration (name, alias)
            
        Returns:
            The decorated function or the function itself
            
        Raises:
            KeyError: If workflow name already exists
        """
        options = RegisterWorkflowOptions(**kwargs)
        
        def decorator(f: Callable) -> Callable:
            workflow_name = options.get('name') or f.__name__
            
            if workflow_name in self._workflows:
                raise KeyError(f"Workflow '{workflow_name}' is already registered")
            
            # Create WorkflowDefinition with type information
            workflow_opts = WorkflowDefinitionOptions(name=workflow_name)
            workflow_def = WorkflowDefinition.wrap(f, workflow_opts)
            self._workflows[workflow_name] = workflow_def
            
            # Register alias if provided
            alias = options.get('alias')
            if alias:
                if alias in self._workflow_aliases:
                    raise KeyError(f"Workflow alias '{alias}' is already registered")
                self._workflow_aliases[alias] = workflow_name
            
            logger.info(f"Registered workflow '{workflow_name}'")
            return f
        
        if func is None:
            return decorator
        return decorator(func)

    @overload
    def activity(self, func: Callable[P, T]) -> ActivityDefinition[P, T]:
        ...

    @overload
    def activity(self, **kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator:
        ...
    
    def activity(self, func: Callable[P, T] | None = None, **kwargs: Unpack[ActivityDefinitionOptions]) -> ActivityDecorator | ActivityDefinition[P, T]:
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

        def decorator(f: Callable[P, T]) -> ActivityDefinition[P, T]:
            defn = ActivityDefinition.wrap(f, options)

            self._register_activity(defn)

            return defn

        if func is not None:
            return decorator(func)

        return decorator

    def register_activities(self, obj: object) -> None:
        activities = _find_activity_definitions(obj)
        if not activities:
            raise ValueError(f"No activity definitions found in '{repr(obj)}'")

        for defn in activities:
            self._register_activity(defn)


    def register_activity(self, defn: Callable) -> None:
        if not isinstance(defn, ActivityDefinition):
            raise ValueError(f"{defn.__qualname__} must have @activity.defn decorator")
        self._register_activity(defn)

    def _register_activity(self, defn: ActivityDefinition) -> None:
        if defn.name in self._activities:
            raise KeyError(f"Activity '{defn.name}' is already registered")

        self._activities[defn.name] = defn

    
    def get_workflow(self, name: str) -> WorkflowDefinition:
        """
        Get a registered workflow by name.
        
        Args:
            name: Name or alias of the workflow
            
        Returns:
            The workflow definition with type information
            
        Raises:
            KeyError: If workflow is not found
        """
        # Check if it's an alias
        actual_name = self._workflow_aliases.get(name, name)
        
        if actual_name not in self._workflows:
            raise KeyError(f"Workflow '{name}' not found in registry")
        
        return self._workflows[actual_name]
    
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

    def __add__(self, other: 'Registry') -> 'Registry':
        result = Registry()
        for name, fn in self._activities.items():
            result._register_activity(fn)
        for name, fn in other._activities.items():
            result._register_activity(fn)

        return result

    @staticmethod
    def of(*args: 'Registry') -> 'Registry':
        result = Registry()
        for other in args:
            result += other

        return result

def _find_activity_definitions(instance: object) -> Sequence[ActivityDefinition]:
    attr_to_def = {}
    for t in instance.__class__.__mro__:
        for attr in dir(t):
            if attr.startswith("_"):
                continue
            value = getattr(t, attr)
            if isinstance(value, ActivityDefinition):
                if attr in attr_to_def:
                    raise ValueError(f"'{attr}' was overridden with a duplicate activity definition")
                attr_to_def[attr] = value

    # Create new definitions, copying the attributes from the declaring type but using the function
    # from the specific object. This allows for the decorator to be applied to the base class and the
    # function to be overridden
    result = []
    for attr, definition in attr_to_def.items():
        result.append(ActivityDefinition(getattr(instance, attr), definition.name, definition.strategy, definition.params))

    return result


    