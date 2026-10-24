"""ITS 공개 웹의 도로 목록·소통 구간·돌발 응답을 엄격히 검증한다."""

from __future__ import annotations

import json
import math
from typing import Any, cast

from .exceptions import KritsSchemaError
from .models import Road, RoadEvent, RoadType, TrafficLink, TrafficSection


def decode_json(text: str) -> object:
    """잘못된 JSON과 비표준 NaN/Infinity를 스키마 오류로 처리한다."""
    def reject_constant(_value: str) -> None:
        raise ValueError

    try:
        return json.loads(text, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        raise KritsSchemaError("응답 JSON 형식이 잘못됐습니다") from None


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KritsSchemaError(f"{name}: 객체가 필요합니다")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KritsSchemaError(f"{name}: 비어 있지 않은 문자열이 필요합니다")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    return _text(value, name)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KritsSchemaError(f"{name}: 숫자가 필요합니다")
    try:
        result = float(value)
    except OverflowError:
        raise KritsSchemaError(f"{name}: 숫자 범위 초과") from None
    if not math.isfinite(result) or result < 0:
        raise KritsSchemaError(f"{name}: 유한한 0 이상 숫자가 필요합니다")
    return result


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KritsSchemaError(f"{name}: 0 이상 정수가 필요합니다")
    return value


def _features(value: object, name: str) -> list[Any]:
    collection = _object(value, name)
    rows = collection.get("features")
    if collection.get("type") != "FeatureCollection" or not isinstance(rows, list):
        raise KritsSchemaError(f"{name}: FeatureCollection/features 구조가 다릅니다")
    if _count(collection.get("totalFeatures"), "totalFeatures") != len(rows):
        raise KritsSchemaError(f"{name}: totalFeatures와 실제 행 수가 다릅니다")
    return rows


def parse_roads(value: object, road_type: RoadType) -> tuple[Road, ...]:
    """검증한 DOM 목록을 도로 모델로 변환한다. 빈 DOM을 정상 빈 도로 목록으로 보지 않는다."""
    if not isinstance(value, list) or not value:
        raise KritsSchemaError("도로 목록 DOM이 없거나 비어 있습니다")
    result = []
    seen: set[str] = set()
    for row in value:
        item = _object(row, "도로")
        road_id = _text(item.get("road_id"), "road_id")
        if len(road_id) != 4 or not road_id.isascii() or not road_id.isdigit() or road_id in seen:
            raise KritsSchemaError("도로 ID 형식이 잘못됐거나 중복됐습니다")
        seen.add(road_id)
        result.append(Road(road_id, _text(item.get("road_number"), "road_number"),
                           _text(item.get("name"), "name").strip(), road_type))
    return tuple(result)


def parse_traffic(value: object, road: Road, direction: str) -> tuple[TrafficSection, ...]:
    """집계 구간과 개별 LINK_INFO를 분리하고 응답 조건·행 수를 검증한다."""
    payload = _object(value, "소통")
    if payload.get("roadId") != road.road_number or payload.get("drct") != direction:
        raise KritsSchemaError("소통 응답의 도로 번호/방향이 조회 조건과 다릅니다")
    result = []
    highway = road.road_type == "highway"
    road_key, section_key, name_key = (
        ("FRWY_ID", "CNZN_ID", "SCTN_NM") if highway
        else ("NLRD_ID", "NLRD_GROUP_ID", "G_SCTN_NM")
    )
    for row in _features(payload, "소통"):
        feature = _object(row, "구간")
        if feature.get("type") != "Feature":
            raise KritsSchemaError("소통 구간의 Feature 형식이 다릅니다")
        properties = _object(feature.get("properties"), "properties")
        info = _object(properties.get("INFO"), "INFO")
        section_id = _text(info.get(section_key), section_key)
        if feature.get("id") != section_id or info.get(road_key) != road.road_id or info.get("DRC_CODE") != direction:
            raise KritsSchemaError("구간 ID/도로 ID/방향이 일치하지 않습니다")
        leaves = properties.get("LINK_INFO")
        if not isinstance(leaves, list) or not leaves or _count(info.get("COUNT"), "COUNT") != len(leaves):
            raise KritsSchemaError("LINK_INFO가 없거나 COUNT와 일치하지 않습니다")
        links = []
        for item in leaves:
            link = _object(item, "LINK_INFO")
            if link.get(road_key) != road.road_id or link.get("DRC_CODE") != direction or link.get(section_key) != section_id:
                raise KritsSchemaError("개별 링크의 도로/방향/구간이 일치하지 않습니다")
            if "PASNG_SPED" not in link:
                raise KritsSchemaError("개별 링크 속도 필드가 없습니다")
            speed = None if link["PASNG_SPED"] is None else _number(link["PASNG_SPED"], "PASNG_SPED")
            links.append(TrafficLink(_text(link.get("LINK_ID"), "LINK_ID"), direction, speed,
                                     _number(link.get("LENGTH"), "LENGTH"), dict(link)))
        if highway and info.get("LINK_ID") != [link.link_id for link in links]:
            raise KritsSchemaError("집계 LINK_ID 순서와 개별 링크가 일치하지 않습니다")
        result.append(TrafficSection(section_id, _text(info.get(name_key), name_key), direction,
                                     _number(info.get("LENGTH"), "LENGTH"), tuple(links), dict(info)))
    return tuple(result)


def parse_events(value: object, road_type: RoadType | None = None) -> tuple[RoadEvent, ...]:
    """선택한 고속도로/국도 돌발만 파싱한다. 재난 분기는 별도 계약이므로 포함하지 않는다."""
    payload = _object(value, "돌발")
    result = []
    for group, kind in (("HIGHWAY", "highway"), ("NATIONAL", "national")):
        if road_type is not None and kind != road_type:
            continue
        for row in _features(payload.get(group), group):
            feature = _object(row, "돌발 Feature")
            if feature.get("type") != "Feature":
                raise KritsSchemaError("돌발 Feature 형식이 다릅니다")
            properties = _object(feature.get("properties"), "돌발 properties")
            encoded = properties.get("INFO")
            if not isinstance(encoded, str):
                raise KritsSchemaError("돌발 INFO는 JSON 문자열이어야 합니다")
            info = _object(decode_json(encoded), "돌발 INFO")
            event_id = _text(info.get("outbrkId"), "outbrkId")
            if feature.get("id") != event_id or info.get("dataType") != ("H" if kind == "highway" else "N"):
                raise KritsSchemaError("돌발 Feature ID 또는 도로 종류가 일치하지 않습니다")
            result.append(RoadEvent(
                event_id, cast(RoadType, kind), _text(info.get("roadNm"), "roadNm"),
                _optional_text(info.get("roadNo"), "roadNo"),
                _optional_text(info.get("roadDrcTy"), "roadDrcTy"),
                _text(info.get("outbrkTy"), "outbrkTy"), _text(info.get("outbrkTyNm"), "outbrkTyNm"),
                _optional_text(info.get("occrrncLinkId"), "occrrncLinkId"),
                _optional_text(info.get("mssageCn"), "mssageCn"), dict(info),
            ))
    return tuple(result)
