#!/usr/bin/env python3
"""
Tests for the registry functionality.
"""

import pytest

from cadence.worker import Registry, RegisterWorkflowOptions, RegisterActivityOptions


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
            
            func = reg.get_activity("test_func")
        
        assert func() == "test"
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_direct_call_behavior(self, registration_type):
        """Test direct function call behavior for both workflows and activities."""
        reg = Registry()
        
        def test_func():
            return "direct_call"
        
        if registration_type == "workflow":
            registered_func = reg.workflow(test_func)
            func = reg.get_workflow("test_func")
        else:
            registered_func = reg.activity(test_func)
            func = reg.get_activity("test_func")
        
        assert registered_func == test_func
        assert func() == "direct_call"
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_decorator_with_options(self, registration_type):
        """Test decorator with options for both workflows and activities."""
        reg = Registry()
        
        if registration_type == "workflow":
            @reg.workflow(name="custom_name", alias="custom_alias")
            def test_func():
                return "decorator_with_options"
            
            func = reg.get_workflow("custom_name")
            func_by_alias = reg.get_workflow("custom_alias")
        else:
            @reg.activity(name="custom_name", alias="custom_alias")
            def test_func():
                return "decorator_with_options"
            
            func = reg.get_activity("custom_name")
            func_by_alias = reg.get_activity("custom_alias")
        
        assert func() == "decorator_with_options"
        assert func_by_alias() == "decorator_with_options"
        assert func == func_by_alias
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_direct_call_with_options(self, registration_type):
        """Test direct call with options for both workflows and activities."""
        reg = Registry()
        
        def test_func():
            return "direct_call_with_options"
        
        if registration_type == "workflow":
            registered_func = reg.workflow(test_func, name="custom_name", alias="custom_alias")
            func = reg.get_workflow("custom_name")
            func_by_alias = reg.get_workflow("custom_alias")
        else:
            registered_func = reg.activity(test_func, name="custom_name", alias="custom_alias")
            func = reg.get_activity("custom_name")
            func_by_alias = reg.get_activity("custom_name")
        
        assert registered_func == test_func
        assert func() == "direct_call_with_options"
        assert func_by_alias() == "direct_call_with_options"
        assert func == func_by_alias
    
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
            @reg.activity
            def test_func():
                return "test"
            
            with pytest.raises(KeyError):
                @reg.activity
                def test_func():
                    return "duplicate"
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_alias_functionality(self, registration_type):
        """Test alias functionality for both workflows and activities."""
        reg = Registry()
        
        if registration_type == "workflow":
            @reg.workflow(name="custom_name")
            def test_func():
                return "test"
            
            func = reg.get_workflow("custom_name")
        else:
            @reg.activity(alias="custom_alias")
            def test_func():
                return "test"
            
            func = reg.get_activity("custom_alias")
            func_by_name = reg.get_activity("test_func")
            assert func_by_name() == "test"
            assert func == func_by_name
        
        assert func() == "test"
    
    @pytest.mark.parametrize("registration_type", ["workflow", "activity"])
    def test_options_class(self, registration_type):
        """Test using options classes for both workflows and activities."""
        reg = Registry()
        
        if registration_type == "workflow":
            options = RegisterWorkflowOptions(name="custom_name", alias="custom_alias")
            
            @reg.workflow(**options.__dict__)
            def test_func():
                return "test"
            
            func = reg.get_workflow("custom_name")
            func_by_alias = reg.get_workflow("custom_alias")
        else:
            options = RegisterActivityOptions(name="custom_name", alias="custom_alias")
            
            @reg.activity(**options.__dict__)
            def test_func():
                return "test"
            
            func = reg.get_activity("custom_name")
            func_by_alias = reg.get_activity("custom_alias")
        
        assert func() == "test"
        assert func_by_alias() == "test"
        assert func == func_by_alias
