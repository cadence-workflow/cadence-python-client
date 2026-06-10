from collections.abc import Callable
from threading import Event, Lock


class _ActivityCancellation:
    def __init__(self) -> None:
        self._requested = Event()
        self._lock = Lock()
        self._callbacks: list[Callable[[], None]] = []

    def request(self) -> None:
        with self._lock:
            if self._requested.is_set():
                return
            self._requested.set()
            callbacks = list(self._callbacks)

        for callback in callbacks:
            callback()

    def is_requested(self) -> bool:
        return self._requested.is_set()

    def wait(self) -> None:
        self._requested.wait()

    def register_cancel_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if not self._requested.is_set():
                self._callbacks.append(callback)
                return

        callback()
