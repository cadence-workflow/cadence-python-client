#!/usr/bin/env python3
"""
Tests for the registry functionality.
"""

import pytest
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from cadence.worker import Registry, RegisterWorkflowOptions, RegisterActivityOptions


class TestRegistry:
    """Test registry functionality."""
    
    def test_basic_registry_creation(self):
        """Test basic registry creation."""
        reg = Registry()
        assert len(reg._workflows) == 0
        assert len(reg._activities) == 0
    
    def test_register_and_retrieve_workflow(self):
        """Test registering and retrieving workflows."""
        reg = Registry()
        
        @reg.workflow
        def test_workflow():
            return "test"
        
        assert "test_workflow" in reg._workflows
        wf = reg.get_workflow("test_workflow")
        assert wf() == "test"
    
    def test_register_and_retrieve_activity(self):
        """Test registering and retrieving activities."""
        reg = Registry()
        
        @reg.activity
        def test_activity():
            return "test"
        
        assert "test_activity" in reg._activities
        act = reg.get_activity("test_activity")
        assert act() == "test"
    
    def test_workflow_registration(self):
        """Test workflow registration."""
        reg = Registry()
        
        @reg.workflow
        def global_workflow():
            return "global"
        
        assert "global_workflow" in reg._workflows
        wf = reg.get_workflow("global_workflow")
        assert wf() == "global"
    
    def test_activity_registration(self):
        """Test activity registration."""
        reg = Registry()
        
        @reg.activity
        def global_activity():
            return "global"
        
        assert "global_activity" in reg._activities
        act = reg.get_activity("global_activity")
        assert act() == "global"
    

    
    def test_workflow_not_found_error(self):
        """Test KeyError is raised when workflow not found."""
        reg = Registry()
        
        with pytest.raises(KeyError):
            reg.get_workflow("nonexistent")
    
    def test_activity_not_found_error(self):
        """Test KeyError is raised when activity not found."""
        reg = Registry()
        
        with pytest.raises(KeyError):
            reg.get_activity("nonexistent")
    
    def test_duplicate_registration_error(self):
        """Test KeyError is raised for duplicate registrations."""
        reg = Registry()
        
        @reg.workflow
        def test_workflow():
            return "test"
        
        with pytest.raises(KeyError):
            @reg.workflow
            def test_workflow():
                return "duplicate"
    
    def test_workflow_alias(self):
        """Test workflow alias functionality."""
        reg = Registry()
        
        @reg.workflow(name="custom_name")
        def test_workflow():
            return "test"
        
        assert "custom_name" in reg._workflows
        wf = reg.get_workflow("custom_name")
        assert wf() == "test"
    
    def test_activity_alias(self):
        """Test activity alias functionality."""
        reg = Registry()
        
        @reg.activity(alias="custom_alias")
        def test_activity():
            return "test"
        
        assert "custom_alias" in reg._activity_aliases
        act = reg.get_activity("custom_alias")
        assert act() == "test"
    
    def test_workflow_options_class(self):
        """Test using RegisterWorkflowOptions class."""
        reg = Registry()
        
        options = RegisterWorkflowOptions(name="custom_name", alias="custom_alias")
        
        @reg.workflow(**options.__dict__)
        def test_workflow():
            return "test"
        
        assert "custom_name" in reg._workflows
        assert "custom_alias" in reg._workflow_aliases
        wf = reg.get_workflow("custom_name")
        assert wf() == "test"
    
    def test_activity_options_class(self):
        """Test using RegisterActivityOptions class."""
        reg = Registry()
        
        options = RegisterActivityOptions(name="custom_name", alias="custom_alias")
        
        @reg.activity(**options.__dict__)
        def test_activity():
            return "test"
        
        assert "custom_name" in reg._activities
        assert "custom_alias" in reg._activity_aliases
        act = reg.get_activity("custom_name")
        assert act() == "test"


if __name__ == "__main__":
    pytest.main([__file__])
