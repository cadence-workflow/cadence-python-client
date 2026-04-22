import pytest
import asyncio
from cadence._internal.workflow.deterministic_event_loop import DeterministicEventLoop


async def coro_append(results: list[int], i: int):
    results.append(i)


async def coro_await(size: int):
    results: list[int] = []
    for i in range(size):
        await coro_append(results, i)
    return results


async def coro_await_future(future: asyncio.Future):
    return await future


async def coro_await_task(size: int):
    results: list[int] = []
    for i in range(size):
        asyncio.create_task(coro_append(results, i))
    return results


class TestDeterministicEventLoop:
    """Test suite for DeterministicEventLoop using table-driven tests."""

    def setup_method(self):
        """Setup method called before each test."""
        self.loop = DeterministicEventLoop()

    def teardown_method(self):
        """Teardown method called after each test."""
        if not self.loop.is_closed():
            self.loop.close()
        assert self.loop.is_closed() is True

    def test_call_soon(self):
        """Test _run_once executes single callback."""
        results: list[int] = []
        expected: list[int] = []
        for i in range(10000):
            expected.append(i)

            def add_to_result(result: int):
                results.append(result)

            self.loop.call_soon(add_to_result, i)

        self.loop._run_once()

        assert results == expected
        assert self.loop.is_running() is False

    def test_run_until_complete(self):
        size = 10000
        results = self.loop.run_until_complete(coro_await(size))
        assert results == list(range(size))
        assert self.loop.is_running() is False
        assert self.loop.is_closed() is False

    @pytest.mark.parametrize(
        "result, exception, expected, expected_exception",
        [(10000, None, 10000, None), (None, ValueError("test"), None, ValueError)],
    )
    def test_create_future(self, result, exception, expected, expected_exception):
        future = self.loop.create_future()
        if expected_exception is not None:
            with pytest.raises(expected_exception):
                future.set_exception(exception)
                self.loop.run_until_complete(coro_await_future(future))
        else:
            future.set_result(result)
            assert self.loop.run_until_complete(coro_await_future(future)) == expected

    def test_create_task(self):
        size = 10000
        results = self.loop.run_until_complete(coro_await_task(size))
        assert results == list(range(size))

    def test_run_once(self):
        # run once won't clear the read queue
        self.loop.create_task(coro_await_task(10))
        self.loop.stop()
        self.loop.run_forever()
        assert len(self.loop._ready) == 10
        # Drain child tasks so teardown does not drop un-awaited coroutines.
        self.loop.run_until_yield()
        assert len(self.loop._ready) == 0

        self.loop.run_until_yield()
        assert len(self.loop._ready) == 0

    def test_run_until_yield(self):
        # run until yield will clear the read queue
        task = self.loop.create_task(coro_await_task(3))
        self.loop.run_until_yield()
        assert len(self.loop._ready) == 0
        assert task.done() is True

    def test_run_once_resolves_one_waiter_per_tick(self):
        """_run_once pops exactly one ready waiter per tick.

        Contract being tested: when multiple waiters share a predicate that
        becomes True, only the first one is resolved in a given _run_once call.
        The second waiter is only evaluated — and potentially resolved — in the
        *next* tick, after the first waiter's continuation has run (and may have
        mutated the state the predicate reads).  This is the fix for the
        Temporal SDK stale-wakeup race (temporalio/sdk-python#618).
        """
        flag = [False]
        resolved: list[str] = []

        async def wait_and_record(label: str) -> None:
            await self.loop.create_waiter(lambda: flag[0])
            resolved.append(label)

        # Two tasks both waiting on the same flag.
        self.loop._run_forever_setup()
        try:
            task_a = self.loop.create_task(wait_and_record("a"))
            task_b = self.loop.create_task(wait_and_record("b"))

            # Advance until both tasks are suspended on their waiters.
            while self.loop._ready:
                self.loop._run_once()

            assert len(self.loop._waiters) == 2
            assert resolved == []

            # Flip the flag — both waiters' predicates are now True.
            flag[0] = True

            # A single _run_once should resolve exactly ONE waiter and leave
            # the other still in _waiters.
            self.loop._run_once()

            assert len(self.loop._waiters) == 1, (
                "exactly one waiter must remain after one tick"
            )
            assert len(self.loop._ready) == 1, (
                "the resolved waiter's continuation must be scheduled"
            )

            # Run the resolved continuation — it records its label.
            self.loop._run_once()
            assert resolved == ["a"]

            # Now the second waiter is re-evaluated.  flag is still True, so it
            # also resolves on this tick.
            self.loop._run_once()
            assert len(self.loop._waiters) == 0
            assert resolved == ["a", "b"]
        finally:
            self.loop._run_forever_cleanup()
            task_a.cancel()
            task_b.cancel()
