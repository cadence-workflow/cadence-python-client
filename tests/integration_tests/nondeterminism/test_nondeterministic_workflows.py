import asyncio
import pytest
from datetime import timedelta
from typing import Type, Any

from cadence import workflow, Registry
from cadence._internal.workflow.statemachine.decision_state_machine import (
    DecisionType,
    DecisionId,
)
from cadence._internal.workflow.statemachine.nondeterminism import (
    NonDeterminismError,
    Expectation,
)
from cadence._internal.workflow.workflow_engine import WorkflowEngine, DecisionResult
from cadence.api.v1 import decision
from cadence.api.v1.common_pb2 import Payload
from cadence.api.v1.decision_pb2 import CompleteWorkflowExecutionDecisionAttributes
from cadence.api.v1.history_pb2 import EventFilterType
from cadence.api.v1.service_workflow_pb2 import (
    GetWorkflowExecutionHistoryResponse,
    GetWorkflowExecutionHistoryRequest,
)
from cadence.data_converter import DefaultDataConverter
from cadence.workflow import WorkflowInfo
from tests.integration_tests.helper import CadenceHelper, DOMAIN_NAME

reg = Registry()


@reg.activity
async def first_activity(_: str) -> str:
    return "hello world"


@reg.activity
async def parallel_one(_: str) -> str:
    return "hello 1"


@reg.activity
async def parallel_two(_: str) -> str:
    return "hello 2"


@reg.activity
async def parallel_three(_: str) -> str:
    return "hello 3"


@reg.workflow()
class HappyWorkflow:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")  # event id 5
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )  # event id 11
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )  # event id 12
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )  # event id 20
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )  # event id 21

        return "hello world"


async def test_succeeds(helper: CadenceHelper):
    async with helper.worker(reg) as worker:
        execution = await worker.client.start_workflow(
            "HappyWorkflow",
            task_list=worker.task_list,
            execution_start_to_close_timeout=timedelta(seconds=10),
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

        response = await worker.client.workflow_stub.GetWorkflowExecutionHistory(
            GetWorkflowExecutionHistoryRequest(
                domain=DOMAIN_NAME,
                workflow_execution=execution,
                wait_for_new_event=True,
                history_event_filter_type=EventFilterType.EVENT_FILTER_TYPE_ALL_EVENT,
                skip_archival=True,
            )
        )

        # Uncomment to regenerate.
        # helper.write_history("success.json", response.history)

        assert (
            '"hello world"'
            == response.history.events[
                -1
            ].workflow_execution_completed_event_attributes.result.data.decode()
        )


@reg.workflow()
class NDActivityRemoved:
    @workflow.run
    async def run(self) -> str:
        # await first_activity.with_options(schedule_to_close_timeout=timedelta(seconds=10)).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        return "hello world"


@reg.workflow()
class NDActivityTypeChanged:
    @workflow.run
    async def run(self) -> str:
        await parallel_one.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")  # changed
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        return "hello world"


@reg.workflow()
class NDParallelActivityRemoved:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            # tg.create_task(parallel_one.with_options(schedule_to_close_timeout=timedelta(seconds=10)).execute("2"))
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        return "hello world"


@reg.workflow()
class NDParallelActivityAdded:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )  # Changed
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        return "hello world"


@reg.workflow()
class NDParallelActivityReordered:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            # reordered
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        return "hello world"


@reg.workflow()
class NDLastActivityRemoved:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            # tg.create_task(parallel_three.with_options(schedule_to_close_timeout=timedelta(seconds=10)).execute("5"))

        return "hello world"


@reg.workflow()
class NDEarlyReturn:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )

        # Skipping an entire decision task

        return "hello world"


@reg.workflow()
class NDAllRemoved:
    @workflow.run
    async def run(self) -> str:
        # Same outcome, very early

        return "hello world"


@reg.workflow()
class NDLateReturn:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        # Extra activity at the end
        await parallel_one.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("6")

        return "hello world"


@reg.workflow()
class NDWrongOutcome:
    @workflow.run
    async def run(self) -> str:
        await first_activity.with_options(
            schedule_to_close_timeout=timedelta(seconds=10)
        ).execute("1")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_one.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("2")
            )
            tg.create_task(
                parallel_two.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("3")
            )
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("4")
            )
            tg.create_task(
                parallel_three.with_options(
                    schedule_to_close_timeout=timedelta(seconds=10)
                ).execute("5")
            )

        raise ValueError("failure!")  # changed


