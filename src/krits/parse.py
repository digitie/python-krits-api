"""ITS 공개 웹의 도로 목록·소통 구간·돌발 응답을 엄격히 검증한다."""

from __future__ import annotations

import json
import math
import re
from typing import Any, cast
from urllib.parse import urlsplit

from .exceptions import KritsSchemaError
from .models import CatalogChanges, Cctv, DataSnapshot, Detour, DetourRoad, DisasterZone, FileAttachment, NodeLinkRelease, Road, RoadEvent, RoadType, TrafficLink, TrafficSection, TravelTime, Vms


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


def _path(value: object) -> tuple[tuple[float, float], ...]:
    """공개 웹에서 EPSG:4326으로 표시하는 개별 링크의 (경도, 위도)를 검증한다."""
    if value is None:
        return ()
    if not isinstance(value, list) or not 2 <= len(value) <= 20_000:
        raise KritsSchemaError("path: 2~20,000개 좌표가 필요합니다")
    result: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise KritsSchemaError("path: 경도·위도 쌍이 필요합니다")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in point):
            raise KritsSchemaError("path: 좌표는 숫자여야 합니다")
        try:
            longitude, latitude = float(point[0]), float(point[1])
        except OverflowError:
            raise KritsSchemaError("path: 좌표 범위 초과") from None
        if not math.isfinite(longitude) or not math.isfinite(latitude) or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise KritsSchemaError("path: EPSG:4326 좌표 범위를 벗어났습니다")
        result.append((longitude, latitude))
    return tuple(result)


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
                                     _number(link.get("LENGTH"), "LENGTH"), dict(link), _path(link.get("path"))))
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


def _marker_info(row: object, id_key: str, kind: str) -> tuple[str, dict[str, Any]]:
    """문자열 INFO와 Feature 식별자의 일치를 검증한다."""
    feature = _object(row, kind)
    properties = _object(feature.get("properties"), "properties")
    if feature.get("type") != "Feature" or properties.get("type") != kind:
        raise KritsSchemaError(f"{kind}: Feature 종류가 다릅니다")
    encoded = properties.get("INFO")
    if not isinstance(encoded, str):
        raise KritsSchemaError(f"{kind}: INFO는 JSON 문자열이어야 합니다")
    info = _object(decode_json(encoded), "INFO")
    identifier = _text(info.get(id_key), id_key)
    if feature.get("id") != identifier:
        raise KritsSchemaError(f"{kind}: Feature 식별자가 일치하지 않습니다")
    return identifier, info


def parse_vms(value: object) -> tuple[Vms, ...]:
    """지도 버튼의 VMS GeoJSON을 파싱하며 표출 구분자도 원문으로 보존한다."""
    result = []
    seen = set()
    for row in _features(value, "VMS"):
        identifier, info = _marker_info(row, "vmsId", "VMS")
        if identifier in seen:
            raise KritsSchemaError("VMS 식별자가 중복됐습니다")
        seen.add(identifier)
        for key in ("vmsEprssCn", "routeNm", "routeNo", "drcNm"):
            if key not in info:
                raise KritsSchemaError(f"VMS: {key} 필드가 없습니다")
        result.append(Vms(identifier, _optional_text(info["vmsEprssCn"], "vmsEprssCn"),
                          _optional_text(info["routeNm"], "routeNm"),
                          _optional_text(info["routeNo"], "routeNo"),
                          _optional_text(info["drcNm"], "drcNm"), dict(info)))
    return tuple(result)


def parse_disaster_zones(value: object) -> tuple[DisasterZone, ...]:
    """현재 DISASTER 구역 전체를 보존한다. 고속도로/국도의 재난성 돌발은 별도다."""
    payload = _object(value, "재난 응답")
    result = []
    seen = set()
    for row in _features(payload.get("DISASTER"), "DISASTER"):
        identifier, info = _marker_info(row, "dangerId", "DISASTER")
        if identifier in seen:
            raise KritsSchemaError("재난구역 식별자가 중복됐습니다")
        seen.add(identifier)
        for key in ("msfrtnOccrrncDt", "msfrtnEndDt"):
            if key not in info:
                raise KritsSchemaError(f"재난구역: {key} 필드가 없습니다")
        result.append(DisasterZone(
            identifier, _text(info.get("msfrtnZoneTyCode"), "msfrtnZoneTyCode"),
            _text(info.get("msfrtnZoneTyCodeNm"), "msfrtnZoneTyCodeNm"),
            _text(info.get("msfrtnZoneSj"), "msfrtnZoneSj"),
            _optional_text(info["msfrtnOccrrncDt"], "msfrtnOccrrncDt"),
            _optional_text(info["msfrtnEndDt"], "msfrtnEndDt"), dict(info),
        ))
    return tuple(result)


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise KritsSchemaError(f"{name}: 배열이 필요합니다")
    return value


