"""ITS 공개 화면을 키 없이 탐색하는 native async 클라이언트."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import re
from typing import Literal

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, Request, Response

from ._browser import BASE_URL, BrowserSession
from ._ratelimit import AsyncTokenBucket
from .exceptions import (
    KritsAccessError, KritsNetworkError, KritsProviderError, KritsRateLimitError, KritsSchemaError,
)
from .models import DataSnapshot, PageSnapshot, Road, RoadEvent, RoadType, TrafficSection
from .parse import decode_json, parse_events, parse_roads, parse_traffic

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
_CONTAINERS = {
    "opendata": "a[href='/opendata/opendataList?service=traffic#moveApi']",
    "nodelink": "#moveData",
}
_ACCESS_TITLE = re.compile(r"로그인|보안\s*확인|접근\s*(?:제한|거부)|captcha|access denied", re.I)
_ACCESS_ELEMENTS = (
    "input[type='password']:visible, [id*='captcha' i]:visible, "
    "[class*='captcha' i]:visible, iframe[src*='captcha' i]:visible"
)
_ROADS_SCRIPT = """(elements) => elements.map(element => {
    const title = element.querySelector('.title_box .title');
    const name = title?.cloneNode(true);
    name?.querySelectorAll('span').forEach(span => span.remove());
    return {road_id: element.getAttribute('data-roadid'),
            road_number: title?.querySelector('span.road')?.textContent?.trim(),
            name: name?.textContent?.trim()};
})"""


def _check_status(status: int) -> None:
    if 300 <= status < 400:
        raise KritsAccessError("공개 웹 응답이 다른 경로로 이동합니다")
    if status in (401, 403):
        raise KritsAccessError("공개 웹 접근이 거부됐습니다")
    if status == 429:
        raise KritsRateLimitError("공개 웹 호출 제한입니다")
    if status != 200:
        raise KritsNetworkError(f"공개 웹 HTTP {status}")


def _road_type(value: RoadType) -> None:
    if value not in ("highway", "national"):
        raise ValueError("road_type은 highway 또는 national이어야 합니다")


async def _open_page(browser_page: Page, page: PublicPage) -> str:
    url = BASE_URL + _PATHS[page]
    response = await browser_page.goto(url, wait_until="domcontentloaded")
    if response is None:
        raise KritsNetworkError("공개 페이지 응답이 없습니다")
    _check_status(response.status)
    if browser_page.url != url:
        raise KritsAccessError("공개 페이지가 다른 경로로 이동했습니다")
    title = (await browser_page.title()).strip()
    if _ACCESS_TITLE.search(title) or await browser_page.locator(_ACCESS_ELEMENTS).count():
        raise KritsAccessError("로그인 또는 보안 확인 화면입니다")
    if "ITS" not in title or "국가교통정보센터" not in title:
        raise KritsSchemaError("ITS 공개 페이지 제목 계약이 바뀌었습니다")
    if not await browser_page.locator(_CONTAINERS.get(page, "#map")).count():
        raise KritsSchemaError("ITS 공개 페이지의 필수 컨테이너가 없습니다")
    return title


async def _action_json(
    page: Page, endpoint: str, action: Callable[[], Awaitable[object]],
    expected: dict[str, object],
) -> object:
    """이번 동작에서 시작한 요청만 관찰하며 listener를 성공·실패·취소 모두에서 제거한다."""
    requests: set[Request] = set()
    url = BASE_URL + endpoint
    denied_status: int | None = None

    def observe_denial(response: Response) -> None:
        nonlocal denied_status
        if response.url == url and response.status in (401, 403, 429) and denied_status is None:
            denied_status = response.status

    def track(request: Request) -> None:
        if request.url != url or request.method != "POST":
            return
        try:
            encoded = request.post_data_json
            if not isinstance(encoded, dict) or not isinstance(encoded.get("body"), dict):
                return
            data = encoded["body"].get("data")
            if isinstance(data, dict) and all(data.get(key) == value for key, value in expected.items()):
                requests.add(request)
        except (ValueError, KeyError, TypeError, PlaywrightError):
            return

    page.on("request", track)
    page.on("response", observe_denial)
    try:
        async with page.expect_response(lambda response: response.request in requests) as pending:
            await action()
            if denied_status is not None:
                _check_status(denied_status)
        response = await pending.value
        if denied_status is not None:
            _check_status(denied_status)
        _check_status(response.status)
        if response.url != url:
            raise KritsAccessError("공개 웹 응답이 다른 경로로 이동했습니다")
        text = await response.text()
        if text.lstrip().startswith("<") and re.search(r"로그인|captcha|password|접근\s*(?:제한|거부)", text, re.I):
            raise KritsAccessError("공개 웹 응답이 로그인 또는 보안 확인 화면입니다")
        payload = decode_json(text)
        if denied_status is not None:
            _check_status(denied_status)
        if isinstance(payload, dict) and isinstance(payload.get("header"), dict):
            if payload["header"].get("state") != "OK":
                raise KritsProviderError("공개 웹 제공자가 처리 실패를 반환했습니다")
        return payload
    finally:
        page.remove_listener("request", track)
        page.remove_listener("response", observe_denial)


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
            title = await _open_page(browser_page, page)
            return PageSnapshot(source_url=url, title=title, collected_at=datetime.now(timezone.utc))

    async def list_roads(self, *, road_type: RoadType = "highway") -> DataSnapshot[Road]:
        """공개 교통 화면에 있는 도로 ID·노선번호·이름을 순서대로 조회한다."""
        _road_type(road_type)
        async with self._browser.operation() as page:
            await _open_page(page, "traffic")
            rows = await page.locator(f"#ul_{road_type} li.dep1").evaluate_all(_ROADS_SCRIPT)
            return DataSnapshot(parse_roads(rows, road_type), BASE_URL + _PATHS["traffic"],
                                datetime.now(timezone.utc), {"road_type": road_type})

    async def get_traffic(
        self, road_id: str, *, road_type: RoadType = "highway", direction: str | None = None,
    ) -> DataSnapshot[TrafficSection]:
        """선택한 도로·방향의 구간과 개별 링크를 조회한다.

        road_id는 list_roads의 4자리 ID이며 표시 노선번호가 아니다.
        방향 코드는 고속도로 1/2, 국도 3/4다. 기본은 각각 1/3이다.
        """
        _road_type(road_type)
        if not isinstance(road_id, str) or re.fullmatch(r"[0-9]{4}", road_id) is None:
            raise ValueError("road_id는 list_roads에서 얻은 4자리 문자열이어야 합니다")
        directions = ("1", "2") if road_type == "highway" else ("3", "4")
        selected = directions[0] if direction is None else direction
        if selected not in directions:
            raise ValueError("도로 종류에 맞는 문자열 방향 코드를 지정해야 합니다")
        async with self._browser.operation() as page:
            await _open_page(page, "traffic")
            rows = await page.locator(f"#ul_{road_type} li.dep1").evaluate_all(_ROADS_SCRIPT)
            roads = parse_roads(rows, road_type)
            road = next((item for item in roads if item.road_id == road_id), None)
            if road is None:
                raise ValueError("공개 화면의 도로 목록에 없는 road_id입니다")
            await page.get_by_role("tab", name="고속도로" if road_type == "highway" else "국도", exact=True).click()
            target = page.locator(f"#ul_{road_type} li.dep1[data-roadid='{road_id}']")
            # 반대방향 버튼이 변경하는 것과 같은 화면 내부 방향 값을 지정한다.
            await target.evaluate("(element, direction) => window.jQuery(element).data('drct', Number(direction))", selected)
            payload = await _action_json(page, "/map/getLinks", target.locator("button.open").click,
                                         {"roadId": road_id, "drct": int(selected), "type": "0" if road_type == "highway" else "1"})
            return DataSnapshot(parse_traffic(payload, road, selected), BASE_URL + _PATHS["traffic"],
                                datetime.now(timezone.utc), {"road_type": road_type, "road_id": road_id, "direction": selected})

    async def get_events(self, *, road_type: RoadType | None = None) -> DataSnapshot[RoadEvent]:
        """현재 공개 돌발 목록의 고속도로·국도 항목을 조회한다. 재난 분기는 포함하지 않는다."""
        if road_type is not None:
            _road_type(road_type)
        async with self._browser.operation() as page:
            # 이전 문서의 timer/요청과 분리한 뒤 최초 데이터 요청부터 관찰한다.
            await page.goto("about:blank")
            payload = await _action_json(
                page, "/map/getMarkers", lambda: _open_page(page, "outbreak"),
                {"type": "", "id": None, "drct": None, "keyword": ""},
            )
            return DataSnapshot(parse_events(payload, road_type), BASE_URL + _PATHS["outbreak"],
                                datetime.now(timezone.utc), {"road_type": road_type or "all", "excluded": "DISASTER"})
