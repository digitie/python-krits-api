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
    Response,
    async_playwright,
)

from ._ratelimit import AsyncTokenBucket
from .exceptions import KritsAccessError, KritsClosedError, KritsNetworkError, KritsRateLimitError

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


async def _intercept_request(
    session: CDPSession, event: dict[str, Any], rate_limiter: AsyncTokenBucket | None = None,
    blocked: Callable[[], bool] | None = None,
) -> None:
    """리디렉션을 포함한 각 전송 전에 Chromium 요청을 종결한다."""
    request_id = event["requestId"]
    try:
        if _allowed_resource(event["request"]["url"], event["resourceType"]) and not (blocked and blocked()):
            if rate_limiter is not None:
                await rate_limiter.acquire()
            if blocked and blocked():
                await session.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
            else:
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
        self._denied_status: int | None = None

    def _raise_denial(self) -> None:
        if self._denied_status == 429:
            raise KritsRateLimitError("공개 웹 호출 제한입니다")
        if self._denied_status in (401, 403):
            raise KritsAccessError("공개 웹 접근이 거부됐습니다")

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
        self._denied_status = None
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
        pending: set[asyncio.Task[None]] = set()
        page: Page | None = None
        denial_closer: asyncio.Task[None] | None = None

        def observe_denial(response: Response) -> None:
            nonlocal denial_closer
            if response.status in (401, 403, 429) and _allowed_resource(response.url, response.request.resource_type):
                self._denied_status = self._denied_status or response.status
                if page is not None and denial_closer is None:
                    denial_closer = asyncio.create_task(page.close())
                    denial_closer.add_done_callback(lambda task: None if task.cancelled() else task.exception())

        async def close_page(value: Page) -> None:
            try:
                value.remove_listener("response", observe_denial)
                if session is not None:
                    session.remove_listener("Fetch.requestPaused", intercept)
                for task in tuple(pending):
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if denial_closer is not None:
                    try:
                        await denial_closer
                    except PlaywrightError:
                        pass
                await value.close()
            finally:
                if session is not None:
                    try:
                        await session.detach()
                    except PlaywrightError:
                        pass  # page.close가 이미 session을 detach한 경우

        def intercept(event: dict[str, Any]) -> asyncio.Task[None]:
            assert session is not None
            task = asyncio.create_task(_intercept_request(session, event, self.rate_limiter,
                                                        lambda: self._denied_status is not None))
            pending.add(task)

            def done(finished: asyncio.Task[None]) -> None:
                pending.discard(finished)
                if not finished.cancelled():
                    finished.exception()

            task.add_done_callback(done)
            return task

        page = await self._acquire(context.new_page(), close_page)
        page.on("response", observe_denial)
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
        """동시 navigation을 막는다. 각 실제 전송은 CDP 경계에서 공통 예산을 쓴다."""
        self._bind_loop()
        self.rate_limiter._bind_loop()
        try:
            async with asyncio.timeout(self.timeout):
                async with self._lock:
                    if self._closed:
                        raise KritsClosedError("종료된 클라이언트입니다")
                    try:
                        page = await self._ensure_page()
                        self._raise_denial()
                        yield page
                        self._raise_denial()
                    except BaseException as exc:
                        try:
                            await self._dispose()
                        except Exception:
                            self._closed = True
                            exc.add_note("브라우저 정리가 실패하여 클라이언트를 종료했습니다")
                        if not isinstance(exc, asyncio.CancelledError):
                            self._raise_denial()
                        if isinstance(exc, PlaywrightError):
                            raise KritsNetworkError("Chromium 시작 또는 공개 페이지 통신 실패") from None
                        raise
        except TimeoutError:
            self._raise_denial()
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
