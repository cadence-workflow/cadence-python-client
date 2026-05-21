"""Adapt :class:`cadence.workflow.ActiveClusterSelectionPolicy` (TypedDict) to its protobuf wire form."""

from __future__ import annotations

from typing import Mapping, cast

from cadence.api.v1 import common_pb2
from cadence.workflow import ActiveClusterSelectionPolicy


def active_cluster_selection_policy_to_proto(
    policy: ActiveClusterSelectionPolicy | Mapping[str, object] | None,
) -> common_pb2.ActiveClusterSelectionPolicy | None:
    """Convert a user active-cluster selection policy to protobuf, or ``None`` if empty.

    ``None`` and an empty mapping both map to ``None``.
    """
    if policy is None or (isinstance(policy, Mapping) and len(policy) == 0):
        return None

    out = common_pb2.ActiveClusterSelectionPolicy()

    if (ca := policy.get("cluster_attribute")) is not None:
        ca_map = cast(Mapping[str, str], ca)
        out.cluster_attribute.CopyFrom(
            common_pb2.ClusterAttribute(
                scope=ca_map.get("scope", ""),
                name=ca_map.get("name", ""),
            )
        )

    return out
