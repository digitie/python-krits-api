"""성공 결과의 제한된 TTL 캐시와 취소 가능한 동일 조회 공유."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from copy import deepcopy
from dataclasses import dataclass
import math
import time
from typing import TypeVar, cast

from .exceptions import KritsClosedError, KritsSchemaError

T = TypeVar("T")


@dataclass
class _Flight:
    task: asyncio.Task[object]
    waiters: int = 0


def _copy(value: T) -> T:
    try:
        return deepcopy(value)
    except RecursionError:
        raise KritsSchemaError("조회 결과의 중첩이 복사 가능한 범위를 넘었습니다") from None


async def _settle(task: asyncio.Future[T]) -> None:
    """정리 대상이 끝날 때까지 반복 취소에도 원격 자원 정리를 기다린다."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()


class RequestCache:
    """한 클라이언트의 완료 결과 LRU와 동일 진행 요청. 실패는 저장하지 않는다."""

    def __init__(self, ttl: float, max_entries: int) -> None:
        if isinstance(ttl, bool) or not math.isfinite(ttl) or ttl < 0:
            raise ValueError("cache_ttl은 유한한 0 이상 초여야 합니다")
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("cache_max_entries는 양의 정수여야 합니다")
        self.ttl = float(ttl)
        self.max_entries = max_entries
        self.closed = False
        self._entries: OrderedDict[Hashable, tuple[float, object]] = OrderedDict()
        self._flights: dict[Hashable, _Flight] = {}
        self._retiring: dict[Hashable, set[asyncio.Task[object]]] = {}
        self._tasks: set[asyncio.Task[object]] = set()
        self._generation = 0

    def clear(self) -> None:
        """완료 캐시를 비우며 현재 진행 중인 요청을 취소하지 않는다."""
        self._entries.clear()
        self._generation += 1

    async def get(self, key: Hashable, fetch: Callable[[], Awaitable[T]]) -> T:
        if self.closed:
            raise KritsClosedError("종료된 클라이언트입니다")
        entry = self._entries.get(key)
        if entry is not None:
            if entry[0] > time.monotonic():
                self._entries.move_to_end(key)
                return cast(T, _copy(entry[1]))
            del self._entries[key]
        flight = self._flights.get(key)
        if flight is None:
            generation = self._generation
            retiring = tuple(self._retiring.get(key, ()))

            async def produce() -> object:
                for previous in retiring:
                    try:
                        await asyncio.shield(previous)
                    except asyncio.CancelledError:
                        current = asyncio.current_task()
                        if current is not None and current.cancelling():
                            raise
                    except Exception:
                        pass  # 이전에 취소된 호출의 정리 실패를 새 호출에 상속하지 않는다.
                value = await fetch()
                if (self.ttl > 0 and not self.closed and generation == self._generation
                        and self._flights.get(key) is flight):
                    self._entries[key] = (time.monotonic() + self.ttl, _copy(value))
                    self._entries.move_to_end(key)
                    while len(self._entries) > self.max_entries:
                        self._entries.popitem(last=False)
                return value

            flight = _Flight(asyncio.create_task(produce()))
            self._flights[key] = flight
            self._tasks.add(flight.task)

            def done(task: asyncio.Task[object]) -> None:
                if self._flights.get(key) is flight:
                    del self._flights[key]
                retiring_tasks = self._retiring.get(key)
                if retiring_tasks is not None:
                    retiring_tasks.discard(task)
                    if not retiring_tasks:
                        del self._retiring[key]
                self._tasks.discard(task)
                if not task.cancelled():
                    task.exception()

            flight.task.add_done_callback(done)
        flight.waiters += 1
        try:
            return cast(T, _copy(await asyncio.shield(flight.task)))
        finally:
            flight.waiters -= 1
            if flight.waiters == 0 and not flight.task.done():
                if self._flights.get(key) is flight:
                    del self._flights[key]
                self._retiring.setdefault(key, set()).add(flight.task)
                flight.task.cancel()
                await _settle(flight.task)

    async def aclose(self) -> None:
        """진행 중 조회를 완료하고 보관한 값만 제거한다."""
        self.closed = True
        pending = tuple(self._tasks)
        try:
            if pending:
                joined = asyncio.gather(*pending, return_exceptions=True)
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError:
                    await _settle(joined)
                    raise
        finally:
            self.clear()
