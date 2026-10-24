"""ITS 공개 화면을 키 없이 탐색하는 native async 클라이언트."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from functools import wraps
from inspect import signature
import re
from typing import Literal, ParamSpec, TypeVar, cast

from playwright.async_api import BrowserContext, Error as PlaywrightError, Locator, Page, Request, Response

from ._browser import BASE_URL, BrowserSession
from ._cache import RequestCache, _settle
from ._ratelimit import AsyncTokenBucket
from .files import DEFAULT_MAX_BYTES, download_file, validate_attachment
from .storage import FileStore
from .exceptions import (
    KritsAccessError, KritsClosedError, KritsNetworkError, KritsProviderError, KritsRateLimitError, KritsSchemaError,
)
from .models import Cctv, DataSnapshot, Detour, DetourRoad, FileAttachment, NodeLinkRelease, OpenDataService, PageSnapshot, Road, RoadEvent, RoadType, StoredFile, TrafficSection, TravelTime
from .parse import (decode_json, parse_cctvs, parse_detour_roads, parse_detours, parse_events,
                    nodelink_dom_ids, open_data_ids, parse_nodelink_releases, parse_open_data, parse_origins, parse_roads, parse_traffic,
                    parse_travel_times, parse_weak_files)

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
P = ParamSpec("P")
R = TypeVar("R")


def _cached_query(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """기본 인자까지 정규화해 같은 공개 조회만 공유한다."""
    parameters = signature(function)

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        owner = cast("KritsClient", args[0])
        owner._browser._bind_loop()
        if owner._query_cache.closed or owner._browser._closed:
            raise KritsClosedError("종료된 클라이언트입니다")
        if owner._browser._denied_status is not None:
            owner._query_cache.clear()
        bound = parameters.bind(*args, **kwargs)
        bound.apply_defaults()
        key = (function.__name__, tuple((name, val) for name, val in bound.arguments.items() if name != "self"))
        try:
            hash(key)
        except TypeError:
            # 잘못된 비해시 인자도 원래 메서드의 사전 검증에서 처리한다.
            return await function(*args, **kwargs)
        try:
            async with asyncio.timeout(owner._browser.timeout):
                return await owner._query_cache.get(key, lambda: function(*args, **kwargs))
        except TimeoutError:
            owner._browser._raise_denial()
            raise KritsNetworkError("공개 조회 시간 제한을 초과했습니다") from None

    return wrapped


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
    return await _visit_page(browser_page, url, _CONTAINERS.get(page, "#map"))


async def _visit_page(browser_page: Page, url: str, container: str) -> str:
    """내부에서 선택한 고정 공개 경로의 응답·제목·접근 상태를 검증한다."""
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
    if not await browser_page.locator(container).count():
        raise KritsSchemaError("ITS 공개 페이지의 필수 컨테이너가 없습니다")
    return title


async def _action_json(
    page: Page, endpoint: str, action: Callable[[], Awaitable[object]],
    expected: dict[str, object],
    *, flat_request: bool = False,
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
            if not isinstance(encoded, dict):
                return
            if flat_request:
                data = encoded
            elif isinstance(encoded.get("body"), dict):
                data = encoded["body"].get("data")
            else:
                return
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
        payload = await _response_json(response, url)
        if denied_status is not None:
            _check_status(denied_status)
        return payload
    finally:
        page.remove_listener("request", track)
        page.remove_listener("response", observe_denial)


async def _response_json(response: Response, url: str) -> object:
    """관찰한 공개 JSON 응답의 HTTP·로그인·제공자 상태를 검증한다."""
    _check_status(response.status)
    if response.url != url:
        raise KritsAccessError("공개 웹 응답이 다른 경로로 이동했습니다")
    text = await response.text()
    if text.lstrip().startswith("<") and re.search(r"로그인|captcha|password|접근\s*(?:제한|거부)", text, re.I):
        raise KritsAccessError("공개 웹 응답이 로그인 또는 보안 확인 화면입니다")
    payload = decode_json(text)
    if isinstance(payload, dict) and isinstance(payload.get("header"), dict):
        if payload["header"].get("state") != "OK":
            raise KritsProviderError("공개 웹 제공자가 처리 실패를 반환했습니다")
    return payload


async def _open_file_catalog(
    page: Page, url: str, endpoint: str, validate: Callable[[object], object] = open_data_ids,
) -> None:
    """초기 목록 요청은 선택적이다. 발생한 응답은 조회 버튼을 누르기 전에 검사한다."""
    responses: list[Response] = []

    def observe(response: Response) -> None:
        if response.url == BASE_URL + endpoint:
            responses.append(response)

    page.on("response", observe)
    try:
        await _visit_page(page, url, "#moveData")
        await page.wait_for_load_state("networkidle")
        for response in responses:
            validate(await _response_json(response, BASE_URL + endpoint))
    finally:
        page.remove_listener("response", observe)


@asynccontextmanager
async def _denial_guard(page: Page, endpoint: str) -> AsyncIterator[Callable[[], None]]:
    """초기 자동 조회부터 선택 결과까지 같은 endpoint의 거부를 유지한다."""
    denied: int | None = None

    def observe(response: Response) -> None:
        nonlocal denied
        if response.url == BASE_URL + endpoint and response.status in (401, 403, 429):
            denied = denied or response.status

    def check() -> None:
        if denied is not None:
            _check_status(denied)

    page.on("response", observe)
    try:
        yield check
        check()
    except asyncio.CancelledError:
        raise
    except Exception:
        check()
        raise
    finally:
        page.remove_listener("response", observe)


@asynccontextmanager
async def _travel_widget(page: Page) -> AsyncIterator[tuple[Locator, tuple[str, ...], Callable[[], None]]]:
    """초기 자동 조회를 확인한 뒤 기점 목록과 선택 동작을 노출한다."""
    endpoint = "/map/getCityReqTimeByGroup"
    await page.goto("about:blank")
    async with _denial_guard(page, endpoint) as check:
        await _action_json(page, endpoint, lambda: _open_page(page, "traffic"), {})
        check()
        select = page.locator(".region_list .select select")
        await select.wait_for(state="attached")
        origins = parse_origins(await select.locator("option").evaluate_all("es => es.map(e => e.value)"))
        check()
        yield select, origins, check


def _date_range(start: date | None, end: date | None) -> tuple[str, str]:
    """사이트의 종료일 기준 직전 1년 경계와 같은 달력 범위를 검증한다."""
    if type(start) is not date or type(end) is not date:
        raise ValueError("start_date/end_date는 datetime이 아닌 date여야 합니다")
    try:
        earliest = end.replace(year=end.year - 1)
    except ValueError:
        if end.year == 1:
            earliest = date.min
        else:
            earliest = date(end.year - 1, 3, 1)
    if start > end or start < earliest:
        raise ValueError("시작일은 종료일 이하여야 하며 한 번에 1년 이내만 조회할 수 있습니다")
    return start.isoformat(), end.isoformat()


class KritsClient:
    """Chromium 공개 페이지 수집 기반. 자원은 첫 호출에서 생성한다.

    ``browser_context``를 주입하면 해당 context는 호출자가 닫는다.
    라이브러리가 만든 page는 라이브러리가 닫는다. 기본 수집 operation은
    5 RPS, burst=1, 자동 재시도 0이다. 허용된 페이지 자산과 redirect 전송에도 적용한다.
    """

    def __init__(
        self,
        *,
        timeout: float = 90.0,
        max_rps: float = 5.0,
        rate_limiter: AsyncTokenBucket | None = None,
        browser_context: BrowserContext | None = None,
        executable_path: str | None = None,
        cache_ttl: float = 15.0,
        cache_max_entries: int = 32,
    ) -> None:
        self._query_cache = RequestCache(cache_ttl, cache_max_entries)
        self._file_tasks: set[asyncio.Task[StoredFile]] = set()
        self._closing = False
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
        self._browser._bind_loop()
        self._closing = True
        try:
            await self._query_cache.aclose()
        finally:
            try:
                if self._file_tasks:
                    joined = asyncio.gather(*tuple(self._file_tasks), return_exceptions=True)
                    try:
                        await asyncio.shield(joined)
                    except asyncio.CancelledError:
                        await _settle(joined)
                        raise
            finally:
                await self._browser.aclose()

    async def download_file(self, attachment: FileAttachment, store: FileStore, *,
                            max_bytes: int = DEFAULT_MAX_BYTES, refresh: bool = False) -> StoredFile:
        """첨부를 재검증해 재사용한다. refresh=True면 새 전송으로 교체 여부를 확인한다."""
        self._browser._bind_loop()
        if self._closing or self._browser._closed:
            raise KritsClosedError("종료된 클라이언트입니다")
        validate_attachment(attachment, max_bytes)
        if not isinstance(store, FileStore) or type(refresh) is not bool:
            raise ValueError("FileStore와 bool refresh가 필요합니다")
        task = asyncio.create_task(download_file(self._browser, attachment, store, max_bytes=max_bytes, refresh=refresh))
        self._file_tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await _settle(task)
            raise
        finally:
            self._file_tasks.discard(task)

    def clear_cache(self) -> None:
        """완료된 조회 캐시를 비운다. 진행 중 같은 조회는 계속 공유한다."""
        self._query_cache.clear()

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

    @_cached_query
    async def list_roads(self, *, road_type: RoadType = "highway") -> DataSnapshot[Road]:
        """공개 교통 화면에 있는 도로 ID·노선번호·이름을 순서대로 조회한다."""
        _road_type(road_type)
        async with self._browser.operation() as page:
            await _open_page(page, "traffic")
            rows = await page.locator(f"#ul_{road_type} li.dep1").evaluate_all(_ROADS_SCRIPT)
            return DataSnapshot(parse_roads(rows, road_type), BASE_URL + _PATHS["traffic"],
                                datetime.now(timezone.utc), {"road_type": road_type})

    @_cached_query
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

    @_cached_query
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

    @_cached_query
    async def search_cctvs(self, keyword: str) -> DataSnapshot[Cctv]:
        """CCTV명으로 메타데이터만 검색한다. 영상 재생/다운로드 요청은 하지 않는다."""
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 100:
            raise ValueError("keyword는 1~100자의 비어 있지 않은 문자열이어야 합니다")
        keyword = keyword.strip()
        async with self._browser.operation() as page:
            await _open_page(page, "cctv")
            await page.locator("#inp_search").fill(keyword)
            payload = await _action_json(page, "/map/getCctvSearch", page.locator("#btn_search").click,
                                         {"searchKeyword": keyword}, flat_request=True)
            return DataSnapshot(parse_cctvs(payload), BASE_URL + _PATHS["cctv"],
                                datetime.now(timezone.utc), {"keyword": keyword, "content": "metadata"})

    @_cached_query
    async def list_detour_roads(self) -> DataSnapshot[DetourRoad]:
        """현재 고속도로 우회 화면의 노선번호 목록을 반환한다."""
        async with self._browser.operation() as page:
            await _open_page(page, "detour")
            rows = page.locator(".rt_box li.dep1")
            await rows.first.wait_for(state="attached")
            roads = parse_detour_roads(await rows.evaluate_all(_ROADS_SCRIPT))
            return DataSnapshot(roads, BASE_URL + _PATHS["detour"], datetime.now(timezone.utc),
                                {"road_type": "highway", "mode": "current"})

    @_cached_query
    async def get_detours(self, road_number: str) -> DataSnapshot[Detour]:
        """현재 고속도로의 양방향 본선·우회 비교를 조회한다. road_number는 노선번호다."""
        if not isinstance(road_number, str) or re.fullmatch(r"[0-9]{1,4}", road_number) is None:
            raise ValueError("road_number는 list_detour_roads의 노선번호 문자열이어야 합니다")
        async with self._browser.operation() as page:
            await _open_page(page, "detour")
            rows = page.locator(".rt_box li.dep1")
            await rows.first.wait_for(state="attached")
            roads = parse_detour_roads(await rows.evaluate_all(_ROADS_SCRIPT))
            index = next((i for i, road in enumerate(roads) if road.road_number == road_number), None)
            if index is None:
                raise ValueError("공개 우회 목록에 없는 노선번호입니다")
            payload = await _action_json(page, "/map/getMainToDetourSectionsByRoad",
                                         rows.nth(index).locator("a.title").click,
                                         {"searchType": "rt", "roadNo": int(road_number), "sctnTyCode": "EX", "keyword": ""})
            return DataSnapshot(parse_detours(payload, road_number), BASE_URL + _PATHS["detour"],
                                datetime.now(timezone.utc), {"road_type": "highway", "road_number": road_number, "mode": "current"})

    @_cached_query
    async def list_travel_origins(self) -> DataSnapshot[str]:
        """소통 지도 기점 선택 위젯의 지원 도시를 반환한다."""
        async with self._browser.operation() as page:
            async with _travel_widget(page) as (_select, origins, _check):
                return DataSnapshot(origins, BASE_URL + _PATHS["traffic"], datetime.now(timezone.utc), {"widget": "region_list"})

    @_cached_query
    async def get_travel_times(self, origin: str) -> DataSnapshot[TravelTime]:
        """소통 지도 기점 위젯을 선택해 도시간 소요시간을 분 단위로 조회한다."""
        if not isinstance(origin, str) or not origin.strip() or len(origin) > 100:
            raise ValueError("origin은 list_travel_origins의 도시 문자열이어야 합니다")
        async with self._browser.operation() as page:
            async with _travel_widget(page) as (select, origins, check):
                if origin not in origins:
                    raise ValueError("공개 기점 목록에 없는 도시입니다")

                async def choose() -> object:
                    check()
                    # 커스텀 셀렉트가 숨긴 원래 select의 값·change 이벤트다.
                    return await select.select_option(origin, force=True)

                payload = await _action_json(page, "/map/getCityReqTimeByGroup", choose, {"grpIds": origin})
                return DataSnapshot(parse_travel_times(payload, origin), BASE_URL + _PATHS["traffic"],
                                    datetime.now(timezone.utc), {"origin": origin, "widget": "region_list"})

    @_cached_query
    async def list_data_files(
        self, service: OpenDataService, *, start_date: date | None = None, end_date: date | None = None,
    ) -> DataSnapshot[FileAttachment]:
        """일반 OpenData 파일을 발견한다. 기간 ZIP과 정적 취약구간 CSV를 구분한다.

        traffic/event/vms는 date 범위를 명시하고 weakSection은 날짜를 받지 않는다.
        목록과 DOM 첨부를 대조하며 파일을 내려받지는 않는다.
        """
        if service not in ("traffic", "event", "vms", "weakSection"):
            raise ValueError("지원하는 OpenData 파일 종류가 아닙니다")
        if service == "weakSection":
            if start_date is not None or end_date is not None:
                raise ValueError("정적 취약구간 파일에는 날짜 조회가 없습니다")
            dates = None
        else:
            dates = _date_range(start_date, end_date)
        url = BASE_URL + "/opendata/opendataList?service=" + service
        async with self._browser.operation() as page:
            await page.goto("about:blank")
            if dates is None:
                await _visit_page(page, url, "#moveData")
                links = page.locator("a[href^='/file/opendata/weakSections/']")
                await links.first.wait_for(state="attached")
                rows = await links.evaluate_all("es => es.map(e => ({name:e.textContent.trim(),href:e.getAttribute('href')}))")
                return DataSnapshot(parse_weak_files(rows), url, datetime.now(timezone.utc),
                                    {"service": service, "kind": "static"})
            endpoint = "/opendata/getTestDataFileList"
            async with _denial_guard(page, endpoint) as check:
                await _open_file_catalog(page, url, endpoint)
                check()
                start, end = dates
                await page.locator("#inp_trafficDate").fill(start.replace("-", "."))
                await page.locator("#inp_trafficDate_endDate").fill(end.replace("-", "."))

                async def search() -> None:
                    check()
                    await page.locator("input[onclick='pages.getDataFile(this)']").click()

                payload = await _action_json(page, endpoint, search,
                                             {"workingDirectory": service, "searchType": -1, "startDate": start, "endDate": end})
                ids = open_data_ids(payload)
                await page.wait_for_function("""ids => {
                    const links = [...document.querySelectorAll('#data_file_list_result a')];
                    return links.length === ids.length && links.every((e,i) => e.id === ids[i]);
                }""", arg=list(ids))
                links = await page.locator("#data_file_list_result a").evaluate_all(
                    "es => es.map(e => ({id:e.id,name:e.title,href:e.getAttribute('href')}))")
                return DataSnapshot(parse_open_data(payload, service, links), url, datetime.now(timezone.utc),
                                    {"service": service, "start_date": start, "end_date": end, "kind": "date_range"})

    @_cached_query
    async def list_nodelink_releases(self, *, start_date: date, end_date: date) -> DataSnapshot[NodeLinkRelease]:
        """1년 이내 자료실 배포와 원본 ZIP·내역서의 실제 첨부를 발견한다."""
        start, end = _date_range(start_date, end_date)
        url = BASE_URL + _PATHS["nodelink"]
        endpoint = "/opendata/getNodeLinkDataFileList"
        async with self._browser.operation() as page:
            await page.goto("about:blank")
            async with _denial_guard(page, endpoint) as check:
                await _open_file_catalog(page, url, endpoint, nodelink_dom_ids)
                check()
                await page.locator("#inp_trafficDate").fill(start.replace("-", "."))
                await page.locator("#inp_trafficDate_endDate").fill(end.replace("-", "."))

                async def search() -> None:
                    check()
                    await page.locator("input[onclick='pages.getDataFile(this)'][data-code='-1']").click()

                payload = await _action_json(page, endpoint, search,
                                             {"workingDirectory": "/nodeLink", "searchType": -1, "startDate": start, "endDate": end})
                ids = nodelink_dom_ids(payload)
                await page.wait_for_function("""ids => {
                    const links = [...document.querySelectorAll('#data_file_list_result a.down')];
                    return links.length === ids.length && links.every((e,i) => e.id === ids[i]);
                }""", arg=list(ids))
                links = await page.locator("#data_file_list_result a.down").evaluate_all("""es => es.map(e => {
                    const copy = e.cloneNode(true); copy.querySelectorAll('span').forEach(s => s.remove());
                    return {id:e.id,sequence:e.title,name:copy.textContent.trim(),href:e.getAttribute('href')};
                })""")
                return DataSnapshot(parse_nodelink_releases(payload, links), url, datetime.now(timezone.utc),
                                    {"service": "nodelink", "start_date": start, "end_date": end})
