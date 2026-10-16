"""Unit tests for cadence._internal.workflow.lru_cache.LRUCacheWithHooks."""

from typing import Any, Hashable

from cadence._internal.workflow.lru_cache import LRUCacheWithHooks


def key(*args: Any, **kwargs: Any) -> Hashable:
    return (args, tuple(sorted(kwargs.items())))


class TestMemoization:
    def test_miss_calls_function(self) -> None:
        calls: list[str] = []

        @LRUCacheWithHooks(maxsize=5)
        def load(run_id: str) -> str:
            calls.append(run_id)
            return f"ctx-{run_id}"

        assert load("a") == "ctx-a"
        assert calls == ["a"]

    def test_hit_returns_cached_value_without_calling_function(self) -> None:
        calls: list[str] = []

        @LRUCacheWithHooks(maxsize=5)
        def load(run_id: str) -> str:
            calls.append(run_id)
            return f"ctx-{run_id}"

        load("a")
        assert load("a") == "ctx-a"
        assert calls == ["a"]

    def test_key_includes_kwargs_independent_of_order(self) -> None:
        calls: list[tuple[int, int]] = []

        @LRUCacheWithHooks(maxsize=5)
        def add(x: int, y: int) -> int:
            calls.append((x, y))
            return x + y

        assert add(x=1, y=2) == 3
        assert add(y=2, x=1) == 3
        assert calls == [(1, 2)]

    def test_preserves_function_metadata(self) -> None:
        @LRUCacheWithHooks(maxsize=5)
        def load(run_id: str) -> str:
            """Load a context."""
            return run_id

        assert load.__name__ == "load"
        assert load.__doc__ == "Load a context."

    def test_exception_is_not_cached(self) -> None:
        calls: list[str] = []
        cache = LRUCacheWithHooks(maxsize=5)

        @cache
        def load(run_id: str) -> str:
            calls.append(run_id)
            raise ValueError("boom")

        for _ in range(2):
            try:
                load("a")
            except ValueError:
                pass
        assert calls == ["a", "a"]
        assert len(cache.cache) == 0


class TestEviction:
    def test_holds_exactly_maxsize_entries(self) -> None:
        cache = LRUCacheWithHooks(maxsize=3)

        @cache
        def load(i: int) -> int:
            return i

        for i in range(3):
            load(i)
        assert list(cache.cache) == [key(0), key(1), key(2)]

    def test_evicts_least_recently_used(self) -> None:
        cache = LRUCacheWithHooks(maxsize=3)

        @cache
        def load(i: int) -> int:
            return i

        for i in range(4):
            load(i)
        assert list(cache.cache) == [key(1), key(2), key(3)]

    def test_hit_refreshes_recency(self) -> None:
        cache = LRUCacheWithHooks(maxsize=3)

        @cache
        def load(i: int) -> int:
            return i

        for i in range(3):
            load(i)
        load(0)
        load(3)
        assert list(cache.cache) == [key(2), key(0), key(3)]

    def test_cache_clear(self) -> None:
        evicted: list[Hashable] = []
        cache = LRUCacheWithHooks(maxsize=3, on_evict=lambda k, v: evicted.append(k))

        @cache
        def load(i: int) -> int:
            return i

        load(0)
        cache.cache_clear()
        assert len(cache.cache) == 0
        assert evicted == []


class TestHooks:
    def test_hooks_called_on_events(self) -> None:
        events: list[tuple[Any, ...]] = []
        cache = LRUCacheWithHooks(
            maxsize=2,
            on_hit=lambda k: events.append(("hit", k)),
            on_miss=lambda k: events.append(("miss", k)),
            on_evict=lambda k, v: events.append(("evict", k, v)),
        )

        @cache
        def load(run_id: str) -> str:
            return f"ctx-{run_id}"

        for run_id in ["a", "b", "a", "c"]:
            load(run_id)

        assert events == [
            ("miss", key("a")),
            ("miss", key("b")),
            ("hit", key("a")),
            ("miss", key("c")),
            ("evict", key("b"), "ctx-b"),
        ]

    def test_hooks_are_optional(self) -> None:
        @LRUCacheWithHooks(maxsize=1)
        def load(run_id: str) -> str:
            return run_id

        for run_id in ["a", "a", "b"]:
            load(run_id)
