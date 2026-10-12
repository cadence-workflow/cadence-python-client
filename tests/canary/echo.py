import sys
from dataclasses import dataclass

from cadence import Registry, workflow

from tests.canary.constants import (
    ACTIVITY_TIMEOUT,
    ACTIVITY_TYPE_ECHO,
    WORKFLOW_TYPE_ECHO,
)

echo_registry = Registry()


@dataclass(frozen=True)
class EchoInput:
    int_value: int
    optional_int_value: int | None
    float_value: float
    string_value: str
    optional_string_value: str | None
    list_value: list[str]
    map_value: dict[str, str]


def _new_echo_input() -> EchoInput:
    return EchoInput(
        int_value=sys.maxsize,
        optional_int_value=sys.maxsize,
        float_value=sys.float_info.max,
        string_value="canary_echo_test",
        optional_string_value="canary_echo_test",
        list_value=["canary", ".", "EchoWorkflow"],
        map_value={"us-east-1": "dca1a", "us-west-1": "sjc1a"},
    )


@echo_registry.activity(name=ACTIVITY_TYPE_ECHO)
def echo_activity(value: EchoInput) -> EchoInput:
    if value != _new_echo_input():
        raise ValueError("echo activity received an unexpected input")
    return value


@echo_registry.workflow(name=WORKFLOW_TYPE_ECHO)
class EchoWorkflow:
    @workflow.run
    async def run(self) -> None:
        expected = _new_echo_input()
        actual = await workflow.execute_activity(
            ACTIVITY_TYPE_ECHO,
            EchoInput,
            expected,
            schedule_to_close_timeout=ACTIVITY_TIMEOUT,
        )
        if actual != expected:
            raise ValueError("echo activity returned an unexpected output")
