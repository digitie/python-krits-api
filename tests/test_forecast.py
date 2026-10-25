"""실제 공개 예측 응답의 결측·식별자·요청 시각·캐시·입력 경계를 검증한다."""

from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from krits import KritsClient, KritsSchemaError
from krits.client import _forecast_catalog, _forecast_selection, _forecast_query
from krits.parse import parse_forecast_links, parse_forecast_roads, parse_forecast_sections

DAY = date(2026, 10, 26)


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"forecast-{name}.json").read_text(encoding="utf8"))


def test_real_roads_sections_and_detail_preserve_missing_and_raw_speed_one():
    roads = parse_forecast_roads(fixture("roads"))
    assert len(roads) == 15 and roads[0].road_number == "1"
    sections = parse_forecast_sections(fixture("sections"), "1", "1")
    assert len(sections) == 2 and sections[0].section_id == "1" and sections[0].detour_id == "1"
    assert sections[0].main_speed_kmh is None and sections[0].main_time_seconds is None
    assert sections[0].predictable and sections[0].main_rank == 4
    links = parse_forecast_links(fixture("links"), "1", "1")
    assert [link.route for link in links] == ["MAIN", "MAIN", "DETOUR", "DETOUR"]
    assert all(link.raw_speed == 1 for link in links)
    assert links[0].link_id == "1210001901" and links[0].length_m == 253.3
    assert links[0].geometry["type"] == "LineString" and links[0].raw_info["PASNG_SPED"] == 1


def test_explicit_empty_collections_differ_from_missing_shapes():
    for name, parser, args in [("roads", parse_forecast_roads, ()), ("sections", parse_forecast_sections, ("1", "1"))]:
        data = fixture(name)
        data["body"]["data"]["SECTIONS"]["LIST"] = []
        assert parser(data, *args) == ()
        del data["body"]["data"]["SECTIONS"]["LIST"]
        with pytest.raises(KritsSchemaError):
            parser(data, *args)
    data = fixture("links")
    for collection in data.values():
        collection.update(features=[], totalFeatures=0)
    assert parse_forecast_links(data, "1", "1") == ()
    del data["MAIN"]
    with pytest.raises(KritsSchemaError):
        parse_forecast_links(data, "1", "1")


@pytest.mark.parametrize("key,value", [("ROAD_NO", 1), ("ROAD_NO", "2"), ("MLN_SCTN_ID", 1),
    ("DETU_ID", None), ("SCTN_TY_CODE", "NH"), ("DRC_CODE", "2"), ("PREDICT_AT", "unknown"),
    ("MAIN_RANK", True), ("DETOUR_RANK", -1), ("MAIN_PASNG_SPED", float("nan")),
    ("DETOUR_PASNG_SPED", "80"), ("MAIN_PASNG_TIME", -1), ("SCTN_NM", "")])
def test_forecast_section_malformed_fields_are_not_missing_predictions(key, value):
    data = fixture("sections")
    data["body"]["data"]["SECTIONS"]["LIST"][0][key] = value
    with pytest.raises(KritsSchemaError):
        parse_forecast_sections(data, "1", "1")


def test_optional_aggregate_values_and_duplicates():
    data = fixture("sections")
    row = data["body"]["data"]["SECTIONS"]["LIST"][0]
    row.update(MAIN_PASNG_SPED=0, DETOUR_PASNG_SPED=None, MAIN_PASNG_TIME=120, DETOUR_PASNG_TIME=180)
    item = parse_forecast_sections(data, "1", "1")[0]
    assert item.main_speed_kmh == 0 and item.detour_speed_kmh is None and item.main_time_seconds == 120
    data["body"]["data"]["SECTIONS"]["LIST"].append(deepcopy(row))
    with pytest.raises(KritsSchemaError):
        parse_forecast_sections(data, "1", "1")


@pytest.mark.parametrize("change", [
    lambda f: f.update(id=123), lambda f: f.update(type="wrong"),
    lambda f: f["properties"].update(type="DETOUR"), lambda f: f["properties"].update(INFO="{}"),
    lambda f: f["properties"]["INFO"].update(MLN_SCTN_ID="2"),
    lambda f: f["properties"]["INFO"].update(ROAD_NO="2"),
    lambda f: f["properties"]["INFO"].update(LINK_SEQ=0),
    lambda f: f["properties"]["INFO"].update(LENGTH=-1),
    lambda f: f["properties"]["INFO"].pop("PASNG_SPED"),
    lambda f: f["properties"]["INFO"].update(PASNG_SPED="1"),
    lambda f: f["geometry"].update(type="Point"), lambda f: f["geometry"].update(coordinates=[]),
    lambda f: f["geometry"].pop("coordinates"),
])
def test_detail_changed_schema_fails(change):
    data = fixture("links")
    change(data["MAIN"]["features"][0])
    with pytest.raises(KritsSchemaError):
        parse_forecast_links(data, "1", "1")