def _data(value: object) -> dict[str, Any]:
    payload = _object(value, "응답")
    if _object(payload.get("header"), "header").get("state") != "OK":
        raise KritsSchemaError("정상 응답 header가 없습니다")
    return _object(_object(payload.get("body"), "body").get("data"), "data")


def parse_cctvs(value: object) -> tuple[Cctv, ...]:
    """CCTV 검색은 envelope 없는 배열이다. 빈 배열과 형식 오류를 구분한다."""
    result = []
    for row in _list(value, "CCTV"):
        item = _object(row, "CCTV 항목")
        result.append(Cctv(_text(item.get("cctvId"), "cctvId"), _text(item.get("instlLcDc"), "instlLcDc"),
                           _optional_text(item.get("routeNo"), "routeNo"),
                           _optional_text(item.get("roadNo"), "roadNo"),
                           _optional_text(item.get("linkId"), "linkId"), dict(item)))
    return tuple(result)


def parse_detour_roads(value: object) -> tuple[DetourRoad, ...]:
    """공개 고속도로 우회 목록 DOM의 문자열 식별자를 검증한다."""
    rows = _list(value, "우회 도로 DOM")
    if not rows:
        raise KritsSchemaError("우회 도로 DOM이 비어 있습니다")
    result = []
    seen = set()
    for row in rows:
        item = _object(row, "우회 도로")
        number = _text(item.get("road_number"), "road_number")
        if not number.isascii() or not number.isdigit() or number in seen:
            raise KritsSchemaError("우회 노선번호 형식이 다르거나 중복됐습니다")
        seen.add(number)
        result.append(DetourRoad(number, _text(item.get("name"), "name")))
    return tuple(result)


def parse_detours(value: object, road_number: str) -> tuple[Detour, ...]:
    """양방향 배열을 보존하고 노선·방향 계약을 교차 검증한다."""
    sections = _object(_data(value).get("SECTIONS"), "SECTIONS")
    result = []
    for key, direction in (("DOWNROAD", "1"), ("UPROAD", "2")):
        for row in _list(sections.get(key), key):
            item = _object(row, "우회 구간")
            if item.get("ROAD_NO") != road_number or item.get("SCTN_TY_CODE") != "EX" or item.get("DRC_CODE") != direction:
                raise KritsSchemaError("우회 노선번호/도로종류/방향이 조회 조건과 다릅니다")
            result.append(Detour(_text(item.get("MLN_SCTN_ID"), "MLN_SCTN_ID"),
                                 _text(item.get("DETU_ID"), "DETU_ID"), road_number,
                                 _text(item.get("SCTN_NM"), "SCTN_NM"), direction,
                                 _number(item.get("MAIN_PASNG_SPED"), "MAIN_PASNG_SPED"),
                                 _number(item.get("DETOUR_PASNG_SPED"), "DETOUR_PASNG_SPED"),
                                 _number(item.get("MAIN_PASNG_TIME"), "MAIN_PASNG_TIME"),
                                 _number(item.get("DETOUR_PASNG_TIME"), "DETOUR_PASNG_TIME"), dict(item)))
    return tuple(result)


def parse_origins(value: object) -> tuple[str, ...]:
    """기점 선택 DOM을 검증한다. 누락 DOM을 정상 빈 목록으로 보지 않는다."""
    rows = _list(value, "기점 DOM")
    origins = tuple(_text(row, "기점") for row in rows)
    if not origins or len(set(origins)) != len(origins):
        raise KritsSchemaError("기점 DOM이 비어 있거나 중복됐습니다")
    return origins


def parse_travel_times(value: object, origin: str) -> tuple[TravelTime, ...]:
    """기점 문자열로 조회한 COURSE 배열을 검증한다."""
    result = []
    for row in _list(_data(value).get("COURSE"), "COURSE"):
        item = _object(row, "도시간 항목")
        if item.get("BSPOTNM") != origin:
            raise KritsSchemaError("도시간 응답 기점이 조회 조건과 다릅니다")
        result.append(TravelTime(_text(item.get("GRPID"), "GRPID"),
                                 _text(item.get("GRPCOURSNM"), "GRPCOURSNM"), origin,
                                 _text(item.get("ESPOTNM"), "ESPOTNM"),
                                 _number(item.get("REQRETIME"), "REQRETIME"), dict(item)))
    return tuple(result)


