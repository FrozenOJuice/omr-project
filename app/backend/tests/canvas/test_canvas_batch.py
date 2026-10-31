import asyncio

import pytest

from services.canvas_batch import bounded_map


@pytest.mark.asyncio
async def test_bounded_map_preserves_order_and_limits_concurrency():
    active = peak = 0

    async def work(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return value * 2

    results = await bounded_map(
        list(range(8)), work, concurrency=2, timeout=1
    )

    assert [result.value for result in results] == list(range(0, 16, 2))
    assert all(result.error is None for result in results)
    assert peak == 2


@pytest.mark.asyncio
async def test_bounded_map_cancels_work_at_the_shared_deadline():
    cancelled = 0

    async def work(_value: int) -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled += 1

    results = await bounded_map([1, 2, 3], work, concurrency=2, timeout=0.01)

    assert all(isinstance(result.error, TimeoutError) for result in results)
    assert cancelled == 2


@pytest.mark.asyncio
async def test_bounded_map_isolates_individual_failures():
    async def work(value: int) -> int:
        if value == 2:
            raise ValueError("bad item")
        return value

    results = await bounded_map([1, 2, 3], work, concurrency=3, timeout=1)

    assert [result.value for result in results] == [1, None, 3]
    assert isinstance(results[1].error, ValueError)
