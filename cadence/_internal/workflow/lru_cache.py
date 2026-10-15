"""Bounded LRU cache used for the sticky workflow cache."""

from collections import OrderedDict
from typing import Callable, Generic, TypeVar

V = TypeVar("V")

RemovedFunc = Callable[[V], None]


class LRUCache(Generic[V]):
    """Fixed size cache that evicts entries in LRU order.

    Not thread-safe: it is expected to be used only from the worker's event loop.

    ``removed_func``, if provided, is called with the value of every entry that
    is evicted or deleted. It is invoked after the entry has been removed, so it
    may safely call back into the cache.

    Values must never be ``None``: ``None`` is used to signal a missing value.
    """

    def __init__(
        self, max_size: int, removed_func: RemovedFunc[V] | None = None
    ) -> None:
        # Ordered least recently used first, most recently used last.
        self._entries: OrderedDict[str, V] = OrderedDict()
        self._max_size = max_size
        self._removed_func = removed_func

    def exist(self, key: str) -> bool:
        """Check if a given key exists in the cache without updating recency."""
        return key in self._entries

    def get(self, key: str) -> V | None:
        """Retrieve the value stored under the given key, or None if absent."""
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key: str, value: V) -> V | None:
        """Put a value under the given key, returning the previous value (if present)."""
        return self._put_internal(key, value, allow_update=True)

    def put_if_not_exist(self, key: str, value: V) -> V:
        """Put a value under the given key if it does not exist.

        Returns the value now stored in the cache: the existing one if the key
        was present, otherwise ``value``.
        """
        existing = self._put_internal(key, value, allow_update=False)
        return value if existing is None else existing

    def delete(self, key: str) -> None:
        """Delete the entry associated with the given key, if present."""
        if key not in self._entries:
            return
        self._notify_removed(self._entries.pop(key))

    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        return len(self._entries)

    def _put_internal(self, key: str, value: V, allow_update: bool) -> V | None:
        if key in self._entries:
            existing = self._entries[key]
            if allow_update:
                self._entries[key] = value
            self._entries.move_to_end(key)
            return existing

        self._entries[key] = value
        if len(self._entries) > self._max_size:
            _, oldest = self._entries.popitem(last=False)
            self._notify_removed(oldest)
        return None

    def _notify_removed(self, value: V) -> None:
        if self._removed_func is not None:
            self._removed_func(value)
