import asyncio
from threading import current_thread

import pytest

from src.services.async_worker import AsyncWorker


@pytest.fixture
def worker():
    instance = AsyncWorker(name="test-worker")
    yield instance
    instance.close()


@pytest.mark.asyncio
async def test_call_returns_the_function_result(worker: AsyncWorker) -> None:
    assert await worker.call(lambda value: value * 2, 21) == 42


@pytest.mark.asyncio
async def test_call_propagates_the_original_exception(worker: AsyncWorker) -> None:
    def boom() -> None:
        raise ValueError("worker failure")

    with pytest.raises(ValueError, match="worker failure"):
        await worker.call(boom)


@pytest.mark.asyncio
async def test_call_runs_off_the_event_loop_thread(worker: AsyncWorker) -> None:
    caller_thread = current_thread().name

    assert await worker.call(lambda: current_thread().name) != caller_thread


@pytest.mark.asyncio
async def test_calls_are_serialized_in_submission_order(worker: AsyncWorker) -> None:
    order: list[int] = []

    results = await asyncio.gather(*(worker.call(order.append, index) for index in range(5)))

    assert order == [0, 1, 2, 3, 4]
    assert results == [None] * 5


@pytest.mark.asyncio
async def test_call_yields_to_other_tasks_while_waiting(worker: AsyncWorker) -> None:
    """The call must suspend on the future, not spin on a polling loop."""
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    background = asyncio.create_task(ticker())
    try:
        await worker.call(lambda: sum(range(100_000)))
    finally:
        background.cancel()

    assert ticks > 0
