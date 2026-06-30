"""Unit tests for cadence._internal.workflow.waiter.Waiter."""

import pytest

from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop
from cadence._internal.workflow.waiter import Waiter


def make_loop() -> DeterministicEventLoop:
    return DeterministicEventLoop()


class TestWaiterPredicateAlreadyTrue:
    """When the predicate is already true, poll() should immediately settle."""

    def test_poll_returns_true(self) -> None:
        loop = make_loop()
        w = Waiter(lambda: True, loop)
        assert w.poll() is True

    def test_future_done_after_poll(self) -> None:
        loop = make_loop()
        w = Waiter(lambda: True, loop)
        w.poll()
        assert w.done()

    def test_result_is_none(self) -> None:
        loop = make_loop()
        w = Waiter(lambda: True, loop)
        w.poll()
        assert w.exception() is None
        w.result()


class TestWaiterFalseBecomesTrue:
    """Predicate starts false, later becomes true."""

    def test_first_poll_returns_false(self) -> None:
        loop = make_loop()
        state = {"v": False}
        w = Waiter(lambda: state["v"], loop)
        assert w.poll() is False
        assert not w.done()

    def test_second_poll_resolves(self) -> None:
        loop = make_loop()
        state = {"v": False}
        w = Waiter(lambda: state["v"], loop)
        w.poll()
        state["v"] = True
        assert w.poll() is True
        assert w.done()
        assert w.exception() is None
        w.result()

    def test_already_done_poll_is_idempotent(self) -> None:
        """Polling an already-settled waiter always returns True without re-running predicate."""
        loop = make_loop()
        calls: list[bool] = []

        def predicate() -> bool:
            calls.append(True)
            return True

        w = Waiter(predicate, loop)
        w.poll()
        call_count_after_first = len(calls)
        w.poll()  # second poll — future already done
        assert len(calls) == call_count_after_first  # predicate not called again


class TestWaiterPredicateRaises:
    """When the predicate raises, the exception is stored on the future."""

    def test_exception_stored(self) -> None:
        loop = make_loop()
        err = RuntimeError("predicate boom")
        w = Waiter(lambda: (_ for _ in ()).throw(err), loop)
        result = w.poll()
        assert result is True  # settled = evictable
        assert w.done()
        assert w.exception() is err

    def test_result_raises_stored_exception(self) -> None:
        loop = make_loop()
        err = ValueError("bad predicate")
        w = Waiter(lambda: (_ for _ in ()).throw(err), loop)
        w.poll()
        with pytest.raises(ValueError, match="bad predicate"):
            w.result()

    def test_base_exception_also_stored(self) -> None:
        """BaseException subclasses (not just Exception) are captured."""
        loop = make_loop()
        err = BaseException("base")
        w = Waiter(lambda: (_ for _ in ()).throw(err), loop)
        w.poll()
        assert w.exception() is err


class TestWaiterOrphan:
    """Orphan waiter: created but never polled / never resolves."""

    def test_done_is_false_without_poll(self) -> None:
        loop = make_loop()
        w = Waiter(lambda: False, loop)
        assert not w.done()

    def test_exception_is_none_without_poll(self) -> None:
        """exception() on an unsettled waiter raises InvalidStateError (Future contract)."""
        import asyncio

        loop = make_loop()
        w = Waiter(lambda: False, loop)
        with pytest.raises(asyncio.InvalidStateError):
            w.exception()

    def test_loop_poll_via_create_waiter(self) -> None:
        """create_waiter() with a never-true predicate leaves waiter in loop._waiters."""
        loop = make_loop()
        w = loop.create_waiter(lambda: False)
        assert not w.done()
        assert w in loop._waiters  # type: ignore[attr-defined]
