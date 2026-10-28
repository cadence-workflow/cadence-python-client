import asyncio

import pytest
from cadence._internal.workflow.deterministic_event_loop import (
    DecisionAbortedError,
    DeterministicEventLoop,
    FatalDecisionError,
    fail_decision,
)


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
        """When a waiter settles and schedules a task, waiter polling pauses.

        Contract: if resolving a waiter adds handles to ``_ready`` (someone
        ``await``s that waiter), ``_run_once`` returns so those handles run
        before sibling waiters are polled again. That ordering avoids the
        Temporal stale-wakeup race (temporalio/sdk-python#618). Waiters that
        settle without scheduling work do not block polling of later waiters
        in the same tick (Cadence Python review #9).
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

    def test_run_once_orphan_waiter_does_not_skip_following_waiters(self):
        """Orphan waiters that settle without scheduling work must not hide later waiters.

        Regression for review #9: breaking after the first ``poll()``-true waiter
        could leave a never-polled sibling in the same ``_run_once`` tick.
        """
        calls_p1 = {"n": 0}

        def pred1() -> bool:
            calls_p1["n"] += 1
            return calls_p1["n"] >= 2

        calls_p2: list[str] = []

        def pred2() -> bool:
            calls_p2.append("eval")
            return False

        self.loop._run_forever_setup()
        try:
            self.loop.create_waiter(pred1)
            self.loop.create_waiter(pred2)
            self.loop._run_once()
            assert calls_p1["n"] == 2
            # pred2 is polled at register time and again in _run_once; the bug
            # would skip the second poll entirely (only the first would exist).
            assert len(calls_p2) >= 2
        finally:
            self.loop._run_forever_cleanup()

    def test_fail_decision_raises_after_loop_yields(self):
        results: list[str] = []

        async def swallow_fatal():
            try:
                fail_decision(FatalDecisionError("fatal"))
            except BaseException:
                results.append("caught")
            await asyncio.sleep(0)
            results.append("resumed")

        self.loop.create_task(swallow_fatal())
        self.loop.call_soon(results.append, "other")

        with pytest.raises(FatalDecisionError, match="fatal"):
            self.loop.run_until_yield()
        assert results == ["caught", "other", "resumed"]

        # The failure is kept, so later runs raise it again.
        with pytest.raises(FatalDecisionError, match="fatal"):
            self.loop.run_until_yield()
        assert results == ["caught", "other", "resumed"]

    def test_fail_decision_from_wait_condition_predicate(self):
        waiters = []

        def predicate() -> bool:
            fail_decision(FatalDecisionError("fatal"))

        async def register():
            # Not awaited, so the failure only surfaces through the loop.
            waiters.append(self.loop.create_waiter(predicate))

        self.loop.create_task(register())
        with pytest.raises(FatalDecisionError, match="fatal"):
            self.loop.run_until_yield()
        waiters[0].exception()

    def test_abort_after_fatal_error_keeps_original_context(self):
        original = FatalDecisionError("fatal")
        aborted: list[BaseException] = []

        async def keeps_going():
            try:
                fail_decision(original)
            except FatalDecisionError:
                pass
            try:
                raise KeyError("unrelated")
            except KeyError:
                try:
                    self.loop.abort_if_decision_failed()
                except DecisionAbortedError as e:
                    aborted.append(e)

        self.loop.create_task(keeps_going())
        with pytest.raises(FatalDecisionError) as exc_info:
            self.loop.run_until_yield()

        assert exc_info.value is original
        assert len(aborted) == 1
        assert aborted[0].__cause__ is original
        assert original.__context__ is None
