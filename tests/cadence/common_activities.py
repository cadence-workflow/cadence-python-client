from typing import Protocol
from dataclasses import dataclass

from cadence import activity


@activity.defn()
def simple_fn() -> None:
    pass


@activity.defn
def no_parens() -> None:
    pass


@activity.defn()
def echo(incoming: str) -> str:
    return incoming


@activity.defn(name="renamed")
def renamed_fn() -> None:
    pass


@activity.defn()
async def async_fn() -> None:
    pass


@activity.defn()
async def async_echo(incoming: str) -> str:
    return incoming


class Activities:
    @activity.defn()
    def echo_sync(self, incoming: str) -> str:
        return incoming

    @activity.defn()
    async def echo_async(self, incoming: str) -> str:
        return incoming


class ActivityInterface(Protocol):
    @activity.defn()
    def do_something(self) -> str: ...


@dataclass
class ActivityImpl(ActivityInterface):
    result: str

    def do_something(self) -> str:  # type: ignore
        return self.result


class InvalidImpl(ActivityInterface):
    @activity.defn(name="something else entirely")
    def do_something(self) -> str:
        return "hehe"