def open_data_ids(value: object) -> tuple[str, ...]:
    """DOM 갱신 대기에도 쓰는 파일 ID를 엄격하게 검증한다."""
    ids = tuple(_text(_object(row, "파일 행").get("fileId"), "fileId")
                for row in _list(_data(value).get("fileVOList"), "fileVOList"))
    if len(set(ids)) != len(ids):
        raise KritsSchemaError("파일 ID가 중복됐습니다")
    return ids


def _file_path(value: object, pattern: str) -> str:
    path = _text(value, "첨부 href")
    # 원문 DOM href만 허용하며 외부 origin·query·조각·인코딩된 경로 이탈을 거부한다.
    if re.fullmatch(pattern, path) is None:
        raise KritsSchemaError("공개 첨부 경로가 허용 계약과 다릅니다")
    return "https://www.its.go.kr" + path


def parse_open_data(value: object, service: str, links: object) -> tuple[FileAttachment, ...]:
    """기간 응답과 실제 DOM 첨부를 ID·파일명·경로로 교차 검증한다."""
    ids = open_data_ids(value)
    rows = _list(_data(value).get("fileVOList"), "fileVOList")
    anchors = _list(links, "첨부 DOM")
    if len(anchors) != len(ids):
        raise KritsSchemaError("파일 응답과 DOM 첨부 수가 다릅니다")
    result = []
    for row, anchor in zip(rows, anchors):
        item = _object(row, "파일 행");link = _object(anchor, "첨부 DOM 행")
        name = _text(item.get("fileStreNm"), "fileStreNm")
        directory = _text(item.get("workingDirectory"), "workingDirectory")
        if item.get("dataType") != service or link.get("id") != item["fileId"] or link.get("name") != name:
            raise KritsSchemaError("파일 종류/ID/파일명이 DOM과 다릅니다")
        url = _file_path(link.get("href"), r"/opendata/fileDownload/(traffic|event|vms)/[0-9]{4}/[A-Za-z0-9_-]+\.[A-Za-z0-9]+")
        if urlsplit(url).path != f"/opendata/fileDownload/{service}/{directory}/{name}":
            raise KritsSchemaError("파일 응답과 DOM 다운로드 경로가 다릅니다")
        sequence = _count(item.get("fileSeq"), "fileSeq")
        result.append(FileAttachment(service, item["fileId"], str(sequence), name, url,
                                     _count(item.get("fileSize"), "fileSize"), dict(item)))
    return tuple(result)


def parse_weak_files(value: object) -> tuple[FileAttachment, ...]:
    """정적 취약구간 CSV의 이름 있는 링크와 중복 아이콘 링크를 병합한다."""
    rows = _list(value, "취약구간 DOM")
    if not rows:
        raise KritsSchemaError("취약구간 파일 DOM이 비어 있습니다")
    result: dict[str, FileAttachment] = {}
    all_urls = set()
    for row in rows:
        item = _object(row, "취약구간 첨부")
        url = _file_path(item.get("href"), r"/file/opendata/weakSections/[A-Za-z0-9_-]+\.csv")
        all_urls.add(url)
        name = item.get("name")
        if not isinstance(name, str):
            raise KritsSchemaError("취약구간 파일명이 문자열이 아닙니다")
        if not name.strip():
            continue
        if url in result and result[url].name != name.strip():
            raise KritsSchemaError("같은 취약구간 경로의 파일명이 서로 다릅니다")
        result[url] = FileAttachment("weakSection", None, None, name.strip(), url, None, dict(item))
    if set(result) != all_urls:
        raise KritsSchemaError("이름 없는 취약구간 첨부만 있습니다")
    return tuple(result.values())


def _node_rows(value: object) -> list[dict[str, Any]]:
    rows = [_object(row, "노드링크 배포") for row in _list(_data(value).get("fileVOList"), "fileVOList")]
    if any("updtCn" not in row for row in rows):
        raise KritsSchemaError("노드링크 배포 설명 필드가 누락됐습니다")
    for key in ("seq", "atchFileId"):
        ids = [_text(row.get(key), key) for row in rows]
        if len(ids) != len(set(ids)):
            raise KritsSchemaError(f"노드링크 {key}가 중복됐습니다")
    return rows


def _node_parts(row: dict[str, Any]) -> list[tuple[str, str, str]]:
    parts = []
    for prefix in ("node", "hist"):
        keys = (prefix + "OrginlFileNm", prefix + "FileExtsnNm", prefix + "FileSeq", prefix + "FileMg")
        if any(key not in row for key in keys):
            raise KritsSchemaError("노드링크 첨부 필드가 누락됐습니다")
        stem = _optional_text(row[keys[0]], keys[0])
        if stem is None:
            if row[keys[3]] is not None:
                _number(row[keys[3]], keys[3])
            if row[keys[1]] is not None or row[keys[2]] is not None or row[keys[3]] not in (None, 0):
                raise KritsSchemaError("없는 노드링크 첨부의 메타데이터가 남아 있습니다")
            continue
        ext = _text(row[keys[1]], keys[1]);seq = _text(row[keys[2]], keys[2])
        if re.fullmatch(r"[A-Za-z0-9]+", ext) is None or re.fullmatch(r"[0-9]+", seq) is None:
            raise KritsSchemaError("노드링크 첨부 확장자/번호 형식이 다릅니다")
        if row[keys[3]] is not None:
            _number(row[keys[3]], keys[3])
        parts.append((prefix, seq, stem + "." + ext))
    if not parts or len({seq for _prefix, seq, _name in parts}) != len(parts):
        raise KritsSchemaError("노드링크 배포에 첨부가 없거나 번호가 충돌합니다")
    return parts


def nodelink_dom_ids(value: object) -> tuple[str, ...]:
    """자료실 DOM 첨부 ID의 기대 순서를 응답의 실제 첨부 그룹에서 읽는다."""
    return tuple(("NODE_" if prefix == "node" else "HIST_") + row["atchFileId"]
                 for row in _node_rows(value) for prefix, _seq, _name in _node_parts(row))


def parse_nodelink_releases(value: object, links: object) -> tuple[NodeLinkRelease, ...]:
    """명시적 null 첨부와 누락 필드를 구분하고 실제 ID/번호/파일명/DOM 경로를 검증한다."""
    anchors = _list(links, "노드링크 첨부 DOM")
    expected_ids = nodelink_dom_ids(value)
    if len(anchors) != len(expected_ids):
        raise KritsSchemaError("노드링크 응답과 DOM 첨부 수가 다릅니다")
    offset = 0
    result = []
    for row in _node_rows(value):
        files: dict[str, FileAttachment] = {}
        group = row["atchFileId"]
        for prefix, sequence, name in _node_parts(row):
            anchor = _object(anchors[offset], "노드링크 첨부")
            if anchor.get("id") != expected_ids[offset] or anchor.get("sequence") != sequence or anchor.get("name") != name:
                raise KritsSchemaError("노드링크 응답과 DOM ID/첨부번호/파일명이 다릅니다")
            url = _file_path(anchor.get("href"), r"/opendata/nodelinkFileSDownload/[A-Za-z0-9_-]+/[0-9]+")
            if urlsplit(url).path != f"/opendata/nodelinkFileSDownload/{group}/{sequence}":
                raise KritsSchemaError("노드링크 DOM과 실제 첨부 ID/번호가 다릅니다")
            # FileMg는 표시용 반올림 MB다. 정확한 바이트 수를 만들어내지 않는다.
            files[prefix] = FileAttachment("nodelink", group, sequence, name, url, None,
                                           {**row, "role": prefix})
            offset += 1
        result.append(NodeLinkRelease(row["seq"], group, _optional_text(row["updtCn"], "updtCn"),
                                      files.get("node"), files.get("hist"), dict(row)))
    return tuple(result)


def compare_nodelink_catalogs(
    before: DataSnapshot[NodeLinkRelease], after: DataSnapshot[NodeLinkRelease],
) -> CatalogChanges:
    """같은 자료실·기간의 추가/미관찰/메타데이터 변경을 계산한다. 원본은 삭제하지 않는다."""
    if before.scope != after.scope or before.source_url != after.source_url:
        raise ValueError("같은 출처와 조회 범위의 자료실 목록만 비교할 수 있습니다")
    old = {row.release_id: row for row in before.items}
    new = {row.release_id: row for row in after.items}
    if len(old) != len(before.items) or len(new) != len(after.items):
        raise KritsSchemaError("비교 목록의 배포 ID가 중복됐습니다")

    def metadata(row: NodeLinkRelease) -> tuple[object, ...]:
        # rowSeq는 현재 목록의 순번이므로 앞에 새 배포가 추가돼도 변경으로 세지 않는다.
        files = tuple(None if file is None else (file.service, file.file_id, file.attachment_id,
                                                 file.name, file.download_url, file.size_bytes)
                      for file in (row.data_file, row.history_file))
        return (row.attachment_group_id, row.description, files,
                {key: val for key, val in row.raw.items() if key != "rowSeq"})

    return CatalogChanges(tuple(key for key in new if key not in old),
                          tuple(key for key in old if key not in new),
                          tuple(key for key in new if key in old and metadata(old[key]) != metadata(new[key])))
