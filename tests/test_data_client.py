"""조회 조건 사전 검증과 동작별 응답 상관관계·listener 수명을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock

from playwright.async_api import Error as PlaywrightError

import pytest

from krits import (
    KritsAccessError, KritsClient, KritsNetworkError, KritsProviderError,
    KritsRateLimitError, KritsSchemaError,
)
from krits.client import _action_json


def load_fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf8"))


@pytest.fixture
def data_browser(browser, monkeypatch):
    page = browser.page

    async def goto(url, **kwargs):
        page.url = url
        return SimpleNamespace(status=200)

    page.goto.side_effect = goto
    road_rows = [{"road_id": "0010", "road_number": "1", "name": "경부고속도로"}]
    locator = SimpleNamespace(count=AsyncMock(return_value=1), evaluate=AsyncMock(),
                              evaluate_all=AsyncMock(return_value=road_rows), click=AsyncMock())
    locator.first = locator
    locator.locator = Mock(return_value=locator)
    page.get_by_role = Mock(return_value=locator)
    page.locator.side_effect = lambda selector: (
        SimpleNamespace(count=AsyncMock(return_value=0)) if ":visible" in selector else locator
    )
    action = AsyncMock(return_value=load_fixture("traffic-highway.json"))
    monkeypatch.setattr("krits.client._action_json", action)
    return SimpleNamespace(browser=browser, page=page, locator=locator, action=action)


async def test_public_roads_and_traffic_have_explicit_query_and_scope(data_browser):
    async with KritsClient(max_rps=10000) as client:
        roads = await client.list_roads()
        traffic = await client.get_traffic(roads.items[0].road_id)
    assert roads.items[0].road_id == "0010"
    assert traffic.scope == {"road_type": "highway", "road_id": "0010", "direction": "1"}
    assert traffic.complete is False and traffic.completeness_note
    assert traffic.collected_at.tzinfo is not None
    assert traffic.source_url.endswith("/map/traffic")
    assert len(traffic.items) == 2
    data_browser.locator.evaluate.assert_awaited_once()


async def test_national_and_explicit_direction(data_browser):
    data_browser.locator.evaluate_all.return_value = [{"road_id": "0001", "road_number": "1", "name": "국도1호선"}]
    data_browser.action.return_value = load_fixture("traffic-national.json")
    async with KritsClient() as client:
        result = await client.get_traffic("0001", road_type="national", direction="3")
    assert result.scope["direction"] == "3"
    assert len(result.items[0].links) == 21
    assert data_browser.page.get_by_role.call_args.kwargs["name"] == "국도"


async def test_event_snapshot_excludes_disaster_and_can_filter_road_type(data_browser):
    data_browser.action.return_value = load_fixture("events.json")
    async with KritsClient() as client:
        result = await client.get_events(road_type="national")
    assert len(result.items) == 2
    assert result.scope == {"road_type": "national", "excluded": "DISASTER"}
    assert all(x.road_type == "national" for x in result.items)


async def test_missing_event_refresh_is_schema_error(data_browser):
    data_browser.locator.count.return_value = 0
    # 공통 정상 컨테이너는 유지하고 새로고침 버튼만 누락시킨다.
    data_browser.page.locator.side_effect = lambda selector: (
        data_browser.locator if "refreshOutbreak" in selector else
        SimpleNamespace(count=AsyncMock(return_value=0 if ":visible" in selector else 1))
    )
    async with KritsClient() as client:
        with pytest.raises(KritsSchemaError, match="새로고침"):
            await client.get_events()
    data_browser.action.assert_not_awaited()


async def test_unknown_road_does_not_request_traffic(data_browser):
    async with KritsClient() as client:
        with pytest.raises(ValueError, match="없는 road_id"):
            await client.get_traffic("9999")
    data_browser.action.assert_not_awaited()


@pytest.mark.parametrize("method,args,kwargs", [
    ("get_traffic", (10,), {}), ("get_traffic", ("10",), {}),
    ("get_traffic", ("００１０",), {}), ("get_traffic", ("0010",), {"direction": 1}),
    ("get_traffic", ("0010",), {"direction": "3"}),
    ("get_traffic", ("0010",), {"road_type": "unknown"}),
    ("list_roads", (), {"road_type": "unknown"}), ("get_events", (), {"road_type": "unknown"}),
])
async def test_bad_query_does_not_start_browser(browser, method, args, kwargs):
    async with KritsClient() as client:
        with pytest.raises(ValueError):
            await getattr(client, method)(*args, **kwargs)
    browser.manager.start.assert_not_awaited()


class ActionPage:
    """request/response 이벤트의 순서와 상관관계를 모의한다."""

    def __init__(self, *, status=200, text='{"type":"FeatureCollection"}', url=None):
        self.url = "https://www.its.go.kr/map/getLinks"
        self.request = Mock(url=self.url, method="POST", post_data_json={"body": {"data": {"roadId": "0010"}}})
        self.response = SimpleNamespace(request=self.request, status=status, url=url or self.url,
                                        text=AsyncMock(return_value=text))
        self.handlers = []

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        self.handlers.remove(handler)

    @asynccontextmanager
    async def expect_response(self, predicate):
        self.predicate = predicate
        pending = asyncio.get_running_loop().create_future()
        pending.set_result(self.response)
        yield SimpleNamespace(value=pending)

    async def click(self):
        # 이번 동작 전에 시작한 동일 URL 응답은 선택되지 않는다.
        stale = SimpleNamespace(request=Mock())
        assert not self.predicate(stale)
        invalid = [
            Mock(url="https://other.invalid/", method="POST"),
            Mock(url=self.url, method="GET"),
            Mock(url=self.url, method="POST", post_data_json=None),
            Mock(url=self.url, method="POST", post_data_json={"body": None}),
            Mock(url=self.url, method="POST", post_data_json={"body": {"data": []}}),
            Mock(url=self.url, method="POST", post_data_json={"body": {"data": {"roadId": "other"}}}),
        ]
        malformed = Mock(url=self.url, method="POST")
        type(malformed).post_data_json = PropertyMock(side_effect=PlaywrightError("잘못된 POST JSON"))
        invalid.append(malformed)
        for request in invalid:
            self.handlers[0](request)
            assert not self.predicate(SimpleNamespace(request=request))
        self.handlers[0](self.request)
        assert self.predicate(self.response)


async def test_action_matches_new_request_and_removes_listener():
    page = ActionPage()
    result = await _action_json(page, "/map/getLinks", page.click, {"roadId": "0010"})
    assert result == {"type": "FeatureCollection"}
    assert page.handlers == []


@pytest.mark.parametrize("status,text,url,error", [
    (401, "", None, KritsAccessError), (403, "", None, KritsAccessError),
    (429, "", None, KritsRateLimitError), (503, "", None, KritsNetworkError),
    (302, "", None, KritsAccessError),
    (200, "{}", "https://www.its.go.kr/user/login", KritsAccessError),
    (200, '<html><input type="password"></html>', None, KritsAccessError),
    (200, "<html>점검 중</html>", None, KritsSchemaError),
    (200, '{"header":{"state":"ERROR"}}', None, KritsProviderError),
])
async def test_action_errors_are_not_empty_success(status, text, url, error):
    page = ActionPage(status=status, text=text, url=url)
    with pytest.raises(error):
        await _action_json(page, "/map/getLinks", page.click, {"roadId": "0010"})
    assert page.handlers == []


async def test_action_cancel_removes_observer():
    page = ActionPage()
    started = asyncio.Event()

    async def cancel_me():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(_action_json(page, "/map/getLinks", cancel_me, {}))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert page.handlers == []
