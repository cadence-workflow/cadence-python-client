#!/usr/bin/env python3
"""
Tests for the registry chaining functionality.
"""

import pytest
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from cadence.worker._registry import (
    Registry, new_registry, registry,
    RegistryError, WorkflowNotFoundError, ActivityNotFoundError, DuplicateRegistrationError
)


class TestRegistryChaining:
    """Test registry chaining functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear the global registry before each test
        registry.clear()
    
    def test_basic_registry_creation(self):
        """Test basic registry creation."""
        reg = Registry()
        assert reg.get_workflow_count() == 0
        assert reg.get_activity_count() == 0
        assert not reg.has_next_registry()
    
    def test_new_registry_chains_to_global(self):
        """Test that new_registry() automatically chains to global registry."""
        local_reg = new_registry()
        assert local_reg.has_next_registry()
        assert local_reg.get_next_registry() is registry
    
    def test_register_and_retrieve_workflow(self):
        """Test registering and retrieving workflows."""
        reg = Registry()
        
        @reg.register_workflow
        def test_workflow():
            return "test"
        
        assert reg.has_workflow("test_workflow")
        wf = reg.get_workflow("test_workflow")
        assert wf() == "test"
    
    def test_register_and_retrieve_activity(self):
        """Test registering and retrieving activities."""
        reg = Registry()
        
        @reg.register_activity
        def test_activity():
            return "test"
        
        assert reg.has_activity("test_activity")
        act = reg.get_activity("test_activity")
        assert act() == "test"
    
    def test_workflow_chaining(self):
        """Test workflow lookup through registry chain."""
        # Register in global registry
        @registry.register_workflow
        def global_workflow():
            return "global"
        
        # Create local registry that chains to global
        local_reg = new_registry()
        
        # Register in local registry
        @local_reg.register_workflow
        def local_workflow():
            return "local"
        
        # Test that local registry can access both
        assert local_reg.has_workflow("local_workflow")
        assert local_reg.has_workflow("global_workflow")
        
        local_wf = local_reg.get_workflow("local_workflow")
        global_wf = local_reg.get_workflow("global_workflow")
        
        assert local_wf() == "local"
        assert global_wf() == "global"
    
    def test_activity_chaining(self):
        """Test activity lookup through registry chain."""
        # Register in global registry
        @registry.register_activity
        def global_activity():
            return "global"
        
        # Create local registry that chains to global
        local_reg = new_registry()
        
        # Register in local registry
        @local_reg.register_activity
        def local_activity():
            return "local"
        
        # Test that local registry can access both
        assert local_reg.has_activity("local_activity")
        assert local_reg.has_activity("global_activity")
        
        local_act = local_reg.get_activity("local_activity")
        global_act = local_reg.get_activity("global_activity")
        
        assert local_act() == "local"
        assert global_act() == "global"
    
    def test_multi_level_chaining(self):
        """Test multi-level registry chaining."""
        # Global registry
        @registry.register_workflow
        def global_workflow():
            return "global"
        
        # Local registry
        local_reg = new_registry()
        @local_reg.register_workflow
        def local_workflow():
            return "local"
        
        # Sub registry
        sub_reg = Registry()
        @sub_reg.register_workflow
        def sub_workflow():
            return "sub"
        
        # Chain: sub -> local -> global
        sub_reg.set_next_registry(local_reg)
        
        # Test that sub registry can access all levels
        assert sub_reg.has_workflow("sub_workflow")
        assert sub_reg.has_workflow("local_workflow")
        assert sub_reg.has_workflow("global_workflow")
        
        sub_wf = sub_reg.get_workflow("sub_workflow")
        local_wf = sub_reg.get_workflow("local_workflow")
        global_wf = sub_reg.get_workflow("global_workflow")
        
        assert sub_wf() == "sub"
        assert local_wf() == "local"
        assert global_wf() == "global"
    
    def test_list_aggregation(self):
        """Test that list methods aggregate from all chained registries."""
        # Global registry
        @registry.register_workflow
        def global_workflow():
            return "global"
        
        # Local registry
        local_reg = new_registry()
        @local_reg.register_workflow
        def local_workflow():
            return "local"
        
        # Sub registry
        sub_reg = Registry()
        @sub_reg.register_workflow
        def sub_workflow():
            return "sub"
        sub_reg.set_next_registry(local_reg)
        
        # Test list aggregation
        global_workflows = registry.list_workflows()
        local_workflows = local_reg.list_workflows()
        sub_workflows = sub_reg.list_workflows()
        
        assert "global_workflow" in global_workflows
        assert "local_workflow" in local_workflows
        assert "global_workflow" in local_workflows
        assert "sub_workflow" in sub_workflows
        assert "local_workflow" in sub_workflows
        assert "global_workflow" in sub_workflows
    
    def test_count_aggregation(self):
        """Test that count methods aggregate from all chained registries."""
        # Global registry
        @registry.register_workflow
        def global_workflow():
            return "global"
        
        # Local registry
        local_reg = new_registry()
        @local_reg.register_workflow
        def local_workflow():
            return "local"
        
        # Sub registry
        sub_reg = Registry()
        @sub_reg.register_workflow
        def sub_workflow():
            return "sub"
        sub_reg.set_next_registry(local_reg)
        
        # Test count aggregation
        assert registry.get_workflow_count() == 1
        assert local_reg.get_workflow_count() == 1
        assert sub_reg.get_workflow_count() == 1
        
        assert registry.get_total_workflow_count() == 1
        assert local_reg.get_total_workflow_count() == 2
        assert sub_reg.get_total_workflow_count() == 3
    
    def test_chain_management(self):
        """Test chain management methods."""
        reg1 = Registry()
        reg2 = Registry()
        
        # Test setting next registry
        reg1.set_next_registry(reg2)
        assert reg1.has_next_registry()
        assert reg1.get_next_registry() is reg2
        
        # Test that reg2 has no next registry
        assert not reg2.has_next_registry()
        assert reg2.get_next_registry() is None
    
    def test_workflow_not_found_error(self):
        """Test WorkflowNotFoundError is raised when workflow not found."""
        reg = Registry()
        
        with pytest.raises(WorkflowNotFoundError):
            reg.get_workflow("nonexistent")
    
    def test_activity_not_found_error(self):
        """Test ActivityNotFoundError is raised when activity not found."""
        reg = Registry()
        
        with pytest.raises(ActivityNotFoundError):
            reg.get_activity("nonexistent")
    
    def test_duplicate_registration_error(self):
        """Test DuplicateRegistrationError is raised for duplicate registrations."""
        reg = Registry()
        
        @reg.register_workflow
        def test_workflow():
            return "test"
        
        with pytest.raises(DuplicateRegistrationError):
            @reg.register_workflow
            def test_workflow():
                return "duplicate"
    
    def test_workflow_alias(self):
        """Test workflow alias functionality."""
        reg = Registry()
        
        @reg.register_workflow(name="custom_name")
        def test_workflow():
            return "test"
        
        assert reg.has_workflow("custom_name")
        wf = reg.get_workflow("custom_name")
        assert wf() == "test"
    
    def test_activity_alias(self):
        """Test activity alias functionality."""
        reg = Registry()
        
        @reg.register_activity(alias="custom_alias")
        def test_activity():
            return "test"
        
        assert reg.has_activity("custom_alias")
        act = reg.get_activity("custom_alias")
        assert act() == "test"
    
    def test_unregister_workflow(self):
        """Test unregistering workflows."""
        reg = Registry()
        
        @reg.register_workflow
        def test_workflow():
            return "test"
        
        assert reg.has_workflow("test_workflow")
        assert reg.unregister_workflow("test_workflow")
        assert not reg.has_workflow("test_workflow")
        assert not reg.unregister_workflow("test_workflow")  # Already unregistered
    
    def test_unregister_activity(self):
        """Test unregistering activities."""
        reg = Registry()
        
        @reg.register_activity
        def test_activity():
            return "test"
        
        assert reg.has_activity("test_activity")
        assert reg.unregister_activity("test_activity")
        assert not reg.has_activity("test_activity")
        assert not reg.unregister_activity("test_activity")  # Already unregistered
    
    def test_clear_registry(self):
        """Test clearing registry."""
        reg = Registry()
        
        @reg.register_workflow
        def test_workflow():
            return "test"
        
        @reg.register_activity
        def test_activity():
            return "test"
        
        assert reg.get_workflow_count() == 1
        assert reg.get_activity_count() == 1
        
        reg.clear()
        
        assert reg.get_workflow_count() == 0
        assert reg.get_activity_count() == 0
        assert not reg.has_workflow("test_workflow")
        assert not reg.has_activity("test_activity")


if __name__ == "__main__":
    pytest.main([__file__])
