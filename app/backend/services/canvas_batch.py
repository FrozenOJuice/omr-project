import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar


Item = TypeVar("Item")
Result = TypeVar("Result")


@dataclass(frozen=True)
class BatchResult(Generic[Result]):
    value: Result | None = None
    error: Exception | None = None


async def bounded_map(
    items: Sequence[Item],
    operation: Callable[[Item], Awaitable[Result]],
    *,
    concurrency: int,
    timeout: float,
) -> list[BatchResult[Result]]:
    """Run independent work concurrently without exceeding a shared deadline."""
    semaphore = asyncio.Semaphore(concurrency)
    results: list[BatchResult[Result] | None] = [None] * len(items)

    async def run(index: int, item: Item) -> None:
        try:
            async with semaphore:
                results[index] = BatchResult(value=await operation(item))
        except Exception as exc:
            results[index] = BatchResult(error=exc)

    tasks = [
        asyncio.create_task(run(index, item))
        for index, item in enumerate(items)
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    return [
        result
        if result is not None
        else BatchResult(error=TimeoutError("Canvas operation timed out"))
        for result in results
    ]
