from typing import Callable, Type

import pytest

from cadence._internal.type_utils import get_fn_parameters, validate_fn_parameters


def _single_param(name: str):
    ...

def _multiple_param(name: str, other: 'str'):
    ...

def _with_args(name:str, *args):
    ...

def _with_kwargs(name:str, **kwargs):
    ...

def _strictly_positional(name: str, other: str, *args, **kwargs):
    ...

def _keyword_only(*args, foo: str):
    ...


@pytest.mark.parametrize(
    "fn,expected",
    [
        pytest.param(
            _single_param, [str], id="single param"
        ),
        pytest.param(
            _multiple_param, [str, str], id="multiple param"
        ),
        pytest.param(
            _strictly_positional, [str, str], id="strictly positional"
        ),
        pytest.param(
            _keyword_only, [], id="keyword only"
        ),
    ]
)
def test_get_fn_parameters(fn: Callable, expected: list[Type]):
    params = get_fn_parameters(fn)
    assert params == expected

@pytest.mark.parametrize(
    "fn,expected",
    [
        pytest.param(
            _single_param, None, id="single param"
        ),
        pytest.param(
            _multiple_param, None, id="multiple param"
        ),
        pytest.param(
            _with_args, ValueError, id="with args"
        ),
        pytest.param(
            _with_kwargs, ValueError, id="with kwargs"
        ),
    ]
)
def test_validate_fn_parameters(fn: Callable, expected: Type[Exception]):
    if expected:
        with pytest.raises(expected):
            validate_fn_parameters(fn)
    else:
        validate_fn_parameters(fn)