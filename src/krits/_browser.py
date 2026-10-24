"""Chromium의 지연 생성, 직렬 operation, 소유권과 취소 정리."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
import math
from typing import Any, TypeVar
from urllib.parse import urlsplit

from playwright.async_api import (
    BrowserContext,
    CDPSession,
    Error as PlaywrightError,
    Page,
    async_playwright,
)

from ._ratelimit import AsyncTokenBucket
from .exceptions import KritsClosedError, KritsNetworkError

BASE_URL = "https://www.its.go.kr"
T = TypeVar("T")


def _allowed_resource(raw_url: str, resource_type: str) -> bool:
    """소유 page의 허용 origin·자원 종류를 판정한다."""
    url = urlsplit(raw_url)
    return (
        url.scheme == "https"
        and url.netloc == "www.its.go.kr"
        and resource_type.lower() in {"document", "script", "stylesheet", "xhr", "fetch"}
    )


async def _intercept_request(session: CDPSession, event: dict[str, Any]) -> None:
    """리디렉션을 포함한 각 전송 전에 Chromium 요청을 종결한다."""
    request_id = event["requestId"]
    try:
        if _allowed_resource(event["request"]["url"], event["resourceType"]):
            await session.send("Fetch.continueRequest", {"requestId": request_id})
        else:
            await session.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
    except PlaywrightError:
        # page 종료로 자동 detach된 session에는 더 이상 전송할 요청이 없다.
        return


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
        session: CDPSession | None = None

        async def close_page(value: Page) -> None:
            try:
                await value.close()
            finally:
                if session is not None:
                    session.remove_listener("Fetch.requestPaused", intercept)
                    try:
                        await session.detach()
                    except PlaywrightError:
                        pass  # page.close가 이미 session을 detach한 경우

        async def intercept(event: dict[str, Any]) -> None:
            assert session is not None
            await _intercept_request(session, event)

        page = await self._acquire(context.new_page(), close_page)
        # page를 닫으면 생성 도중의 CDP session도 함께 해제된다.
        session = await context.new_cdp_session(page)
        session.on("Fetch.requestPaused", intercept)
        await session.send("Network.setBypassServiceWorker", {"bypass": True})
        await session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
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
        try:
            async with asyncio.timeout(self.timeout):
                async with self._lock:
                    if self._closed:
                        raise KritsClosedError("종료된 클라이언트입니다")
                    await self.rate_limiter.acquire()
                    try:
                        yield await self._ensure_page()
                    except BaseException as exc:
                        try:
                            await self._dispose()
                        except Exception:
                            self._closed = True
                            exc.add_note("브라우저 정리가 실패하여 클라이언트를 종료했습니다")
                        if isinstance(exc, PlaywrightError):
                            raise KritsNetworkError("Chromium 시작 또는 공개 페이지 통신 실패") from None
                        raise
        except TimeoutError:
            raise KritsNetworkError("Chromium operation 시간 제한을 초과했습니다") from None

    async def aclose(self) -> None:
        """진행 중 operation을 기다린 뒤 소유 자원만 닫는다."""
        self._bind_loop()
        async with self._lock:
            self._closed = True
            try:
                await self._dispose()
            except PlaywrightError:
                raise KritsNetworkError("Chromium 자원 정리 실패") from None
