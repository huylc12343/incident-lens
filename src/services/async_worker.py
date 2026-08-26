"""Small daemon worker for serialized blocking calls from async services."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from queue import Queue
from threading import Thread
from typing import Any


class AsyncWorker:
    def __init__(self, *, name: str) -> None:
        self._queue: Queue[tuple | None] = Queue()
        self._thread = Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    async def call(self, function: Callable[..., Any], *args, **kwargs):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._queue.put((loop, future, function, args, kwargs))
        return await future

    def close(self) -> None:
        self._queue.put(None)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            loop, future, function, args, kwargs = item
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                loop.call_soon_threadsafe(_set_exception, future, exc)
            else:
                loop.call_soon_threadsafe(_set_result, future, result)


def _set_result(future: asyncio.Future, result: Any) -> None:
    if not future.cancelled():
        future.set_result(result)


def _set_exception(future: asyncio.Future, exc: BaseException) -> None:
    if not future.cancelled():
        future.set_exception(exc)