def test_detail_duplicate_sequence_count_null_and_repeated_link_ids():
    data = fixture("links")
    data["MAIN"]["features"][0]["properties"]["INFO"]["PASNG_SPED"] = None
    assert parse_forecast_links(data, "1", "1")[0].raw_speed is None
    second = data["MAIN"]["features"][1]
    first = data["MAIN"]["features"][0]
    second["id"] = first["id"]
    second["properties"]["INFO"]["LINK_ID"] = first["id"]
    assert len(parse_forecast_links(data, "1", "1")) == 4
    second["properties"]["INFO"]["LINK_SEQ"] = first["properties"]["INFO"]["LINK_SEQ"]
    with pytest.raises(KritsSchemaError):
        parse_forecast_links(data, "1", "1")
    data = fixture("links"); data["MAIN"]["totalFeatures"] = 99
    with pytest.raises(KritsSchemaError):
        parse_forecast_links(data, "1", "1")


@pytest.mark.parametrize("value", [None, {}, [], {"header": {"state": "ERROR"}}])
def test_roads_invalid_envelopes(value):
    with pytest.raises(KritsSchemaError):
        parse_forecast_roads(value)


@pytest.mark.parametrize("key,value", [("ROAD_NO", 1), ("ROAD_NO", "xx"), ("SCTN_TY_CODE", "NH"), ("ROAD_NM", None)])
def test_bad_forecast_road_identifiers(key, value):
    data = fixture("roads");data["body"]["data"]["SECTIONS"]["LIST"][0][key] = value
    with pytest.raises(KritsSchemaError):
        parse_forecast_roads(data)


def test_duplicate_forecast_roads():
    data = fixture("roads");rows = data["body"]["data"]["SECTIONS"]["LIST"];rows.append(deepcopy(rows[0]))
    with pytest.raises(KritsSchemaError):
        parse_forecast_roads(data)


@pytest.mark.parametrize("kwargs", [{"road_number": 1}, {"road_number": ""}, {"forecast_date": datetime(2026,10,26)},
    {"forecast_date": "2026-10-26"}, {"hour": True}, {"hour": 24}, {"hour": -1}, {"direction": 1}, {"direction": "3"}])
async def test_invalid_queries_do_not_create_browser(browser, kwargs):
    query = dict(road_number="1", forecast_date=DAY, hour=12, direction="1");query.update(kwargs)
    async with KritsClient() as client:
        with pytest.raises(ValueError):
            await client.list_forecast_sections(**query)
    browser.manager.start.assert_not_awaited()


@pytest.mark.parametrize("identifier", [1, "", "bad", "../1", "１"])
async def test_invalid_detail_identifiers_do_not_create_browser(browser, identifier):
    async with KritsClient() as client:
        with pytest.raises(ValueError):
            await client.get_forecast_links("1", identifier, "1", forecast_date=DAY, hour=12)
    browser.manager.start.assert_not_awaited()


@pytest.fixture
def forecast_browser(browser, monkeypatch):
    catalog = AsyncMock(return_value=parse_forecast_roads(fixture("roads")))
    selection = AsyncMock(return_value=parse_forecast_sections(fixture("sections"), "1", "1"))
    query = AsyncMock(return_value=fixture("links"))
    monkeypatch.setattr("krits.client._forecast_catalog", catalog)
    monkeypatch.setattr("krits.client._forecast_selection", selection)
    monkeypatch.setattr("krits.client._forecast_query", query)
    return SimpleNamespace(catalog=catalog, selection=selection, query=query)


