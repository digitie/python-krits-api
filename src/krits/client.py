"""ITS 공개 화면을 키 없이 탐색하는 native async 클라이언트."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from playwright.async_api import BrowserContext

from ._browser import BASE_URL, BrowserSession
from ._ratelimit import AsyncTokenBucket
from .exceptions import KritsAccessError, KritsNetworkError, KritsRateLimitError, KritsSchemaError
from .models import PageSnapshot

PublicPage = Literal["opendata", "traffic", "outbreak", "cctv", "detour", "travel_time", "nodelink"]
_PATHS: dict[str, str] = {
    "opendata": "/opendata/intro",
    "traffic": "/map/traffic",
    "outbreak": "/map/outbreak",
    "cctv": "/map/cctv",
    "detour": "/map/detour",
    "travel_time": "/map/travelTime",
    "nodelink": "/nodelink/nodelinkRef",
}


class KritsClient:
    """Chromium 공개 페이지 수집 기반. 자원은 첫 호출에서 생성한다.

    ``browser_context``를 주입하면 해당 context는 호출자가 닫는다.
    라이브러리가 만든 page는 라이브러리가 닫는다. 기본 수집 operation은
    1 RPS, burst=1, 자동 재시도 0이며 페이지 자산 전송 수의 제한은 아니다.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_rps: float = 1.0,
        rate_limiter: AsyncTokenBucket | None = None,
        browser_context: BrowserContext | None = None,
        executable_path: str | None = None,
    ) -> None:
        self._browser = BrowserSession(
            timeout=timeout, max_rps=max_rps, rate_limiter=rate_limiter,
            browser_context=browser_context, executable_path=executable_path,
        )

    @property
    def rate_limiter(self) -> AsyncTokenBucket:
        """여러 클라이언트에서 공유할 수 있는 실제 요청 제한기."""
        return self._browser.rate_limiter

    async def __aenter__(self) -> KritsClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """진행 중 요청 완료를 기다리고 소유 자원을 닫는다. 반복 호출은 안전하다."""
        await self._browser.aclose()

    async def get_page_snapshot(self, page: PublicPage = "opendata") -> PageSnapshot:
        """허용된 공개 화면의 제목·출처·수집 시각을 조회한다.

        이 메서드는 화면 접근의 확인용이며 교통정보 목록이나 파일 다운로드를 반환하지 않는다.
        """
        if page not in _PATHS:
            raise ValueError("지원하는 공개 페이지 이름이 아닙니다")
        url = BASE_URL + _PATHS[page]
        async with self._browser.operation() as browser_page:
            response = await browser_page.goto(url, wait_until="domcontentloaded")
            if response is None:
                raise KritsNetworkError("공개 페이지 응답이 없습니다")
            if response.status in (401, 403):
                raise KritsAccessError("공개 페이지 접근이 거부됐습니다")
            if response.status == 429:
                raise KritsRateLimitError("공개 페이지 호출 제한입니다")
            if response.status != 200:
                raise KritsNetworkError(f"공개 페이지 HTTP {response.status}")
            if browser_page.url != url:
                raise KritsAccessError("공개 페이지가 다른 경로로 이동했습니다")
            title = (await browser_page.title()).strip()
            if "ITS" not in title or "국가교통정보센터" not in title:
                raise KritsSchemaError("ITS 공개 페이지 제목 계약이 바뀌었습니다")
            return PageSnapshot(source_url=url, title=title, collected_at=datetime.now(timezone.utc))
