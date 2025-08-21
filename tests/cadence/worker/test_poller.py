import asyncio

import pytest

from cadence.worker._poller import Poller


@pytest.mark.asyncio
async def test_poller():
    permits = asyncio.Semaphore(1)
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    poller = Poller(1, permits, incoming.get, outgoing.put)

    task = asyncio.create_task(poller.run())
    await incoming.put("foo")
    result = await outgoing.get()

    assert result == "foo"
    task.cancel()
    assert incoming.empty() is True
    assert outgoing.empty() is True

@pytest.mark.asyncio
async def test_poller_empty_task():
    permits = asyncio.Semaphore(1)
    incoming = asyncio.Queue()
    outgoing = asyncio.Queue()
    poller = Poller(1, permits, incoming.get, outgoing.put)

    task = asyncio.create_task(poller.run())
    await incoming.put(None)
    await incoming.put("foo")
    result = await outgoing.get()

    assert result == "foo"
    task.cancel()

@pytest.mark.asyncio
async def test_poller_num_tasks():
    permits = asyncio.Semaphore(10)

    count = 0
    all_waiting = asyncio.Event()
    done = asyncio.Event()

    async def poll_func():
        nonlocal count

        count += 1
        if count == 5 and not all_waiting.is_set():
            all_waiting.set()

        await done.wait()
        return "foo"

    outgoing = asyncio.Queue()
    poller = Poller(5, permits, poll_func, outgoing.put)
    task = asyncio.create_task(poller.run())

    async with asyncio.timeout(1):
        await all_waiting.wait()

    assert outgoing.empty() is True

    task.cancel()

@pytest.mark.asyncio
async def test_poller_concurrency():
    permits = asyncio.Semaphore(5)

    poll_count = 0
    count = 0
    all_waiting = asyncio.Event()
    done = asyncio.Event()

    async def infinite_tasks() -> str:
        nonlocal poll_count
        poll_count += 1
        return "foo"

    async def never_complete(_: str):
        nonlocal count, all_waiting, done
        count += 1
        if count == 5 and not all_waiting.is_set():
            all_waiting.set()

        await done.wait()

    poller = Poller(10, permits, infinite_tasks, never_complete)
    task = asyncio.create_task(poller.run())

    # Ensure we receive all 5
    async with asyncio.timeout(1):
        await all_waiting.wait()

    # Ensure no extra polls were issued
    assert poll_count == 5
    done.set()
    task.cancel()


@pytest.mark.asyncio
async def test_poller_poll_error():
    permits = asyncio.Semaphore(1)

    done = asyncio.Event()
    call_count = 0
    async def poll_func():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("oh no")
        elif call_count == 2:
            return "foo"
        else:
            await done.wait()
            return "bar"

    outgoing = asyncio.Queue()
    poller = Poller(1, permits, poll_func, outgoing.put)

    task = asyncio.create_task(poller.run())
    result = await outgoing.get()

    assert result == "foo"
    task.cancel()
    done.set()

@pytest.mark.asyncio
async def test_poller_execute_error():
    permits = asyncio.Semaphore(1)

    outgoing = asyncio.Queue()
    call_count = 0
    async def execute(item: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("oh no")
        await outgoing.put(item)

    incoming = asyncio.Queue()
    poller = Poller(1, permits, incoming.get, execute)

    task = asyncio.create_task(poller.run())
    await incoming.put("first")
    await incoming.put("second")
    result = await outgoing.get()

    assert result == "second"
    task.cancel()


