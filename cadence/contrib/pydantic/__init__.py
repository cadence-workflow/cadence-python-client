"""Pydantic v2 data converter for Cadence payloads.

Serializes payloads with ``pydantic_core.to_json`` and deserializes them
with ``pydantic.TypeAdapter``, so every type Pydantic supports works,
including ``BaseModel``, ``TypedDict``, dataclasses, and unions of
dict-like types that msgspec cannot compile. Pass
:class:`PydanticDataConverter` as the ``data_converter`` argument to
:class:`cadence.client.Client`:

.. code-block:: python

    from cadence.contrib.pydantic import PydanticDataConverter

    client = Client(
        domain="default",
        target="localhost:7833",
        data_converter=PydanticDataConverter(),
    )

Pydantic v1 is not supported.
"""

try:
    from cadence.contrib.pydantic._data_converter import PydanticDataConverter
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "PydanticDataConverter requires pydantic. "
        "Install with: pip install 'cadence-python-client[pydantic]'"
    ) from e

__all__ = ["PydanticDataConverter"]
