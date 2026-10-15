from unittest.mock import Mock

from cadence.client import ClientOptions, _validate_and_copy_defaults
from cadence.workflow import (
    WorkflowContext,
    WorkflowInterceptor,
)


def test_not_abstract() -> None:
    assert WorkflowInterceptor.__abstractmethods__ == frozenset()


def test_overrides_every_public_method() -> None:
    # mypy can't enforce overriding non-abstract methods, so check at runtime.
    expected = {
        name
        for name, value in vars(WorkflowContext).items()
        if not name.startswith("_")
        and callable(value)
        and not isinstance(value, staticmethod)
    }
    missing = expected - set(vars(WorkflowInterceptor))
    assert not missing


def test_client_default_factory_is_identity() -> None:
    options = _validate_and_copy_defaults(
        ClientOptions(domain="domain", target="target")
    )
    ctx = Mock(spec=WorkflowContext)

    assert options["workflow_interceptor_factory"](ctx) is ctx


def test_client_custom_factory_preserved() -> None:
    def factory(ctx: WorkflowContext) -> WorkflowContext:
        return WorkflowInterceptor(ctx)

    options = _validate_and_copy_defaults(
        ClientOptions(
            domain="domain", target="target", workflow_interceptor_factory=factory
        )
    )

    assert options["workflow_interceptor_factory"] is factory
