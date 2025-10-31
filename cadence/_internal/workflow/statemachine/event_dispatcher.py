from dataclasses import dataclass
from inspect import signature
from typing import Type, Callable, get_type_hints, TypeVar, Any, cast

from google.protobuf.message import Message

T = TypeVar("T")

EventHandler = Callable[[Any, T], None]


@dataclass(
    frozen=True,
)
class Action:
    fn: EventHandler
    id_attr: str
    event_id_is_alias: bool


class EventDispatcher:
    handlers: dict[Type, Action]

    def __init__(self, default_id_attr: str) -> None:
        self._default_id_attr = default_id_attr
        self.handlers = {}

    def event(
        self, id_attr: str = "", event_id_is_alias: bool = False
    ) -> Callable[[EventHandler], EventHandler]:
        def decorator(func: EventHandler) -> EventHandler:
            event_type = _find_event_type(func)
            event_id_attr = id_attr if id_attr else self._default_id_attr

            _validate_field(func, event_type, event_id_attr)
            if event_type in self.handlers:
                raise ValueError(
                    f"Duplicate handler for {event_type}: {func.__qualname__} and {self.handlers[event_type].fn.__qualname__}"
                )
            self.handlers[event_type] = Action(func, event_id_attr, event_id_is_alias)
            return func

        return decorator


def _find_event_type(func: EventHandler) -> Type[Message]:
    sig = signature(func)
    type_hints = get_type_hints(func)
    if len(sig.parameters) != 2:
        raise ValueError(
            f"Expected 2 arguments (self, event), {func.__qualname__} has: {sig.parameters}"
        )
    (non_self_param, _) = list(sig.parameters.items())[1]
    if non_self_param not in type_hints:
        raise ValueError(f"Missing type hint on {func.__qualname__}: {non_self_param}")
    if "return" in type_hints and type_hints["return"] != None.__class__:
        raise ValueError(
            f"Event methods must return None, {func.__qualname__} returns: {type_hints['return']}"
        )

    event_type = type_hints[non_self_param]
    if not issubclass(event_type, Message):
        raise ValueError(
            f"Event methods must accept a Message, {func.__qualname__} accepts: {event_type}"
        )

    # Mypy struggles without this for some reason, despite type narrowing being supported
    return cast(Type[Message], event_type)


def _validate_field(func: EventHandler, event_type: Type[Message], field: str) -> None:
    fields = event_type.DESCRIPTOR.fields_by_name
    if field not in fields:
        raise ValueError(
            f"{func.__qualname__} handles {event_type.__qualname__}, which has no field {field}"
        )
