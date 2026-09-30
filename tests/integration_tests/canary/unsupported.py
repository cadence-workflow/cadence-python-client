from typing import NoReturn

from tests.integration_tests.canary.constants import UNSUPPORTED_WORKFLOW_REASONS


class UnsupportedCanaryError(RuntimeError):
    pass


def raise_unsupported(workflow_type: str) -> NoReturn:
    reason = UNSUPPORTED_WORKFLOW_REASONS[workflow_type]
    raise UnsupportedCanaryError(f"{workflow_type} is unavailable: {reason}")
