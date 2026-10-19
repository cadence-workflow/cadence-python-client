import asyncio
import contextvars
import inspect
import logging

import pytest
from cadence._internal.workflow.deterministic_event_loop import (
    DecisionAbortedError,
    DeterministicEventLoop,
    FatalDecisionError,
    fail_decision,
)

_task_var: contextvars.ContextVar[str] = contextvars.ContextVar("_task_var")


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

    def test_create_task_eager_start(self):
        results: list[int] = []
        self.loop.create_task(coro_append(results, 1), eager_start=False)
        self.loop.run_until_yield()
        assert results == [1]

        coro = coro_append(results, 2)
        with pytest.raises(RuntimeError, match="eager_start"):
            self.loop.create_task(coro, eager_start=True)
        assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED

    def test_fail_decision_halts_loop_even_if_caught(self):
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
        assert results == ["caught"]

        # The loop stays failed: later runs raise without running workflow code.
        with pytest.raises(FatalDecisionError, match="fatal"):
            self.loop.run_until_yield()
        assert results == ["caught"]

    def test_fail_decision_from_wait_condition_predicate(self):
        calls_a: list[int] = []
        polls_b: list[int] = []
        waiters = []

        def pred_a() -> bool:
            calls_a.append(1)
            if len(calls_a) > 1:
                fail_decision(FatalDecisionError("fatal"))
            return False

        def pred_b() -> bool:
            polls_b.append(1)
            return False

        async def register():
            # Not awaited, so settling the first waiter schedules no work.
            waiters.append(self.loop.create_waiter(pred_a))
            waiters.append(self.loop.create_waiter(pred_b))

        self.loop.create_task(register())
        with pytest.raises(FatalDecisionError, match="fatal"):
            self.loop.run_until_yield()

        # The second predicate isn't polled again after the first one fails.
        assert polls_b == [1]
        waiters[0].exception()

    def test_close_unwinds_nested_task_groups(self):
        cleanup: list[str] = []

        async def child(level: int):
            try:
                await self.loop.create_future()
            finally:
                cleanup.append(f"child{level}")

        async def nest(level: int):
            if level == 0:
                await self.loop.create_future()
                return
            try:
                # Suspended inside each body, so every __aexit__ awaits its child
                # while handling the error.
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(child(level))
                    await nest(level - 1)
            finally:
                cleanup.append(f"level{level}")

        coro = nest(3)
        self.loop.create_task(coro)
        self.loop.run_until_yield()

        self.loop.close()

        assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
        assert sorted(cleanup) == [
            "child1",
            "child2",
            "child3",
            "level1",
            "level2",
            "level3",
        ]

    def test_close_gives_up_on_coroutine_that_never_stops_catching(self, caplog):
        catches: list[int] = []
        stop = False

        async def never_stops():
            while not stop:
                try:
                    await self.loop.create_future()
                except BaseException:
                    catches.append(1)

        coro = never_stops()
        self.loop.create_task(coro)
        self.loop.run_until_yield()

        self.loop.close()

        assert len(catches) > 1
        assert inspect.getcoroutinestate(coro) == inspect.CORO_SUSPENDED
        assert "could not be destroyed" in caplog.text

        # Let it exit so garbage collection doesn't hit the same loop.
        stop = True
        coro.close()

    @pytest.mark.parametrize(
        "interact",
        [
            lambda loop, coro: loop.run_until_yield(),
            lambda loop, coro: loop.run_until_complete(coro),
            lambda loop, coro: loop.abort_if_decision_failed(),
            lambda loop, coro: loop.create_task(coro),
        ],
        ids=[
            "run_until_yield",
            "run_until_complete",
            "abort_if_decision_failed",
            "create_task",
        ],
    )
    def test_interacting_after_close_raises_decision_aborted_error(self, interact):
        self.loop.close()
        coro = coro_append([], 0)

        with pytest.raises(DecisionAbortedError, match="workflow destroyed") as exc:
            interact(self.loop, coro)
        assert exc.value.__cause__ is None
        coro.close()

    def test_close_runs_finally_in_task_context(self, caplog):
        seen: list[str] = []

        async def paused():
            token = _task_var.set("task")
            try:
                await self.loop.create_future()
            finally:
                seen.append(_task_var.get("missing"))
                _task_var.reset(token)

        self.loop.create_task(paused())
        self.loop.run_until_yield()

        with caplog.at_level(logging.WARNING):
            self.loop.close()

        assert seen == ["task"]
        assert caplog.records == []

    def test_close_refuses_tasks_created_by_finally(self):
        ran: list[bool] = []
        refused: list[BaseException] = []

        async def spawned():
            ran.append(True)

        async def paused():
            try:
                await self.loop.create_future()
            finally:
                try:
                    asyncio.create_task(spawned())
                except FatalDecisionError as e:
                    refused.append(e)

        self.loop.create_task(paused())
        self.loop.run_until_yield()

        self.loop.close()

        assert ran == []
        assert len(refused) == 1

    def test_create_task_after_caught_fatal_error_raises(self):
        original = FatalDecisionError("fatal")
        refused: list[BaseException] = []

        async def keeps_going():
            try:
                fail_decision(original)
            except FatalDecisionError:
                pass
            try:
                asyncio.create_task(coro_append([], 0))
            except FatalDecisionError as e:
                refused.append(e)

        self.loop.create_task(keeps_going())
        with pytest.raises(FatalDecisionError) as exc_info:
            self.loop.run_until_yield()

        assert exc_info.value is original
        assert len(refused) == 1
        assert isinstance(refused[0], DecisionAbortedError)
        assert refused[0].__cause__ is original

    def test_create_task_after_fatal_error_keeps_original_context(self):
        original = FatalDecisionError("fatal")

        async def keeps_going():
            try:
                fail_decision(original)
            except FatalDecisionError:
                pass
            try:
                raise KeyError("unrelated")
            except KeyError:
                asyncio.create_task(coro_append([], 0))

        self.loop.create_task(keeps_going())
        with pytest.raises(FatalDecisionError) as exc_info:
            self.loop.run_until_yield()

        assert exc_info.value is original
        assert original.__context__ is None

    @pytest.mark.parametrize("fail_first", [True, False])
    def test_close_throws_decision_aborted_error(self, fail_first: bool):
        original = FatalDecisionError("original")
        seen: list[tuple[BaseException, bool]] = []

        async def paused():
            try:
                await self.loop.create_future()
            except BaseException as e:
                seen.append((e, asyncio.get_running_loop() is self.loop))
                raise

        async def fail():
            fail_decision(original)

        self.loop.create_task(paused())
        if fail_first:
            self.loop.create_task(fail())
            with pytest.raises(FatalDecisionError):
                self.loop.run_until_yield()
        else:
            self.loop.run_until_yield()

        self.loop.close()

        assert len(seen) == 1
        error, in_running_loop = seen[0]
        assert isinstance(error, DecisionAbortedError)
        assert error.__cause__ is (original if fail_first else None)
        assert in_running_loop
