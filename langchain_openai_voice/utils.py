import asyncio
from typing import AsyncIterator, TypeVar

T = TypeVar("T")


async def amerge(**streams: AsyncIterator[T]) -> AsyncIterator[tuple[str, T]]:
    """Merge multiple streams into one stream. 한 스트림에서 예외가 발생해도 나머지 스트림은 계속 동작하도록 개선."""
    nexts: dict[asyncio.Task, str] = {
        asyncio.create_task(anext(stream)): key for key, stream in streams.items()
    }
    while nexts:
        done, _ = await asyncio.wait(nexts, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            key = nexts.pop(task)
            stream = streams[key]
            try:
                yield key, task.result()
                nexts[asyncio.create_task(anext(stream))] = key
            except StopAsyncIteration:
                pass  # 해당 스트림만 종료, 나머지는 계속
            except Exception as e:
                print(f"amerge: 스트림 '{key}'에서 예외 발생: {e}")
                # 해당 스트림만 종료, 나머지는 계속
                pass