def workflow_completed(success: bool, event_id: int | None = None) -> Expectation:
    return Expectation(
        DecisionId(DecisionType.WORKFLOW_COMPLETE, "complete"),
        {
            "success": success,
        },
        event_id,
    )


def activity_scheduled(
    activity_id: int, activity_type: str, event_id: int | None = None
) -> Expectation:
    return Expectation(
        DecisionId(DecisionType.ACTIVITY, str(activity_id)),
        {
            "activity_type": activity_type,
        },
        event_id,
    )


expected_history = [
    activity_scheduled(0, "first_activity", event_id=5),
    activity_scheduled(1, "parallel_one", event_id=11),
    activity_scheduled(2, "parallel_two", event_id=12),
    activity_scheduled(3, "parallel_three", event_id=20),
    activity_scheduled(4, "parallel_three", event_id=21),
    workflow_completed(success=True, event_id=29),
]


@pytest.mark.parametrize(
    "workflow_class,expected",
    [
        pytest.param(HappyWorkflow, None, id="happy path"),
        pytest.param(
            NDActivityRemoved,
            NonDeterminismError(
                expected_history[0], activity_scheduled(0, "parallel_one")
            ),
            id="activity removed",
        ),
        pytest.param(
            NDActivityTypeChanged,
            NonDeterminismError(
                expected_history[0], activity_scheduled(0, "parallel_one")
            ),
            id="activity type change error",
        ),
        pytest.param(
            NDParallelActivityRemoved,
            NonDeterminismError(
                expected_history[1], activity_scheduled(1, "parallel_two")
            ),
            id="parallel activity removed",
        ),
        pytest.param(
            NDParallelActivityAdded,
            NonDeterminismError(None, activity_scheduled(3, "parallel_three")),
            id="parallel activity added",
        ),
        pytest.param(
            NDParallelActivityReordered,
            NonDeterminismError(
                expected_history[1], activity_scheduled(1, "parallel_two")
            ),
            id="parallel activity reordered",
        ),
        pytest.param(
            NDLastActivityRemoved,
            NonDeterminismError(expected_history[4], None),
            id="last activity removed",
        ),
        pytest.param(
            NDEarlyReturn,
            NonDeterminismError(expected_history[3], workflow_completed(True)),
            id="early return",
        ),
        pytest.param(
            NDAllRemoved,
            NonDeterminismError(expected_history[0], workflow_completed(True)),
            id="all removed",
        ),
        pytest.param(
            NDLateReturn,
            NonDeterminismError(
                expected_history[5], activity_scheduled(5, "parallel_one")
            ),
            id="late return",
        ),
        pytest.param(
            NDWrongOutcome,
            NonDeterminismError(expected_history[5], workflow_completed(False)),
            id="wrong outcome",
        ),
    ],
)
def test_nondeterministic_changes(
    helper: CadenceHelper,
    workflow_class: Type[Any],
    expected: NonDeterminismError | None,
) -> None:
    # pytest.raises is awkward with ExceptionGroups, use try/except instead
    try:
        decisions = replay_with_history(helper, workflow_class)
        if expected is not None:
            raise AssertionError("no exception thrown")
        assert decisions.decisions == [
            decision.Decision(
                complete_workflow_execution_decision_attributes=CompleteWorkflowExecutionDecisionAttributes(
                    result=Payload(data='"hello world"'.encode())
                )
            )
        ]
    except NonDeterminismError as e:
        if expected is not None:
            # Compare everything past the message
            assert e.args[1:] == expected.args[1:]
        else:
            raise e
    except ExceptionGroup as e:
        # Only look at the first NonDeterminismError
        if expected is not None:
            subgroup = e.subgroup(NonDeterminismError)
            assert subgroup is not None
            errors = subgroup.exceptions
            assert errors[0].args[1:] == expected.args[1:]
        else:
            raise e


def replay_with_history(helper: CadenceHelper, clazz: Type[Any]) -> DecisionResult:
    history = helper.load_history("success.json")
    test_registry = Registry()
    test_registry.workflow(name=helper.test_name)(clazz)
    workflow_def = test_registry.get_workflow(helper.test_name)
    engine = WorkflowEngine(
        WorkflowInfo(
            workflow_type=helper.test_name,
            workflow_domain="domain",
            workflow_id="wfid",
            workflow_run_id="fast",
            workflow_task_list="tl",
            data_converter=DefaultDataConverter(),
        ),
        workflow_def,
    )
    result = engine.process_decision(list(history.events))
    assert engine.is_done()
    return result
