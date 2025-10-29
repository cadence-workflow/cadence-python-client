#!/usr/bin/env python3
"""
Tests for the registry functionality.
"""

import pytest

from cadence import activity
from cadence import workflow
from cadence.worker import Registry
from cadence.workflow import WorkflowDefinition
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

    def test_basic_workflow_registration_and_retrieval(self):
        """Test basic registration and retrieval for class-based workflows."""
        reg = Registry()

        @reg.workflow
        class TestWorkflow:
            @workflow.run
            async def run(self):
                return "test"

        # Registry stores WorkflowDefinition internally
        workflow_def = reg.get_workflow("TestWorkflow")
        # Verify it's actually a WorkflowDefinition
        assert isinstance(workflow_def, WorkflowDefinition)
        assert workflow_def.name == "TestWorkflow"
        assert workflow_def.cls == TestWorkflow

    def test_basic_activity_registration_and_retrieval(self):
        """Test basic registration and retrieval for activities."""
        reg = Registry()

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

    def test_duplicate_workflow_registration_error(self):
        """Test KeyError is raised for duplicate workflow registrations."""
        reg = Registry()

        @reg.workflow(name="duplicate_test")
        class TestWorkflow:
            @workflow.run
            async def run(self):
                return "test"

        with pytest.raises(KeyError):

            @reg.workflow(name="duplicate_test")
            class TestWorkflow2:
                @workflow.run
                async def run(self):
                    return "duplicate"

    def test_duplicate_activity_registration_error(self):
        """Test KeyError is raised for duplicate activity registrations."""
        reg = Registry()

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

        assert (
            reg.get_activity(common_activities.ActivityInterface.do_something.name)
            is not None
        )
        assert reg.get_activity("ActivityInterface.do_something") is not None
        assert (
            reg.get_activity(common_activities.ActivityInterface.do_something.name)()
            == "result"
        )

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

    def test_class_workflow_validation_errors(self):
        """Test validation errors for class-based workflows."""
        reg = Registry()

        # Test missing run method
        with pytest.raises(ValueError, match="No @workflow.run method found"):

            @reg.workflow
            class MissingRunWorkflow:
                def some_method(self):
                    pass

        # Test duplicate run methods
        with pytest.raises(ValueError, match="Multiple @workflow.run methods found"):

            @reg.workflow
            class DuplicateRunWorkflow:
                @workflow.run
                async def run1(self):
                    pass

                @workflow.run
                async def run2(self):
                    pass

    def test_class_workflow_with_custom_name(self):
        """Test class-based workflow with custom name."""
        reg = Registry()

        @reg.workflow(name="custom_workflow_name")
        class CustomWorkflow:
            @workflow.run
            async def run(self, input: str) -> str:
                return f"processed: {input}"

        workflow_def = reg.get_workflow("custom_workflow_name")
        assert workflow_def.name == "custom_workflow_name"
        assert workflow_def.cls == CustomWorkflow
