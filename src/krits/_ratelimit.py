"""비동기 HTTP 호출의 TPS를 제어하는 공통 토큰 버킷 구현."""

from __future__ import annotations

import asyncio
import math
import time


class AsyncTokenBucket:
    """한 이벤트 루프에서 FIFO 순서로 토큰을 배분한다.

    ``max_rps``는 초당 충전량이며 ``capacity``는 허용할 초기/최대 burst다.
    기본 용량은 ``max(1, max_rps)``이므로 1 TPS 미만도 지원한다.
    대기 중 취소된 호출은 토큰을 소비하지 않고 다음 호출에 자리를 넘긴다.
    같은 공급자 quota를 공유하는 요청에는 같은 인스턴스를 사용한다.
    """

    def __init__(self, max_rps: float = 5.0, capacity: float | None = None) -> None:
        if isinstance(max_rps, bool) or not math.isfinite(max_rps) or max_rps <= 0:
            raise ValueError("max_rps must be a finite number greater than 0")
        resolved_capacity = max(1.0, max_rps) if capacity is None else capacity
        if (
            isinstance(resolved_capacity, bool)
            or not math.isfinite(resolved_capacity)
            or resolved_capacity < 1
        ):
            raise ValueError("capacity must be a finite number greater than or equal to 1")
        self._max_rps = float(max_rps)
        self._capacity = float(resolved_capacity)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def max_rps(self) -> float:
        """초당 토큰 충전량."""
        return self._max_rps

    @property
    def capacity(self) -> float:
        """최대로 저장할 토큰 수."""
        return self._capacity

    async def acquire(self) -> None:
        """요청 하나에 필요한 토큰이 생길 때까지 비동기로 대기한다."""
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("AsyncTokenBucket must be used on a single event loop")
        # 선두 호출만 충전을 기다린다. asyncio.Lock의 FIFO/취소 처리를 사용해
        # 별도 timer나 Future 큐 없이 후속 호출의 진행을 보장한다.
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = max(0.0, now - self._updated_at)
                self._updated_at = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._max_rps)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._max_rps)
