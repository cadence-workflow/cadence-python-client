"""Tests for the search_attributes module."""

import json
from datetime import datetime, timezone

import pytest

from cadence.api.v1.common_pb2 import Payload, SearchAttributes
from cadence.search_attributes import (
    CADENCE_CHANGE_VERSION,
    SearchAttributeConverter,
    validate_search_attributes,
)


@pytest.fixture
def converter() -> SearchAttributeConverter:
    return SearchAttributeConverter()


def make_search_attrs(attrs: dict[str, bytes]) -> SearchAttributes:
    result = SearchAttributes()
    for key, data in attrs.items():
        result.indexed_fields[key].CopyFrom(Payload(data=data))
    return result


class TestEncode:
    def test_string(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Status": "RUNNING"})
        assert result.indexed_fields["Status"].data == b'"RUNNING"'

    def test_int(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Count": 42})
        assert result.indexed_fields["Count"].data == b"42"

    def test_float(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Price": 99.99})
        assert result.indexed_fields["Price"].data == b"99.99"

    def test_bool(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"IsTrue": True, "IsFalse": False})
        assert result.indexed_fields["IsTrue"].data == b"true"
        assert result.indexed_fields["IsFalse"].data == b"false"

    def test_datetime(self, converter: SearchAttributeConverter) -> None:
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = converter.encode({"CreatedAt": dt})
        assert (
            json.loads(result.indexed_fields["CreatedAt"].data)
            == "2024-01-15T10:30:00+00:00"
        )

    def test_list_of_strings(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Tags": ["urgent", "customer"]})
        assert json.loads(result.indexed_fields["Tags"].data) == ["urgent", "customer"]

    def test_multiple_attributes(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Status": "RUNNING", "Count": 42})
        assert len(result.indexed_fields) == 2

    def test_empty_raises(self, converter: SearchAttributeConverter) -> None:
        with pytest.raises(ValueError, match="search attributes is empty"):
            converter.encode({})

    def test_list_of_ints(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Counts": [1, 2, 3]})
        assert json.loads(result.indexed_fields["Counts"].data) == [1, 2, 3]

    def test_nested_dict(self, converter: SearchAttributeConverter) -> None:
        result = converter.encode({"Meta": {"key": "value"}})
        assert json.loads(result.indexed_fields["Meta"].data) == {"key": "value"}


class TestDecode:
    def test_string(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"Status": b'"RUNNING"'})
        assert converter.decode(proto) == {"Status": "RUNNING"}

    def test_int(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"Count": b"42"})
        assert converter.decode(proto) == {"Count": 42}

    def test_float(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"Price": b"99.99"})
        assert converter.decode(proto) == {"Price": 99.99}

    def test_bool(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"IsTrue": b"true", "IsFalse": b"false"})
        assert converter.decode(proto) == {"IsTrue": True, "IsFalse": False}

    def test_list(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"Tags": b'["a", "b"]'})
        assert converter.decode(proto) == {"Tags": ["a", "b"]}

    def test_datetime_without_hint(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"CreatedAt": b'"2024-01-15T10:30:00"'})
        assert converter.decode(proto) == {"CreatedAt": "2024-01-15T10:30:00"}

    def test_datetime_with_hint(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"CreatedAt": b'"2024-01-15T10:30:00+00:00"'})
        result = converter.decode(proto, type_hints={"CreatedAt": datetime})
        assert result["CreatedAt"] == datetime(
            2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc
        )

    def test_empty_search_attributes(self, converter: SearchAttributeConverter) -> None:
        assert converter.decode(SearchAttributes()) == {}

    def test_empty_payload(self, converter: SearchAttributeConverter) -> None:
        proto = make_search_attrs({"Empty": b""})
        assert converter.decode(proto) == {"Empty": None}


class TestRoundTrip:
    @pytest.mark.parametrize(
        "attrs,type_hints",
        [
            ({"Status": "RUNNING"}, None),
            ({"Count": 42}, None),
            ({"Price": 99.99}, None),
            ({"IsPriority": True}, None),
            ({"Tags": ["a", "b"]}, None),
            ({"Counts": [1, 2, 3]}, None),
            (
                {"CreatedAt": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)},
                {"CreatedAt": datetime},
            ),
        ],
    )
    def test_roundtrip(
        self,
        converter: SearchAttributeConverter,
        attrs: dict[str, type],
        type_hints: dict[str, type] | None,
    ) -> None:
        encoded = converter.encode(attrs)
        decoded = converter.decode(encoded, type_hints=type_hints)
        assert decoded == attrs


class TestValidate:
    def test_valid(self) -> None:
        validate_search_attributes({"Status": "RUNNING", "Count": 42})

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="search attributes is empty"):
            validate_search_attributes({})

    def test_reserved_key_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved key"):
            validate_search_attributes({CADENCE_CHANGE_VERSION: ["v1"]})

    def test_reserved_key_allowed(self) -> None:
        validate_search_attributes(
            {CADENCE_CHANGE_VERSION: ["v1"]}, allow_reserved_keys=True
        )


def test_cadence_change_version_constant() -> None:
    assert CADENCE_CHANGE_VERSION == "CadenceChangeVersion"
