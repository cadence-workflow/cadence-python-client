from inspect import signature, Parameter
from typing import Callable, List, Type, get_type_hints

def get_fn_parameters(fn: Callable) -> List[Type | None]:
    args = signature(fn).parameters
    hints = get_type_hints(fn)
    result = []
    for name, param in args.items():
        if param.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            type_hint = hints.get(name, None)
            result.append(type_hint)

    return result

def validate_fn_parameters(fn: Callable) -> None:
    args = signature(fn).parameters
    for name, param in args.items():
        if param.kind not in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD):
            raise ValueError(f"Parameters must be positional. {name} is {param.kind}, and not valid")