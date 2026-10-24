"""공유 버킷의 실제 대기·FIFO·취소와 유효성 검증."""

import asyncio
from unittest.mock import patch

import pytest

from krits import AsyncTokenBucket, KritsClient


@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan")])
def test_invalid_rps(value):
    with pytest.raises(ValueError):
        AsyncTokenBucket(value)


@pytest.mark.parametrize("value", [True, 0, 0.9, float("inf"), float("nan")])
def test_invalid_capacity(value):
    with pytest.raises(ValueError):
        AsyncTokenBucket(1, capacity=value)


async def test_refill_uses_monotonic_time():
    now = [0.0]
    waits = []

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    with patch("krits._ratelimit.time.monotonic", lambda: now[0]), \
            patch("krits._ratelimit.asyncio.sleep", sleep):
        bucket = AsyncTokenBucket(0.5)
        await bucket.acquire()
        await bucket.acquire()
    assert waits == [2.0]
    assert bucket.max_rps == 0.5
    assert bucket.capacity == 1


async def test_fifo_and_cancelled_waiter_progress():
    bucket = AsyncTokenBucket(100, capacity=1)
    await bucket.acquire()
    order = []

    async def wait(number):
        await bucket.acquire()
        order.append(number)

    first = asyncio.create_task(wait(1))
    second = asyncio.create_task(wait(2))
    third = asyncio.create_task(wait(3))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.gather(second, third)
    assert order == [2, 3]


def test_loop_affinity():
    bucket = AsyncTokenBucket()
    asyncio.run(bucket.acquire())
    with pytest.raises(RuntimeError, match="single event loop"):
        asyncio.run(bucket.acquire())


def test_shared_bucket_overrides_rps():
    bucket = AsyncTokenBucket(2)
    client = KritsClient(rate_limiter=bucket, max_rps=0)
    assert client.rate_limiter is bucket
    assert client.rate_limiter.max_rps == 2
