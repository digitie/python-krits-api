"""공개 지도 VMS/재난 계약과 미지원 판정의 정확성을 검증한다."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from krits import KritsClient, KritsSchemaError, list_capabilities
from krits.parse import parse_disaster_zones, parse_vms
from krits.client import _vms_payload


def payload(kind):
    return json.loads((Path(__file__).parent / "fixtures" / f"{kind}.json").read_text(encoding="utf8"))


def test_vms_raw_messages_ids_and_nullable_fields():
    value = payload("vms")
    result = parse_vms(value)
    assert len(result) == 2
    assert result[0].vms_id == "0010VME00200"
    assert "@@@" in result[1].message
    assert result[1].raw_info == json.loads(value["features"][1]["properties"]["INFO"])
    info = json.loads(value["features"][0]["properties"]["INFO"])
    info.update(vmsEprssCn=None, routeNm=None)
    value["features"][0]["properties"]["INFO"] = json.dumps(info)
    assert parse_vms(value)[0].message is None
    assert parse_vms(value)[0].route_name is None


def test_disaster_zone_raw_times_and_distinct_scope():
    result = parse_disaster_zones(payload("disaster"))
    assert len(result) == 1
    assert result[0].disaster_id == "FRF0000794"
    assert result[0].zone_type == "0"
    assert result[0].occurred_at_raw == "2026-10-24 14:15"
    assert result[0].ended_at_raw is None
    assert result[0].raw_info["msfrtnZoneScope"].startswith("POLYGON")


@pytest.mark.parametrize("kind,parser", [("vms", parse_vms), ("disaster", parse_disaster_zones)])
def test_empty_missing_malformed_and_duplicate_markers(kind, parser):
    value = payload(kind)
    collection = value if kind == "vms" else value["DISASTER"]
    empty = copy.deepcopy(value)
    (empty if kind == "vms" else empty["DISASTER"]).update(features=[], totalFeatures=0)
    assert parser(empty) == ()
    for mutation in (lambda c: c.pop("features"), lambda c: c.update(totalFeatures=999),
                     lambda c: c["features"][0].update(id=1),
                     lambda c: c["features"][0].update(type="wrong"),
                     lambda c: c["features"][0]["properties"].update(type="wrong"),
                     lambda c: c["features"][0]["properties"].update(INFO=[]),
                     lambda c: c["features"][0]["properties"].update(INFO="{bad")):
        broken = copy.deepcopy(value)
        mutation(broken if kind == "vms" else broken["DISASTER"])
        with pytest.raises(KritsSchemaError):
            parser(broken)
    collection["features"].append(copy.deepcopy(collection["features"][0]))
    collection["totalFeatures"] += 1
    with pytest.raises(KritsSchemaError, match="중복"):
        parser(value)


@pytest.mark.parametrize("kind,key,parser", [("vms", "vmsEprssCn", parse_vms),
                                           ("disaster", "msfrtnEndDt", parse_disaster_zones)])
@pytest.mark.parametrize("missing", [True, False])
def test_missing_optional_column_differs_from_null_and_wrong_type(kind, key, parser, missing):
    value = payload(kind)
    row = (value if kind == "vms" else value["DISASTER"])["features"][0]
    info = json.loads(row["properties"]["INFO"])
    if missing:
        info.pop(key)
    else:
        info[key] = 123
    row["properties"]["INFO"] = json.dumps(info)
    with pytest.raises(KritsSchemaError):
        parser(value)


def test_official_twelve_services_have_explicit_partial_or_unsupported_contract():
    rows = list_capabilities()
    assert len(rows) == len({r.service for r in rows}) == 12
    assert {r.service for r in rows if r.status == "unsupported"} == {"fcTraffic", "detectorInfo", "safeDriving", "vsl", "dangerousCarInfo"}
    for row in rows:
        assert row.limitation and row.source_url.endswith("service=" + row.service)
        assert bool(row.methods) is (row.status != "unsupported")
        assert all(callable(getattr(KritsClient, m)) for m in row.methods)


@pytest.mark.parametrize("method,kind", [("get_vms", "vms"), ("get_disaster_zones", "disaster")])
async def test_new_queries_use_actions_and_shared_cache(browser, monkeypatch, method, kind):
    opened = AsyncMock()
    monkeypatch.setattr("krits.client._open_page", opened)
    locator = SimpleNamespace(click=AsyncMock())
    browser.page.locator.side_effect = None
    browser.page.locator.return_value = locator
    browser.page.wait_for_load_state = AsyncMock()

    async def action(page, endpoint, invoke, expected):
        assert endpoint == "/map/getMarkers"
        assert expected["type"] == ("VMS" if kind == "vms" else "")
        await invoke()
        return payload(kind)

    observed = AsyncMock(side_effect=action)
    monkeypatch.setattr("krits.client._action_json", observed)
    async with KritsClient() as client:
        first = await getattr(client, method)()
        second = await getattr(client, method)()
        assert first == second and first is not second
    assert first.items and not first.complete
    assert first.collected_at.tzinfo is not None
    observed.assert_awaited_once()
    opened.assert_awaited_once()
    browser.page.goto.assert_awaited_once_with("about:blank")
    if kind == "vms":
        assert locator.click.await_count == 2
        assert first.scope == {"layer": "VMS", "time": "current"}
    else:
        assert first.scope["excluded"] == "HIGHWAY,NATIONAL"


@pytest.mark.parametrize("status", [200, 403])
async def test_initial_vms_response_is_validated_without_button_retry(monkeypatch, status):
    listeners = []
    locator = SimpleNamespace(click=AsyncMock())
    page = SimpleNamespace(on=lambda event, fn: listeners.append(fn),
                           remove_listener=lambda event, fn: listeners.remove(fn),
                           wait_for_load_state=AsyncMock(), locator=lambda _: locator)

    async def open_page(*_args):
        for body in (None, {"body": None}, {"body": {"data": {"type": "other"}}}):
            listeners[0](SimpleNamespace(url="https://www.its.go.kr/map/getMarkers",
                                        request=SimpleNamespace(method="POST", post_data_json=body)))
        listeners[0](SimpleNamespace(url="https://www.its.go.kr/map/getMarkers", status=status,
                                    text=AsyncMock(return_value=json.dumps(payload("vms"))),
                                    request=SimpleNamespace(method="POST", post_data_json={"body": {"data": {"type": "VMS"}}})))

    monkeypatch.setattr("krits.client._open_page", open_page)
    if status == 200:
        assert await _vms_payload(page) == payload("vms")
    else:
        from krits import KritsAccessError
        with pytest.raises(KritsAccessError):
            await _vms_payload(page)
    locator.click.assert_not_awaited()
    assert listeners == []
