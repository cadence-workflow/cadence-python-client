#!/usr/bin/env python3
"""
Tests for the registry functionality.
"""

import pytest

from cadence import activity
from cadence.worker import Registry
from tests.cadence import common_activities


class TestRegistry:
    """Test registry functionality."""
    
    def test_basic_registry_creation(self):
        """Test basic registry creation."""
        reg = Registry()
        with pytest.raises(KeyError):
            reg.get_workflow("nonexistent")
        with pytest.raises(KeyError):
            reg.get_activity("nonexistent")
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_basic_registration_and_retrieval(self, registration_type):
        """Test basic registration and retrieval for both workflows and activities."""
        reg = Registry()
        
        if registration_type == "workflow":
            @reg.workflow
            def test_func():
                return "test"
            
            func = reg.get_workflow("test_func")
        else:
            @reg.activity
            def test_func():
                return "test"
            
            func = reg.get_activity(test_func.name)
        
        assert func() == "test"
    
    def test_direct_call_behavior(self):
        reg = Registry()

        @activity.defn(name="test_func")
        def test_func():
            return "direct_call"

        reg.register_activity(test_func)
        func = reg.get_activity("test_func")
        
        assert func() == "direct_call"
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_not_found_error(self, registration_type):
        """Test KeyError is raised when function not found."""
        reg = Registry()
        
        if registration_type == "workflow":
            with pytest.raises(KeyError):
                reg.get_workflow("nonexistent")
        else:
            with pytest.raises(KeyError):
                reg.get_activity("nonexistent")
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_duplicate_registration_error(self, registration_type):
        """Test KeyError is raised for duplicate registrations."""
        reg = Registry()
        
        if registration_type == "workflow":
            @reg.workflow
            def test_func():
                return "test"
            
            with pytest.raises(KeyError):
                @reg.workflow
                def test_func():
                    return "duplicate"
        else:
            @reg.activity(name="test_func")
            def test_func():
                return "test"

            with pytest.raises(KeyError):
                @reg.activity(name="test_func")
                def test_func():
                    return "duplicate"

    def test_register_activities_instance(self):
        reg = Registry()

        reg.register_activities(common_activities.Activities())

        assert reg.get_activity("Activities.echo_sync") is not None
        assert reg.get_activity("Activities.echo_sync") is not None

    def test_register_activities_interface(self):
        impl = common_activities.ActivityImpl("result")
        reg = Registry()

        reg.register_activities(impl)

        assert reg.get_activity(common_activities.ActivityInterface.do_something.name) is not None
        assert reg.get_activity("ActivityInterface.do_something") is not None
        assert reg.get_activity(common_activities.ActivityInterface.do_something.name)() == "result"

    def test_register_activities_invalid_impl(self):
        impl = common_activities.InvalidImpl()
        reg = Registry()

        with pytest.raises(ValueError):
            reg.register_activities(impl)


    def test_add(self):
        registry = Registry()
        registry.register_activity(common_activities.simple_fn)
        other = Registry()
        other.register_activity(common_activities.echo)

        result = registry + other

        assert result.get_activity("simple_fn") is not None
        assert result.get_activity("echo") is not None
        with pytest.raises(KeyError):
            registry.get_activity("echo")
        with pytest.raises(KeyError):
            other.get_activity("simple_fn")

    def test_add_duplicate(self):
        registry = Registry()
        registry.register_activity(common_activities.simple_fn)
        other = Registry()
        other.register_activity(common_activities.simple_fn)
        with pytest.raises(KeyError):
            registry + other

    def test_of(self):
        first = Registry()
        second = Registry()
        third = Registry()
        first.register_activity(common_activities.simple_fn)
        second.register_activity(common_activities.echo)
        third.register_activity(common_activities.async_fn)

        result = Registry.of(first, second, third)
        assert result.get_activity("simple_fn") is not None
        assert result.get_activity("echo") is not None
        assert result.get_activity("async_fn") is not None
