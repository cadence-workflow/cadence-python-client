#!/usr/bin/env python3
"""
Workflow and Activity Registry for Cadence Python Client.

This module provides a registry system for managing workflows and activities,
similar to the Go client's registry.go implementation.
"""

import logging
from typing import Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """Base exception for registry operations."""
    pass


class WorkflowNotFoundError(RegistryError):
    """Raised when a workflow is not found in the registry."""
    pass


class ActivityNotFoundError(RegistryError):
    """Raised when an activity is not found in the registry."""
    pass


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register a duplicate workflow or activity."""
    pass


class Registry:
    """
    Registry for managing workflows and activities.
    
    This class provides functionality to register, retrieve, and manage
    workflows and activities in a Cadence application.
    """
    
    def __init__(self, next_registry: Optional['Registry'] = None):
        """
        Initialize the registry.
        
        Args:
            next_registry: Optional next registry in the chain for delegation
        """
        self._workflows: Dict[str, Callable] = {}
        self._activities: Dict[str, Callable] = {}
        self._workflow_aliases: Dict[str, str] = {}  # alias -> name mapping
        self._activity_aliases: Dict[str, str] = {}  # alias -> name mapping
        self._next_registry = next_registry
        
    def register_workflow(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        alias: Optional[str] = None
    ) -> Callable:
        """
        Register a workflow function.
        
        This method can be used as a decorator or called directly.
        
        Args:
            func: The workflow function to register
            name: Name of the workflow (defaults to function name)
            alias: Alternative name for the workflow
            
        Returns:
            The decorated function or the function itself
            
        Raises:
            DuplicateRegistrationError: If workflow name already exists
        """
        def decorator(f: Callable) -> Callable:
            workflow_name = name or f.__name__
            
            if workflow_name in self._workflows:
                raise DuplicateRegistrationError(
                    f"Workflow '{workflow_name}' is already registered"
                )
            
            self._workflows[workflow_name] = f
            
            # Register alias if provided
            if alias:
                if alias in self._workflow_aliases:
                    raise DuplicateRegistrationError(
                        f"Workflow alias '{alias}' is already registered"
                    )
                self._workflow_aliases[alias] = workflow_name
            
            logger.info(f"Registered workflow '{workflow_name}'")
            return f
        
        if func is None:
            return decorator
        return decorator(func)
    
    def register_activity(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        alias: Optional[str] = None
    ) -> Callable:
        """
        Register an activity function.
        
        This method can be used as a decorator or called directly.
        
        Args:
            func: The activity function to register
            name: Name of the activity (defaults to function name)
            alias: Alternative name for the activity
            
        Returns:
            The decorated function or the function itself
            
        Raises:
            DuplicateRegistrationError: If activity name already exists
        """
        def decorator(f: Callable) -> Callable:
            activity_name = name or f.__name__
            
            if activity_name in self._activities:
                raise DuplicateRegistrationError(
                    f"Activity '{activity_name}' is already registered"
                )
            
            self._activities[activity_name] = f
            
            # Register alias if provided
            if alias:
                if alias in self._activity_aliases:
                    raise DuplicateRegistrationError(
                        f"Activity alias '{alias}' is already registered"
                    )
                self._activity_aliases[alias] = activity_name
            
            logger.info(f"Registered activity '{activity_name}'")
            return f
        
        if func is None:
            return decorator
        return decorator(func)
    
    def get_workflow(self, name: str) -> Callable:
        """
        Get a registered workflow by name.
        
        Args:
            name: Name or alias of the workflow
            
        Returns:
            The workflow function
            
        Raises:
            WorkflowNotFoundError: If workflow is not found
        """
        # Check if it's an alias
        actual_name = self._workflow_aliases.get(name, name)
        
        if actual_name in self._workflows:
            return self._workflows[actual_name]
        
        # Try the next registry in the chain if available
        if self._next_registry:
            try:
                return self._next_registry.get_workflow(name)
            except WorkflowNotFoundError:
                pass
        
        raise WorkflowNotFoundError(f"Workflow '{name}' not found in registry")
    
    def get_activity(self, name: str) -> Callable:
        """
        Get a registered activity by name.
        
        Args:
            name: Name or alias of the activity
            
        Returns:
            The activity function
            
        Raises:
            ActivityNotFoundError: If activity is not found
        """
        # Check if it's an alias
        actual_name = self._activity_aliases.get(name, name)
        
        if actual_name in self._activities:
            return self._activities[actual_name]
        
        # Try the next registry in the chain if available
        if self._next_registry:
            try:
                return self._next_registry.get_activity(name)
            except ActivityNotFoundError:
                pass
        
        raise ActivityNotFoundError(f"Activity '{name}' not found in registry")
    
    def list_workflows(self) -> List[str]:
        """
        Get a list of all registered workflow names.
        
        Returns:
            List of workflow names
        """
        workflows = list(self._workflows.keys())
        if self._next_registry:
            workflows.extend(self._next_registry.list_workflows())
        return workflows
    
    def list_activities(self) -> List[str]:
        """
        Get a list of all registered activity names.
        
        Returns:
            List of activity names
        """
        activities = list(self._activities.keys())
        if self._next_registry:
            activities.extend(self._next_registry.list_activities())
        return activities
    
    def list_workflow_aliases(self) -> Dict[str, str]:
        """
        Get a mapping of workflow aliases to actual names.
        
        Returns:
            Dictionary mapping aliases to workflow names
        """
        return self._workflow_aliases.copy()
    
    def list_activity_aliases(self) -> Dict[str, str]:
        """
        Get a mapping of activity aliases to actual names.
        
        Returns:
            Dictionary mapping aliases to activity names
        """
        return self._activity_aliases.copy()
    
    def unregister_workflow(self, name: str) -> bool:
        """
        Unregister a workflow.
        
        Args:
            name: Name or alias of the workflow to unregister
            
        Returns:
            True if workflow was unregistered, False if not found
        """
        # Check if it's an alias
        actual_name = self._workflow_aliases.get(name, name)
        
        if actual_name in self._workflows:
            del self._workflows[actual_name]
            
            # Remove any aliases pointing to this workflow
            aliases_to_remove = [
                alias for alias, workflow_name in self._workflow_aliases.items()
                if workflow_name == actual_name
            ]
            for alias in aliases_to_remove:
                del self._workflow_aliases[alias]
            
            logger.info(f"Unregistered workflow '{actual_name}'")
            return True
        
        return False
    
    def unregister_activity(self, name: str) -> bool:
        """
        Unregister an activity.
        
        Args:
            name: Name or alias of the activity to unregister
            
        Returns:
            True if activity was unregistered, False if not found
        """
        # Check if it's an alias
        actual_name = self._activity_aliases.get(name, name)
        
        if actual_name in self._activities:
            del self._activities[actual_name]
            
            # Remove any aliases pointing to this activity
            aliases_to_remove = [
                alias for alias, activity_name in self._activity_aliases.items()
                if activity_name == actual_name
            ]
            for alias in aliases_to_remove:
                del self._activity_aliases[alias]
            
            logger.info(f"Unregistered activity '{actual_name}'")
            return True
        
        return False
    
    def clear(self):
        """Clear all registered workflows and activities."""
        self._workflows.clear()
        self._activities.clear()
        self._workflow_aliases.clear()
        self._activity_aliases.clear()
        logger.info("Registry cleared")
    
    def get_workflow_count(self) -> int:
        """
        Get the total number of registered workflows in this registry.
        
        Note: This only counts workflows in this registry, not in chained registries.
        Use get_total_workflow_count() to get the total count across all chained registries.
        """
        return len(self._workflows)
    
    def get_activity_count(self) -> int:
        """
        Get the total number of registered activities in this registry.
        
        Note: This only counts activities in this registry, not in chained registries.
        Use get_total_workflow_count() to get the total count across all chained registries.
        """
        return len(self._activities)
    
    def get_total_workflow_count(self) -> int:
        """Get the total number of registered workflows across all chained registries."""
        count = len(self._workflows)
        if self._next_registry:
            count += self._next_registry.get_total_workflow_count()
        return count
    
    def get_total_activity_count(self) -> int:
        """Get the total number of registered activities across all chained registries."""
        count = len(self._activities)
        if self._next_registry:
            count += self._next_registry.get_total_activity_count()
        return count
    
    def has_workflow(self, name: str) -> bool:
        """
        Check if a workflow is registered in this registry or any chained registries.
        
        Args:
            name: Name or alias of the workflow
            
        Returns:
            True if workflow exists anywhere in the chain, False otherwise
        """
        actual_name = self._workflow_aliases.get(name, name)
        if actual_name in self._workflows:
            return True
        
        # Check the next registry in the chain if available
        if self._next_registry:
            return self._next_registry.has_workflow(name)
        
        return False
    
    def has_activity(self, name: str) -> bool:
        """
        Check if an activity is registered in this registry or any chained registries.
        
        Args:
            name: Name or alias of the activity
            
        Returns:
            True if activity exists anywhere in the chain, False otherwise
        """
        actual_name = self._activity_aliases.get(name, name)
        if actual_name in self._activities:
            return True
        
        # Check the next registry in the chain if available
        if self._next_registry:
            return self._next_registry.has_activity(name)
        
        return False

    def set_next_registry(self, next_registry: 'Registry') -> None:
        """
        Set the next registry in the chain.
        
        Args:
            next_registry: The registry to chain to
        """
        self._next_registry = next_registry
    
    def get_next_registry(self) -> Optional['Registry']:
        """
        Get the next registry in the chain.
        
        Returns:
            The next registry or None if no chaining
        """
        return self._next_registry
    
    def has_next_registry(self) -> bool:
        """
        Check if this registry has a next registry in the chain.
        
        Returns:
            True if there is a next registry, False otherwise
        """
        return self._next_registry is not None


# Global registry instance
registry = Registry()

def new_registry() -> Registry:
    """
    Create a new registry that automatically chains to the global registry.
    
    This follows the Go client pattern where new registries automatically
    delegate to the global registry when items are not found locally.
    
    Returns:
        A new Registry instance chained to the global registry
    """
    return Registry(next_registry=registry)


# Convenience functions for using the global registry
def register_workflow(
    func: Optional[Callable] = None,
    **kwargs
) -> Callable:
    """Register a workflow with the global registry."""
    return registry.register_workflow(func, **kwargs)


def register_activity(
    func: Optional[Callable] = None,
    **kwargs
) -> Callable:
    """Register an activity with the global registry."""
    return registry.register_activity(func, **kwargs)


def get_workflow(name: str) -> Callable:
    """Get a workflow from the global registry."""
    return registry.get_workflow(name)


def get_activity(name: str) -> Callable:
    """Get an activity from the global registry."""
    return registry.get_activity(name)


def list_workflows() -> List[str]:
    """List all workflows in the global registry."""
    return registry.list_workflows()


def list_activities() -> List[str]:
    """List all activities in the global registry."""
    return registry.list_activities()


def has_workflow(name: str) -> bool:
    """Check if a workflow exists in the global registry."""
    return registry.has_workflow(name)


def has_activity(name: str) -> bool:
    """Check if an activity exists in the global registry."""
    return registry.has_activity(name)


def get_total_workflow_count() -> int:
    """Get the total number of workflows across all chained registries."""
    return registry.get_total_workflow_count()


def get_total_activity_count() -> int:
    """Get the total number of activities across all chained registries."""
    return registry.get_total_activity_count()


def clear_registry():
    """Clear the global registry."""
    registry.clear()


# Export the main classes and functions
__all__ = [
    'Registry',
    'RegistryError',
    'WorkflowNotFoundError',
    'ActivityNotFoundError',
    'DuplicateRegistrationError',
    'registry',
    'new_registry',
    'register_workflow',
    'register_activity',
    'get_workflow',
    'get_activity',
    'list_workflows',
    'list_activities',
    'has_workflow',
    'has_activity',
    'get_total_workflow_count',
    'get_total_activity_count',
    'clear_registry',
]