async def test_public_queries_have_scope_and_cache(forecast_browser):
    async with KritsClient() as client:
        roads = await client.list_forecast_roads()
        sections = await client.list_forecast_sections("1", forecast_date=DAY, hour=12)
        again = await client.list_forecast_sections("1", forecast_date=DAY, hour=12, direction="1")
        links = await client.get_forecast_links("1", "1", "1", forecast_date=DAY, hour=12)
        assert roads.items and sections == again and sections is not again and len(links.items) == 4
        assert sections.scope["forecast_date"] == "2026-10-26" and sections.scope["hour"] == "12"
        assert sections.scope["clock_basis"] == "page_local_calendar" and not sections.complete
        assert links.scope["section_id"] == "1" and links.scope["detour_id"] == "1"
    assert forecast_browser.selection.await_count == 2
    forecast_browser.query.assert_awaited_once()


async def test_unknown_section_cannot_request_detail(forecast_browser):
    async with KritsClient() as client:
        with pytest.raises(ValueError):
            await client.get_forecast_links("1", "999", "1", forecast_date=DAY, hour=12)
    forecast_browser.query.assert_not_awaited()


@pytest.mark.parametrize("calendar,error", [(None,KritsSchemaError), ({},KritsSchemaError),
    ({"lower":"bad","upper":"2026-10-31","today":"2026-10-25","hour":17},KritsSchemaError),
    ({"lower":"2026-10-26","upper":"2026-10-31","today":"2026-10-25","hour":17},KritsSchemaError),
    ({"lower":"2026-10-25","upper":"2026-10-25","today":"2026-10-25","hour":17},ValueError)])
async def test_site_calendar_contract_and_range(monkeypatch, calendar, error):
    p = SimpleNamespace(evaluate=AsyncMock(return_value=calendar),get_by_role=Mock(return_value=SimpleNamespace(click=AsyncMock())))
    monkeypatch.setattr("krits.client._forecast_catalog",AsyncMock(return_value=parse_forecast_roads(fixture("roads"))))
    query = AsyncMock();monkeypatch.setattr("krits.client._forecast_query",query)
    with pytest.raises(error):
        await _forecast_selection(p,"1",DAY,12,"1")
    query.assert_not_awaited()


@pytest.mark.parametrize("hour",[0,5,12,23])
async def test_exact_hour_is_not_overwritten_by_site_ui(monkeypatch,hour):
    p = SimpleNamespace(evaluate=AsyncMock(return_value={"lower":"2026-10-25","upper":"2026-10-31","today":"2026-10-25","hour":17}),
                        get_by_role=Mock(return_value=SimpleNamespace(click=AsyncMock())))
    monkeypatch.setattr("krits.client._forecast_catalog",AsyncMock(return_value=parse_forecast_roads(fixture("roads"))))
    query = AsyncMock(return_value=fixture("sections"));monkeypatch.setattr("krits.client._forecast_query",query)
    await _forecast_selection(p,"1",DAY,hour,"1")
    assert query.call_args.args[2]["fcHour"] == f"{hour:02d}" and query.call_args.args[2]["fcDate"] == "20261026"
    with pytest.raises(ValueError):
        await _forecast_selection(p,"1",date(2026,10,25),16,"1")
    with pytest.raises(ValueError):
        await _forecast_selection(p,"9999",DAY,12,"1")


async def test_catalog_dom_cross_check_and_missing_template(browser, monkeypatch):
    p = browser.page
    dom = [{"road_number":r.road_number,"name":r.name} for r in parse_forecast_roads(fixture("roads"))]
    locator = SimpleNamespace(count=AsyncMock(return_value=1),wait_for=AsyncMock(),evaluate_all=AsyncMock(return_value=dom))
    locator.first=locator;p.locator.side_effect=None;p.locator.return_value=locator
    monkeypatch.setattr("krits.client._action_json",AsyncMock(return_value=fixture("roads")))
    assert len(await _forecast_catalog(p)) == 15
    locator.evaluate_all.return_value=dom[:1]
    with pytest.raises(KritsSchemaError):await _forecast_catalog(p)
    locator.count.return_value=0
    with pytest.raises(KritsSchemaError):await _forecast_catalog(p)


async def test_page_query_uses_site_ajax_and_exact_response_filter(monkeypatch):
    p=SimpleNamespace(evaluate=AsyncMock())
    async def action(page,endpoint,callback,expected):
        await callback();assert expected=={"fcHour":"12"};return {"ok":True}
    monkeypatch.setattr("krits.client._action_json",action)
    assert await _forecast_query(p,"/map/getMainToDetourSection",{"fcHour":"12"}) == {"ok":True}
    assert "ajaxRequest" in p.evaluate.call_args.args[0]
    assert p.evaluate.call_args.args[1] == ["/map/getMainToDetourSection",{"fcHour":"12"}]
