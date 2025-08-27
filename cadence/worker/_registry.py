#!/usr/bin/env python3
"""
Workflow and Activity Registry for Cadence Python Client.

This module provides a registry system for managing workflows and activities,
similar to the Go client's registry.go implementation.
"""

import logging
from typing import Callable, Dict, Optional
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class RegisterWorkflowOptions:
    """Options for registering a workflow."""
    name: Optional[str] = None
    alias: Optional[str] = None


@dataclass
class RegisterActivityOptions:
    """Options for registering an activity."""
    name: Optional[str] = None
    alias: Optional[str] = None


class Registry:
    """
    Registry for managing workflows and activities.
    
    This class provides functionality to register, retrieve, and manage
    workflows and activities in a Cadence application.
    """
    
    def __init__(self):
        """Initialize the registry."""
        self._workflows: Dict[str, Callable] = {}
        self._activities: Dict[str, Callable] = {}
        self._workflow_aliases: Dict[str, str] = {}  # alias -> name mapping
        self._activity_aliases: Dict[str, str] = {}  # alias -> name mapping
        
    def workflow(
        self,
        func: Optional[Callable] = None,
        **kwargs: RegisterWorkflowOptions
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
            workflow_name = options.name or f.__name__
            
            if workflow_name in self._workflows:
                raise KeyError(f"Workflow '{workflow_name}' is already registered")
            
            self._workflows[workflow_name] = f
            
            # Register alias if provided
            if options.alias:
                if options.alias in self._workflow_aliases:
                    raise KeyError(f"Workflow alias '{options.alias}' is already registered")
                self._workflow_aliases[options.alias] = workflow_name
            
            logger.info(f"Registered workflow '{workflow_name}'")
            return f
        
        if func is None:
            return decorator
        return decorator(func)
    
    def activity(
        self,
        func: Optional[Callable] = None,
        **kwargs: RegisterActivityOptions
    ) -> Callable:
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
        options = RegisterActivityOptions(**kwargs)
        
        def decorator(f: Callable) -> Callable:
            activity_name = options.name or f.__name__
            
            if activity_name in self._activities:
                raise KeyError(f"Activity '{activity_name}' is already registered")
            
            self._activities[activity_name] = f
            
            # Register alias if provided
            if options.alias:
                if options.alias in self._activity_aliases:
                    raise KeyError(f"Activity alias '{options.alias}' is already registered")
                self._activity_aliases[options.alias] = activity_name
            
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
            KeyError: If workflow is not found
        """
        # Check if it's an alias
        actual_name = self._workflow_aliases.get(name, name)
        
        if actual_name not in self._workflows:
            raise KeyError(f"Workflow '{name}' not found in registry")
        
        return self._workflows[actual_name]
    
    def get_activity(self, name: str) -> Callable:
        """
        Get a registered activity by name.
        
        Args:
            name: Name or alias of the activity
            
        Returns:
            The activity function
            
        Raises:
            KeyError: If activity is not found
        """
        # Check if it's an alias
        actual_name = self._activity_aliases.get(name, name)
        
        if actual_name not in self._activities:
            raise KeyError(f"Activity '{name}' not found in registry")
        
        return self._activities[actual_name]
    

    