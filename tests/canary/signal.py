from datetime import timedelta

from cadence import Registry, activity, workflow
from cadence.workflow import WorkflowContext

from tests.canary.constants import (
    ACTIVITY_TIMEOUT,
    ACTIVITY_TYPE_SIGNAL,
    CHILD_WORKFLOW_TIMEOUT,
    WORKFLOW_TYPE_SIGNAL,
    WORKFLOW_TYPE_SIGNAL_EXTERNAL,
)

_SIGNAL_NAME = "canary-signal"
_SIGNAL_VALUE = "canary.signal"

signal_registry = Registry()


@signal_registry.activity(name=ACTIVITY_TYPE_SIGNAL)
async def signal_parent(
    workflow_id: str,
    run_id: str,
    signal_name: str,
) -> bool:
    client = activity.client()
    await client.signal_workflow(
        workflow_id,
        run_id,
        signal_name,
        _SIGNAL_VALUE,
    )
    await client.signal_workflow(
        workflow_id,
        "",
        signal_name,
        _SIGNAL_VALUE,
    )
    return True


@signal_registry.workflow(name=WORKFLOW_TYPE_SIGNAL_EXTERNAL)
class SignalExternalWorkflow:
    def __init__(self) -> None:
        self.signal_value: str | None = None

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.signal_value is not None)
        if self.signal_value != _SIGNAL_VALUE:
            raise ValueError(f"unexpected signal value: {self.signal_value!r}")
        return self.signal_value

    @workflow.signal(name=_SIGNAL_NAME)
    def receive_signal(self, value: str) -> None:
        self.signal_value = value


@signal_registry.workflow(name=WORKFLOW_TYPE_SIGNAL)
class SignalWorkflow:
    def __init__(self) -> None:
        self.parent_signals: list[str] = []

    @workflow.run
    async def run(self) -> None:
        info = WorkflowContext.get().info()
        await workflow.execute_activity(
            ACTIVITY_TYPE_SIGNAL,
            bool,
            info.workflow_id,
            info.workflow_run_id,
            _SIGNAL_NAME,
            schedule_to_close_timeout=ACTIVITY_TIMEOUT,
        )
        await workflow.wait_condition(lambda: len(self.parent_signals) >= 2)
        if self.parent_signals != [_SIGNAL_VALUE, _SIGNAL_VALUE]:
            raise ValueError(f"unexpected parent signals: {self.parent_signals!r}")

        await self._signal_child(
            workflow_id=f"{info.workflow_id}/signal-child",
            via_handle=True,
            use_run_id=True,
        )
        await self._signal_child(
            workflow_id=f"{info.workflow_id}/signal-external-without-run-id",
            via_handle=False,
            use_run_id=False,
        )
        await self._signal_child(
            workflow_id=f"{info.workflow_id}/signal-external-with-run-id",
            via_handle=False,
            use_run_id=True,
        )

    async def _signal_child(
        self,
        *,
        workflow_id: str,
        via_handle: bool,
        use_run_id: bool,
    ) -> None:
        handle = await workflow.start_child_workflow(
            WORKFLOW_TYPE_SIGNAL_EXTERNAL,
            str,
            workflow_id=workflow_id,
            execution_start_to_close_timeout=CHILD_WORKFLOW_TIMEOUT,
            task_start_to_close_timeout=timedelta(seconds=10),
        )
        if via_handle:
            await handle.signal(_SIGNAL_NAME, _SIGNAL_VALUE)
        else:
            await workflow.signal_external_workflow(
                handle.workflow_id,
                _SIGNAL_NAME,
                _SIGNAL_VALUE,
                run_id=handle.run_id if use_run_id else "",
            )
        result = await handle
        if result != _SIGNAL_VALUE:
            raise ValueError(f"unexpected child signal result: {result!r}")

    @workflow.signal(name=_SIGNAL_NAME)
    def receive_parent_signal(self, value: str) -> None:
        self.parent_signals.append(value)
