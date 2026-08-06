from typing import cast

from msgspec import DecodeError, json

from cadence.api.v1.common_pb2 import Payload
from cadence.workflow import VersioningOption


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
    change_id: str, min_supported: int, max_supported: int
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


def select_version(
    min_supported: int, max_supported: int, *options: VersioningOption
) -> int:
    custom_version: int | None = None
    use_min_version = False
    for option in options:
        if not isinstance(option, VersioningOption):
            raise ValueError("get_version options must be VersioningOption values")
        if option._kind == "version":
            custom_version = option._version
        elif option._kind == "min":
            use_min_version = True
        else:
            raise ValueError("invalid get_version option")
    if custom_version is not None:
        return custom_version
    if use_min_version:
        return min_supported
    return max_supported


def validate_selected_version(
    change_id: str, version: int, min_supported: int, max_supported: int
) -> None:
    if version < min_supported or version > max_supported:
        raise ValueError(
            f"selected version {version} for change_id {change_id!r} is outside "
            f"the supported range [{min_supported}, {max_supported}]"
        )
