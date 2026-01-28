from types import NoneType
from typing import Callable, Any, Tuple, Sequence, Dict

import pytest

from cadence._internal.fn_signature import FnSignature, FnParameter


def simple_fn() -> None:
    pass


def no_params() -> str:
    return "hello"


def no_result(param: str) -> None:
    pass


def echo(incoming: str) -> str:
    return incoming


def multiple_params(first: str, second: int, third: float) -> None:
    pass


async def async_fn() -> None:
    pass


async def async_echo(incoming: str) -> str:
    return incoming


class ExampleClass:
    def simple_fn(self) -> None:
        return None

    def echo(self, incoming: str) -> str:
        return incoming

    async def async_echo(self, incoming: str) -> str:
        return incoming


def default_param(value: str = "default_value") -> None:
    return None


def no_annotations(value):
    return value


@pytest.mark.parametrize(
    "fn,expected",
    [
        pytest.param(
            simple_fn, FnSignature(params=[], return_type=NoneType), id="simple fn"
        ),
        pytest.param(
            no_params, FnSignature(params=[], return_type=str), id="no params"
        ),
        pytest.param(
            no_result,
            FnSignature(
                params=[FnParameter(name="param", type_hint=str)], return_type=NoneType
            ),
            id="no result",
        ),
        pytest.param(
            echo,
            FnSignature(
                params=[FnParameter(name="incoming", type_hint=str)], return_type=str
            ),
            id="echo",
        ),
        pytest.param(
            multiple_params,
            FnSignature(
                params=[
                    FnParameter(name="first", type_hint=str),
                    FnParameter(name="second", type_hint=int),
                    FnParameter(name="third", type_hint=float),
                ],
                return_type=NoneType,
            ),
            id="multiple_params",
        ),
        pytest.param(
            async_fn, FnSignature(params=[], return_type=NoneType), id="async void fn"
        ),
        pytest.param(
            async_echo,
            FnSignature(
                params=[FnParameter(name="incoming", type_hint=str)], return_type=str
            ),
            id="async echo",
        ),
        pytest.param(
            ExampleClass.simple_fn,
            FnSignature(params=[], return_type=NoneType),
            id="simple method",
        ),
        pytest.param(
            ExampleClass.echo,
            FnSignature(
                params=[FnParameter(name="incoming", type_hint=str)], return_type=str
            ),
            id="echo method",
        ),
        pytest.param(
            ExampleClass.async_echo,
            FnSignature(
                params=[FnParameter(name="incoming", type_hint=str)], return_type=str
            ),
            id="async echo method",
        ),
        pytest.param(
            default_param,
            FnSignature(
                params=[
                    FnParameter(
                        name="value",
                        type_hint=str,
                        has_default=True,
                        default_value="default_value",
                    )
                ],
                return_type=NoneType,
            ),
            id="default param",
        ),
        pytest.param(
            no_annotations,
            FnSignature(
                params=[FnParameter(name="value", type_hint=None)], return_type=Any
            ),
            id="no annotations",
        ),
    ],
)
def test_signature_of(fn: Callable, expected: FnSignature):
    actual = FnSignature.of(fn)
    assert actual == expected


def varargs_fn(*args: Any) -> None:
    return None


def kwargs_fn(**kwargs: Any) -> None:
    return None


def keyword_only(*, the_param: int) -> None:
    pass


@pytest.mark.parametrize(
    "fn",
    [
        pytest.param(varargs_fn, id="varargs"),
        pytest.param(kwargs_fn, id="kwargs"),
        pytest.param(keyword_only, id="keyword only"),
    ],
)
def test_signature_of_invalid(fn: Callable):
    with pytest.raises(ValueError):
        FnSignature.of(fn)


def validation_fn(
    first_param: int, second_param: str, third_param: bool
) -> Tuple[int, str, bool]:
    return first_param, second_param, third_param


def with_defaults(
    first_param: int = 1, second_param: str = "hello", third_param: bool = True
) -> Tuple[int, str, bool]:
    return first_param, second_param, third_param


DEFAULTS = [1, "hello", True]


@pytest.mark.parametrize(
    "fn,args,kwargs,expected",
    [
        pytest.param(validation_fn, [1, "hello", True], {}, DEFAULTS, id="positional"),
        pytest.param(
            validation_fn,
            [1],
            {"second_param": "hello", "third_param": True},
            DEFAULTS,
            id="mixed",
        ),
        pytest.param(
            validation_fn,
            [],
            {"third_param": True, "first_param": 1, "second_param": "hello"},
            DEFAULTS,
            id="keyword only",
        ),
        pytest.param(
            validation_fn,
            [],
            {"second_param": "hello", "third_param": True},
            None,
            id="missing param keyword",
        ),
        pytest.param(
            validation_fn, [1, "hello"], {}, None, id="missing param positional"
        ),
        pytest.param(
            validation_fn,
            [1, "hello", False, 100],
            {},
            None,
            id="additional param positional",
        ),
        pytest.param(
            validation_fn,
            [],
            {"fourth_param": 100},
            None,
            id="additional param keyword",
        ),
        pytest.param(with_defaults, [], {}, DEFAULTS, id="with defaults"),
        pytest.param(
            with_defaults, [2], {}, [2, "hello", True], id="positional partial override"
        ),
        pytest.param(
            with_defaults,
            [2, "bye", False],
            {},
            [2, "bye", False],
            id="positional override defaults",
        ),
        pytest.param(
            with_defaults,
            [],
            {"first_param": 2, "second_param": "bye"},
            [2, "bye", True],
            id="keyword partial override",
        ),
        pytest.param(
            with_defaults,
            [],
            {"first_param": 2, "second_param": "bye", "third_param": False},
            [2, "bye", False],
            id="keyword override defaults",
        ),
        pytest.param(
            with_defaults,
            [2],
            {"third_param": False},
            [2, "hello", False],
            id="mixed override defaults",
        ),
    ],
)
def test_params_from_call(
    fn: Callable,
    args: Sequence[Any],
    kwargs: Dict[str, Any],
    expected: Sequence[Any] | None,
) -> None:
    signature = FnSignature.of(fn)

    if expected is None:
        with pytest.raises(ValueError):
            signature.params_from_call(args, kwargs)

        return

    assert signature.params_from_call(args, kwargs) == expected
