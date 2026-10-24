"""MOIS 방식의 취소 안전한 thread 파일 작업."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


async def run_file_io(fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """취소돼도 실행 중인 파일 작업이 끝난 뒤 호출자에게 자원을 반환한다."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise
