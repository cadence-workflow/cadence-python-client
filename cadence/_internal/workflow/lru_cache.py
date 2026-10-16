"""Bounded LRU cache used for the sticky workflow cache."""

from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Hashable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class LRUCacheWithHooks:
    """Decorator that memoizes a function in a fixed size LRU cache.

    The cache key is built from the decorated function's arguments. On a miss
    the function is called and its result is cached; on a hit the cached result
    is returned without calling the function. When the cache is full, the least
    recently used entry is evicted to make room.

    Optional hooks are invoked on cache events, e.g. to emit metrics:
    ``on_hit(key)``, ``on_miss(key)`` and ``on_evict(key, value)``.

    Not thread-safe: it is expected to be used only from the worker's event loop.
    """

    def __init__(
        self,
        maxsize: int,
        on_hit: Callable[[Hashable], None] | None = None,
        on_miss: Callable[[Hashable], None] | None = None,
        on_evict: Callable[[Hashable, Any], None] | None = None,
    ) -> None:
        self.maxsize = maxsize
        # Ordered least recently used first, most recently used last.
        self.cache: OrderedDict[Hashable, Any] = OrderedDict()
        self.on_hit = on_hit
        self.on_miss = on_miss
        self.on_evict = on_evict

    def __call__(self, func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = (args, tuple(sorted(kwargs.items())))

            if key in self.cache:
                if self.on_hit:
                    self.on_hit(key)
                self.cache.move_to_end(key)
                cached: R = self.cache[key]
                return cached

            if self.on_miss:
                self.on_miss(key)

            result = func(*args, **kwargs)

            if len(self.cache) >= self.maxsize:
                evicted_key, evicted_value = self.cache.popitem(last=False)
                if self.on_evict:
                    self.on_evict(evicted_key, evicted_value)

            self.cache[key] = result
            return result

        # Expose cache utilities similar to functools.lru_cache
        wrapper.cache_clear = self.cache.clear  # type: ignore[attr-defined]
        wrapper.cache = self.cache  # type: ignore[attr-defined]
        return wrapper
