from collections.abc import Mapping
from typing import cast

from msgspec import DecodeError, json

from cadence._internal.workflow.deterministic_event_loop import (
    FatalDecisionError,
    fail_decision,
)
from cadence.api.v1.common_pb2 import Payload
from cadence.workflow import (
    CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE,
    SearchAttributeType,
)


def encode_version_marker_details(version: int) -> Payload:
    """Encode SDK-owned Version marker details as one canonical JSON integer."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Version marker details must be an int")
    return Payload(data=json.encode(version))


def decode_version_marker_details(details: Payload) -> int:
    """Decode the canonical SDK-owned Version marker details format."""
    if not details.data:
        raise ValueError("Version marker details are empty")
    try:
        version = json.decode(details.data)
    except DecodeError as exc:
        raise ValueError("Version marker details are invalid") from exc
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Version marker details must encode a JSON integer")
    return cast(int, version)


def validate_version_arguments(
    change_id: str,
    min_supported: int,
    max_supported: int,
) -> None:
    if not isinstance(change_id, str) or not change_id:
        raise ValueError("change_id must be a non-empty str")
    for name, value in (
        ("min_supported", min_supported),
        ("max_supported", max_supported),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an int")
    if min_supported > max_supported:
        raise ValueError("min_supported must not be greater than max_supported")


# Values of the VersionMismatchType metric and log tag.
VERSION_MISMATCH_TOO_NEW = "toonew"
"""The version is newer than this worker's code supports.

Expected during a rolling deployment, when an old worker replays a workflow that
a newer worker has already moved to a higher version. It resolves itself once an
upgraded worker picks up the decision task.
"""
VERSION_MISMATCH_TOO_OLD = "tooold"
"""The workflow code dropped support for a version that is still in use.

This is a bug in the workflow code.
"""


class VersionMismatchError(FatalDecisionError):
    """Raised by get_version when the version is outside the supported range.

    It is a separate type so that the decision task handler can report it apart
    from other decision failures. Like any FatalDecisionError, it fails the
    decision task so it is retried, not the workflow.
    """

    def __init__(
        self,
        change_id: str,
        version: int,
        min_supported: int,
        max_supported: int,
    ) -> None:
        # Same message as before this type existed, so log searches keep working.
        super().__init__(
            f"version {version} for change_id {change_id!r} is outside "
            f"the supported range [{min_supported}, {max_supported}]"
        )
        self.change_id = change_id
        self.version = version
        self.min_supported = min_supported
        self.max_supported = max_supported
        self.mismatch_type = (
            VERSION_MISMATCH_TOO_NEW
            if version > max_supported
            else VERSION_MISMATCH_TOO_OLD
        )


def validate_resolved_version(
    change_id: str,
    version: int,
    min_supported: int,
    max_supported: int,
) -> None:
    if version < min_supported or version > max_supported:
        fail_decision(
            VersionMismatchError(change_id, version, min_supported, max_supported)
        )


def change_version_search_attributes(
    change_id: str,
    version: int,
    existing_versions: Mapping[str, int],
) -> dict[str, SearchAttributeType | list[SearchAttributeType]]:
    """Build the Go SDK-compatible searchable change-version attribute."""
    values: list[SearchAttributeType] = [f"{change_id}-{version}"]
    values.extend(
        f"{existing_change_id}-{existing_version}"
        for existing_change_id, existing_version in sorted(existing_versions.items())
    )
    return {CADENCE_CHANGE_VERSION_SEARCH_ATTRIBUTE: values}
