from dataclasses import dataclass
from datetime import timedelta
from typing import TypeVar, Any

import pytest

from cadence import Registry, workflow, activity
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryResponse,
    GetWorkflowExecutionHistoryRequest,
)
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME


@dataclass(frozen=True)
class CustomData:
    some_int: int
    some_string: str


serialization_workflows = Registry()


T = TypeVar("T")


class SerializationActivities:
    def __init__(self, expected: Any) -> None:
        self.expected = expected

    @activity.method()
    def untyped(self, message):
        return self.assert_expected(message)

    @activity.method()
    def string_activity(self, message: str) -> str:
        return self.assert_expected(message)

    @activity.method()
    def int_activity(self, message: int) -> int:
        return self.assert_expected(message)

    @activity.method()
    def bool_activity(self, message: bool) -> bool:
        return self.assert_expected(message)

    @activity.method()
    def list_activity(self, message: list[int]) -> list[int]:
        return self.assert_expected(message)

    @activity.method()
    def dict_activity(self, message: dict[str, Any]) -> dict[str, Any]:
        return self.assert_expected(message)

    @activity.method()
    def set_activity(self, message: set[str]) -> set[str]:
        return self.assert_expected(message)

    @activity.method()
    def dataclass_activity(self, message: CustomData) -> CustomData:
        return self.assert_expected(message)

    def assert_expected(self, message: T) -> T:
        assert message == self.expected
        return message


@serialization_workflows.workflow()
class UntypedWorkflow:
    @workflow.run
    async def run(self, activity_name: str, message) -> Any:
        return await workflow.execute_activity(
            activity_name, Any, message, schedule_to_close_timeout=timedelta(seconds=10)
        )


@serialization_workflows.workflow()
class DataClassWorkflow:
    @workflow.run
    async def run(self, activity_name: str, message: CustomData) -> CustomData:
        return await workflow.execute_activity(
            activity_name,
            CustomData,
            message,
            schedule_to_close_timeout=timedelta(seconds=10),
        )


@pytest.mark.parametrize(
    "result_type,value,activity_name",
    [
        pytest.param(
            str, "hello world", "SerializationActivities.untyped", id="untyped string"
        ),
        pytest.param(int, 1, "SerializationActivities.untyped", id="untyped int"),
        pytest.param(bool, True, "SerializationActivities.untyped", id="untyped bool"),
        pytest.param(
            list[int], [1, 2, 3], "SerializationActivities.untyped", id="untyped list"
        ),
        pytest.param(
            dict[str, Any],
            {"hello": "world"},
            "SerializationActivities.untyped",
            id="untyped dict",
        ),
        pytest.param(
            str,
            "hello world",
            "SerializationActivities.string_activity",
            id="typed string",
        ),
        pytest.param(int, 1, "SerializationActivities.int_activity", id="typed int"),
        pytest.param(
            bool, True, "SerializationActivities.bool_activity", id="typed bool"
        ),
        pytest.param(
            list[int],
            [1, 2, 3],
            "SerializationActivities.list_activity",
            id="typed list",
        ),
        pytest.param(
            dict[str, Any],
            {"hello": "world"},
            "SerializationActivities.dict_activity",
            id="typed dict",
        ),
        # Set and Dataclasses can't be untyped by the activity because they're not a JSON type
        pytest.param(
            set[Any], {"hello world"}, "SerializationActivities.set_activity", id="set"
        ),
        pytest.param(
            CustomData,
            CustomData(some_int=7, some_string="hi"),
            "SerializationActivities.dataclass_activity",
            id="dataclass",
        ),
    ],
)
async def test_untyped_serialization(
    helper: CadenceHelper, result_type, value: Any, activity_name: str
) -> None:
    test_reg = Registry()
    test_reg.register_activities(SerializationActivities(value))
    async with helper.worker(Registry.of(test_reg, serialization_workflows)) as worker:
        execution = await worker.client.start_workflow(
            "UntypedWorkflow",
            activity_name,
            value,
            execution_start_to_close_timeout=timedelta(seconds=10),
            task_list=worker.task_list,
        )

        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        close_event = response.history.events[-1]
        assert hasattr(close_event, "workflow_execution_completed_event_attributes")
        close_event_attributes = (
            close_event.workflow_execution_completed_event_attributes
        )
        deserialized = helper.client().data_converter.from_data(
            close_event_attributes.result, [result_type]
        )[0]

        assert deserialized == value


async def test_dataclass_workflow(helper: CadenceHelper) -> None:
    expected = CustomData(some_int=7, some_string="hi")

    test_reg = Registry()
    test_reg.register_activities(SerializationActivities(expected))
    async with helper.worker(Registry.of(test_reg, serialization_workflows)) as worker:
        execution = await worker.client.start_workflow(
            "DataClassWorkflow",
            SerializationActivities.dataclass_activity.name,
            expected,
            execution_start_to_close_timeout=timedelta(seconds=10),
            task_list=worker.task_list,
        )

        response: GetWorkflowExecutionHistoryResponse = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_CLOSE_EVENT,
                skip_archival=True,
            )
        )

        close_event = response.history.events[-1]
        assert hasattr(close_event, "workflow_execution_completed_event_attributes")
        close_event_attributes = (
            close_event.workflow_execution_completed_event_attributes
        )
        deserialized = helper.client().data_converter.from_data(
            close_event_attributes.result, [CustomData]
        )[0]

        assert deserialized == expected
