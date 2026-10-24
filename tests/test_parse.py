"""실제 응답 구조 기반의 데이터 손실·스키마 오류·정상 빈 값 회귀."""

import json
from pathlib import Path

import pytest

from krits import KritsSchemaError, Road
from krits.parse import decode_json, parse_events, parse_roads, parse_traffic

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf8"))


@pytest.mark.parametrize("kind,road_id,name,links", [
    ("highway", "0010", "경부고속도로", 4), ("national", "0001", "국도1호선", 21),
])
def test_actual_traffic_preserves_section_and_link_order(kind, road_id, name, links):
    payload = fixture(f"traffic-{kind}.json")
    result = parse_traffic(payload, Road(road_id, "1", name, kind), payload["drct"])
    assert sum(len(x.links) for x in result) == links
    assert result[0].section_id.startswith(road_id)
    for section, raw in zip(result, payload["features"]):
        assert [x.link_id for x in section.links] == [x["LINK_ID"] for x in raw["properties"]["LINK_INFO"]]
        assert section.raw_info == raw["properties"]["INFO"]
        for link, original in zip(section.links, raw["properties"]["LINK_INFO"]):
            assert link.raw == original
            assert link.speed_kmh == original["PASNG_SPED"]
    if kind == "national":
        assert result[0].raw_info["PASNG_SPED"] > 1000
        assert result[0].links[0].speed_kmh < 100


def test_actual_events_preserve_raw_timestamps_null_messages_and_ids():
    payload = fixture("events.json")
    result = parse_events(payload)
    assert len(result) == 4
    assert [x.road_type for x in result] == ["highway", "highway", "national", "national"]
    assert result[0].raw_info["occrrncTm"] == json.loads(payload["HIGHWAY"]["features"][0]["properties"]["INFO"])["occrrncTm"]
    assert result[-1].message is None
    assert len(parse_events(payload, "national")) == 2


def test_empty_events_and_traffic_are_valid_only_with_explicit_collection_contract():
    payload = fixture("events.json")
    for group in payload.values():
        group.update(features=[], totalFeatures=0)
    assert parse_events(payload) == ()
    traffic = fixture("traffic-highway.json")
    traffic.update(features=[], totalFeatures=0)
    assert parse_traffic(traffic, Road("0010", "1", "경부", "highway"), "1") == ()


@pytest.mark.parametrize("value", [None, [], {}, {"HIGHWAY": []}])
def test_missing_event_collections_are_not_empty(value):
    with pytest.raises(KritsSchemaError):
        parse_events(value)


@pytest.mark.parametrize("change", [
    lambda p: p.update(roadId="0010"),
    lambda p: p.update(drct="2"),
    lambda p: p.update(type="wrong"),
    lambda p: p.update(features=None),
    lambda p: p.update(totalFeatures=True),
    lambda p: p.update(totalFeatures=-1),
    lambda p: p.update(totalFeatures=99),
    lambda p: p["features"][0].update(type="wrong"),
    lambda p: p["features"][0].update(id="other"),
    lambda p: p["features"][0].update(properties=[]),
    lambda p: p["features"][0]["properties"].update(INFO=[]),
    lambda p: p["features"][0]["properties"].update(LINK_INFO=[]),
    lambda p: p["features"][0]["properties"]["INFO"].update(COUNT=2),
    lambda p: p["features"][0]["properties"]["INFO"].update(LINK_ID=["other"]),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(FRWY_ID="other"),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(CNZN_ID="other"),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(LINK_ID=1210005101),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].pop("PASNG_SPED"),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(PASNG_SPED=True),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(PASNG_SPED=-1),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(PASNG_SPED=float("inf")),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(PASNG_SPED="28"),
    lambda p: p["features"][0]["properties"]["LINK_INFO"][0].update(LENGTH=10**1000),
])
def test_traffic_schema_mismatch_fails_whole_result(change):
    payload = fixture("traffic-highway.json")
    change(payload)
    with pytest.raises(KritsSchemaError):
        parse_traffic(payload, Road("0010", "1", "경부", "highway"), "1")


