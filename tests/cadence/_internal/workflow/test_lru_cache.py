"""Unit tests for cadence._internal.workflow.lru_cache.LRUCache."""

from cadence._internal.workflow.lru_cache import LRUCache


class TestBasicOperations:
    def test_get_miss_returns_none(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        assert cache.get("missing") is None

    def test_put_then_get(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        assert cache.put("A", "Foo") is None
        assert cache.get("A") == "Foo"

    def test_put_returns_previous_value_and_overwrites(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        cache.put("A", "Foo")
        assert cache.put("A", "Bar") == "Foo"
        assert cache.get("A") == "Bar"
        assert cache.size() == 1

    def test_exist(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        assert not cache.exist("A")
        cache.put("A", "Foo")
        assert cache.exist("A")

    def test_delete(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        cache.put("A", "Foo")
        cache.delete("A")
        assert cache.get("A") is None
        assert cache.size() == 0

    def test_delete_missing_key_is_noop(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        cache.delete("missing")
        assert cache.size() == 0

    def test_size(self) -> None:
        cache: LRUCache[int] = LRUCache(5)
        for i in range(3):
            cache.put(str(i), i)
        assert cache.size() == 3


class TestPutIfNotExist:
    def test_inserts_when_absent(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        assert cache.put_if_not_exist("A", "Foo") == "Foo"
        assert cache.get("A") == "Foo"

    def test_does_not_overwrite(self) -> None:
        cache: LRUCache[str] = LRUCache(5)
        cache.put_if_not_exist("A", "Foo")
        assert cache.put_if_not_exist("A", "Bar") == "Foo"
        assert cache.get("A") == "Foo"

    def test_refreshes_recency_of_existing(self) -> None:
        cache: LRUCache[str] = LRUCache(2)
        cache.put("A", "Foo")
        cache.put("B", "Bar")
        cache.put_if_not_exist("A", "ignored")
        cache.put("C", "Baz")
        assert cache.exist("A")
        assert not cache.exist("B")


class TestEviction:
    def test_holds_exactly_max_size_entries(self) -> None:
        cache: LRUCache[int] = LRUCache(3)
        for i in range(3):
            cache.put(str(i), i)
        assert cache.size() == 3
        assert all(cache.exist(str(i)) for i in range(3))

    def test_evicts_least_recently_inserted(self) -> None:
        cache: LRUCache[int] = LRUCache(3)
        for i in range(4):
            cache.put(str(i), i)
        assert cache.size() == 3
        assert not cache.exist("0")
        assert all(cache.exist(str(i)) for i in range(1, 4))

    def test_get_refreshes_recency(self) -> None:
        cache: LRUCache[int] = LRUCache(3)
        for i in range(3):
            cache.put(str(i), i)
        cache.get("0")
        cache.put("3", 3)
        assert cache.exist("0")
        assert not cache.exist("1")

    def test_put_existing_refreshes_recency(self) -> None:
        cache: LRUCache[int] = LRUCache(3)
        for i in range(3):
            cache.put(str(i), i)
        cache.put("0", 100)
        cache.put("3", 3)
        assert cache.get("0") == 100
        assert not cache.exist("1")

    def test_exist_does_not_refresh_recency(self) -> None:
        cache: LRUCache[int] = LRUCache(2)
        cache.put("0", 0)
        cache.put("1", 1)
        cache.exist("0")
        cache.put("2", 2)
        assert not cache.exist("0")


class TestRemovedFunc:
    def test_called_on_eviction(self) -> None:
        removed: list[str] = []
        cache: LRUCache[str] = LRUCache(2, removed_func=removed.append)
        cache.put("A", "Foo")
        cache.put("B", "Bar")
        assert removed == []
        cache.put_if_not_exist("C", "Baz")
        assert removed == ["Foo"]

    def test_called_on_delete(self) -> None:
        removed: list[str] = []
        cache: LRUCache[str] = LRUCache(2, removed_func=removed.append)
        cache.put("A", "Foo")
        cache.delete("A")
        assert removed == ["Foo"]

    def test_not_called_on_overwrite(self) -> None:
        removed: list[str] = []
        cache: LRUCache[str] = LRUCache(2, removed_func=removed.append)
        cache.put("A", "Foo")
        cache.put("A", "Bar")
        assert removed == []

    def test_can_reenter_cache(self) -> None:
        cache: LRUCache[str] = LRUCache(1)
        sizes: list[int] = []
        cache._removed_func = lambda _: sizes.append(cache.size())
        cache.put("A", "Foo")
        cache.put("B", "Bar")
        cache.delete("B")
        assert sizes == [1, 0]
