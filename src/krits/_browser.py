"""Chromium의 지연 생성, 직렬 operation, 소유권과 취소 정리."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
import math
from typing import TypeVar
from urllib.parse import urlsplit

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Route,
    async_playwright,
)

from ._ratelimit import AsyncTokenBucket
from .exceptions import KritsClosedError, KritsNetworkError

BASE_URL = "https://www.its.go.kr"
T = TypeVar("T")


async def _filter_resource(route: Route) -> None:
    """수집 페이지에서 외부 지도·영상·이미지 전송을 차단한다."""
    url = urlsplit(route.request.url)
    if (
        url.scheme == "https"
        and url.netloc == "www.its.go.kr"
        and route.request.resource_type in {"document", "script", "stylesheet", "xhr", "fetch"}
    ):
        await route.continue_()
    else:
        await route.abort()


class BrowserSession:
    """하나의 이벤트 루프에서 사용하는 내부 Chromium 세션."""

    def __init__(
        self,
        *,
        timeout: float,
        max_rps: float,
        rate_limiter: AsyncTokenBucket | None,
        browser_context: BrowserContext | None,
        executable_path: str | None,
    ) -> None:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout은 유한한 양수여야 합니다")
        if browser_context is not None and executable_path is not None:
            raise ValueError("browser_context와 executable_path는 함께 지정할 수 없습니다")
        self.timeout = float(timeout)
        self.rate_limiter = rate_limiter or AsyncTokenBucket(max_rps, capacity=1)
        self._external_context = browser_context
        self._executable_path = executable_path
        self._page: Page | None = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("KritsClient는 한 이벤트 루프에서 사용해야 합니다")

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        self._stack = AsyncExitStack()
        context = self._external_context
        if context is None:
            playwright = await self._acquire(async_playwright().start(), lambda value: value.stop())
            browser = await self._acquire(
                playwright.chromium.launch(executable_path=self._executable_path),
                lambda value: value.close(),
            )
            context = await self._acquire(
                browser.new_context(service_workers="block"), lambda value: value.close(),
            )
        page = await self._acquire(context.new_page(), lambda value: value.close())
        await page.route("**/*", _filter_resource)
        page.set_default_timeout(self.timeout * 1000)
        self._page = page
        return page

    async def _acquire(self, creation: Awaitable[T], close: Callable[[T], Awaitable[None]]) -> T:
        # 생성 응답 직전에 취소돼도 원격에서 생성된 자원을 잃지 않는다.
        task = asyncio.ensure_future(creation)
        cancelled = False
        while True:
            try:
                resource = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        assert self._stack is not None
        self._stack.push_async_callback(close, resource)
        if cancelled:
            raise asyncio.CancelledError
        return resource

    async def _dispose(self) -> None:
        stack, self._stack = self._stack, None
        self._page = None
        if stack is None:
            return
        # 취소가 반복돼도 page/context/browser/driver 정리가 끝날 때까지 기다린다.
        task = asyncio.create_task(stack.aclose())
        try:
            await asyncio.shield(task)
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

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[Page]:
        """동시 navigation을 막고 operation마다 공유 예산을 적용한다."""
        self._bind_loop()
        async with self._lock:
            if self._closed:
                raise KritsClosedError("종료된 클라이언트입니다")
            await self.rate_limiter.acquire()
            try:
                async with asyncio.timeout(self.timeout):
                    yield await self._ensure_page()
            except BaseException as exc:
                try:
                    await self._dispose()
                except Exception:
                    self._closed = True
                    exc.add_note("브라우저 정리가 실패하여 클라이언트를 종료했습니다")
                if isinstance(exc, (PlaywrightError, TimeoutError)):
                    # Playwright 원문에는 쿠키·URL 등의 세션 정보가 포함될 수 있다.
                    raise KritsNetworkError("Chromium 시작 또는 공개 페이지 통신 실패") from None
                raise

    async def aclose(self) -> None:
        """진행 중 operation을 기다린 뒤 소유 자원만 닫는다."""
        self._bind_loop()
        async with self._lock:
            self._closed = True
            try:
                await self._dispose()
            except PlaywrightError:
                raise KritsNetworkError("Chromium 자원 정리 실패") from None