def test_null_speed_is_not_zero_or_dropped():
    payload = fixture("traffic-highway.json")
    payload["features"][0]["properties"]["LINK_INFO"][0]["PASNG_SPED"] = None
    assert parse_traffic(payload, Road("0010", "1", "경부", "highway"), "1")[0].links[0].speed_kmh is None


@pytest.mark.parametrize("encoded", [None, {}, "bad json", "[]", '{"x":NaN}'])
def test_bad_event_info_is_not_silently_dropped(encoded):
    payload = fixture("events.json")
    payload["HIGHWAY"]["features"][0]["properties"]["INFO"] = encoded
    with pytest.raises(KritsSchemaError):
        parse_events(payload)


@pytest.mark.parametrize("field,value", [
    ("outbrkId", 123), ("dataType", "N"), ("outbrkId", "other"),
    ("roadNm", " "), ("roadNo", 1), ("occrrncLinkId", 12),
])
def test_event_fields_preserve_identifier_types(field, value):
    payload = fixture("events.json")
    row = payload["HIGHWAY"]["features"][0]
    info = json.loads(row["properties"]["INFO"])
    info[field] = value
    row["properties"]["INFO"] = json.dumps(info)
    with pytest.raises(KritsSchemaError):
        parse_events(payload)


def test_event_feature_type_and_optional_blanks():
    payload = fixture("events.json")
    row = payload["HIGHWAY"]["features"][0]
    info = json.loads(row["properties"]["INFO"])
    info.update(roadNo=" ", roadDrcTy=None)
    row["properties"]["INFO"] = json.dumps(info)
    assert parse_events(payload)[0].road_number is None
    row["type"] = "wrong"
    with pytest.raises(KritsSchemaError):
        parse_events(payload)


def test_road_dom_keeps_leading_zero_and_distinct_route_number():
    roads = parse_roads([{"road_id": "0010", "road_number": "1", "name": " 경부고속도로 "}], "highway")
    assert roads == (Road("0010", "1", "경부고속도로", "highway"),)


@pytest.mark.parametrize("value", [None, [], {}, [{"road_id": 10}],
    [{"road_id": "1", "road_number": "1", "name": "경부"}],
    [{"road_id": "００１０", "road_number": "1", "name": "경부"}],
    [{"road_id": "0010", "road_number": "1", "name": "경부"}] * 2,
])
def test_invalid_or_changed_road_dom(value):
    with pytest.raises(KritsSchemaError):
        parse_roads(value, "highway")


@pytest.mark.parametrize("text", ["<html>점검</html>", "NaN", "Infinity", "[invalid]", "[" * 2000])
def test_invalid_json(text):
    with pytest.raises(KritsSchemaError):
        decode_json(text)



def test_traffic_path_preserves_wgs84_order_without_mutating_raw():
    payload = fixture("traffic-highway.json")
    path = [[127.01645974799, 37.5176283875577], [127.016366406254, 37.517439662834]]
    payload["features"][0]["properties"]["LINK_INFO"][0]["path"] = path
    result = parse_traffic(payload, Road("0010", "1", "경부", "highway"), "1")
    link = result[0].links[0]
    assert link.path == tuple(tuple(point) for point in path)
    assert link.raw["path"] == path
    assert result[-1].links[-1].path == ()


@pytest.mark.parametrize("path", [[], [[127, 37]], [[127, 37, 0], [127, 37]], [[True, 37], [127, 37]], [["127", 37], [127, 37]], [[float("nan"), 37], [127, 37]], [[127, 91], [127, 37]], [[181, 37], [127, 37]], [[10**400, 37], [127, 37]], [[127, 37]] * 20_001])
def test_invalid_traffic_path_is_not_silently_dropped(path):
    payload = fixture("traffic-highway.json")
    payload["features"][0]["properties"]["LINK_INFO"][0]["path"] = path
    with pytest.raises(KritsSchemaError, match="path"):
        parse_traffic(payload, Road("0010", "1", "경부", "highway"), "1")
