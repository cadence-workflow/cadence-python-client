"""Bounded LRU cache used for the sticky workflow cache."""

import threading
from collections import OrderedDict
from typing import Callable, Generic, TypeVar

V = TypeVar("V")

RemovedFunc = Callable[[V], None]


class LRUCache(Generic[V]):
    """Thread-safe fixed size cache that evicts entries in LRU order.

    ``removed_func``, if provided, is called with the value of every entry that
    is evicted or deleted. It is invoked after the internal lock is released,
    so it may safely call back into the cache.

    Values must never be ``None``: ``None`` is used to signal a missing value.
    """

    def __init__(
        self, max_size: int, removed_func: RemovedFunc[V] | None = None
    ) -> None:
        self._lock = threading.Lock()
        # Ordered least recently used first, most recently used last.
        self._entries: OrderedDict[str, V] = OrderedDict()
        self._max_size = max_size
        self._removed_func = removed_func

    def exist(self, key: str) -> bool:
        """Check if a given key exists in the cache without updating recency."""
        with self._lock:
            return key in self._entries

    def get(self, key: str) -> V | None:
        """Retrieve the value stored under the given key, or None if absent."""
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return self._entries[key]

    def put(self, key: str, value: V) -> V | None:
        """Put a value under the given key, returning the previous value (if present)."""
        existing, evicted = self._put_internal(key, value, allow_update=True)
        self._notify_removed(evicted)
        return existing

    def put_if_not_exist(self, key: str, value: V) -> V:
        """Put a value under the given key if it does not exist.

        Returns the value now stored in the cache: the existing one if the key
        was present, otherwise ``value``.
        """
        existing, evicted = self._put_internal(key, value, allow_update=False)
        self._notify_removed(evicted)
        return value if existing is None else existing

    def delete(self, key: str) -> None:
        """Delete the entry associated with the given key, if present."""
        with self._lock:
            if key not in self._entries:
                return
            removed = self._entries.pop(key)
        self._notify_removed(removed)

    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        with self._lock:
            return len(self._entries)

    def _put_internal(
        self, key: str, value: V, allow_update: bool
    ) -> tuple[V | None, V | None]:
        with self._lock:
            if key in self._entries:
                existing = self._entries[key]
                if allow_update:
                    self._entries[key] = value
                self._entries.move_to_end(key)
                return existing, None

            self._entries[key] = value
            if len(self._entries) > self._max_size:
                _, oldest = self._entries.popitem(last=False)
                return None, oldest
            return None, None

    def _notify_removed(self, value: V | None) -> None:
        if value is not None and self._removed_func is not None:
            self._removed_func(value)
