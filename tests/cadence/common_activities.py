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
    @activity.method()
    def echo_sync(self, incoming: str) -> str:
        return incoming

    @activity.method()
    async def echo_async(self, incoming: str) -> str:
        return incoming


class ActivityInterface(Protocol):
    @activity.method()
    def do_something(self) -> str: ...

    @activity.method()
    async def other_thing(self) -> str: ...

    @activity.method()
    def add(self, a: int, b: int) -> int: ...


class PartialImplementation(ActivityInterface):
    @activity.override(ActivityInterface.add)
    def add(self, a: int, b: int) -> int:
        return a + b

    @activity.override(ActivityInterface.other_thing)
    async def other_thing(self) -> str:
        return "hello"


@dataclass
class ActivityImpl(PartialImplementation):
    result: str

    @activity.override(ActivityInterface.do_something)
    def do_something(self) -> str:
        return self.result


class InvalidImpl(ActivityInterface):
    @activity.override(ActivityInterface.do_something)
    def do_something(self) -> str:
        return "hehe"
