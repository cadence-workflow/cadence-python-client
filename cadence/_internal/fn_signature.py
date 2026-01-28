from dataclasses import dataclass
from inspect import signature, Parameter
from typing import (
    Type,
    Any,
    Callable,
    Sequence,
    get_type_hints,
)

from cadence.api.v1.common_pb2 import Payload
from cadence.data_converter import DataConverter


@dataclass(frozen=True)
class FnParameter:
    name: str
    type_hint: Type | None
    has_default: bool = False
    default_value: Any = None


@dataclass(frozen=True)
class FnSignature:
    params: list[FnParameter]
    return_type: Type

    def params_from_call(
        self, args: Sequence[Any], kwargs: dict[str, Any]
    ) -> list[Any]:
        result: list[Any] = []
        if len(args) > len(self.params):
            raise ValueError(f"Too many positional arguments: {args}")

        for value, param_spec in zip(args, self.params):
            result.append(value)

        i = len(result)
        while i < len(self.params):
            param = self.params[i]
            if param.name not in kwargs and not param.has_default:
                raise ValueError(f"Missing parameter: {param.name}")

            value = kwargs.pop(param.name, param.default_value)
            result.append(value)
            i = i + 1

        if len(kwargs) > 0:
            raise ValueError(f"Unexpected keyword arguments: {kwargs}")

        return result

    def params_from_payload(
        self, data_converter: DataConverter, payload: Payload
    ) -> list[Any]:
        type_hints = [param.type_hint for param in self.params]
        return data_converter.from_data(payload, type_hints)

    @staticmethod
    def of(fn: Callable) -> "FnSignature":
        sig = signature(fn)
        args = sig.parameters
        hints = get_type_hints(fn)
        params = []
        for name, param in args.items():
            # "unbound functions" aren't a thing in the Python spec. We don't have a way to determine whether the function
            # is part of a class or is standalone.
            # Filter out the self parameter and hope they followed the convention.
            if param.name == "self":
                continue
            default = None
            has_default = False
            if param.default != Parameter.empty:
                default = param.default
                has_default = param.default is not None
            if param.kind in (
                Parameter.POSITIONAL_ONLY,
                Parameter.POSITIONAL_OR_KEYWORD,
            ):
                type_hint = hints.get(name, None)
                params.append(FnParameter(name, type_hint, has_default, default))
            else:
                raise ValueError(
                    f"Parameters must be positional. {name} is {param.kind}, and not valid"
                )

        # Treat unspecified return type as Any
        return_type = hints.get("return", Any)

        return FnSignature(params, return_type)
