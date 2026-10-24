"""출처와 수집 시각을 가진 공개 모델."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

RoadType = Literal["highway", "national"]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    """공개 페이지 접근 결과이며 교통 데이터 수집 완료를 의미하지 않는다."""

    source_url: str
    title: str
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class DataSnapshot(Generic[T]):
    """공개 웹 조회 결과. complete는 전국 데이터 완전성을 보장하지 않음을 나타낸다."""

    items: tuple[T, ...]
    source_url: str
    collected_at: datetime
    scope: dict[str, str]
    complete: Literal[False] = False
    completeness_note: str = "공개 화면의 조회 결과이며 전국 전체 도로·링크의 완전 수집은 검증하지 않았습니다."


@dataclass(frozen=True, slots=True)
class Road:
    """공개 화면의 도로 식별자와 표시 노선번호를 구분한다."""

    road_id: str
    road_number: str
    name: str
    road_type: RoadType


@dataclass(frozen=True, slots=True)
class TrafficLink:
    """화면 구간에 속하는 개별 표준 링크. raw는 경로·TIME 등 원문이다."""

    link_id: str
    direction: str
    speed_kmh: float | None
    length_m: float
    raw: dict[str, Any] = field(repr=False)
    # 공개 polylineOl.js의 LineString(link.path).transform('EPSG:4326', ...) 계약.
    # geometry가 없는 과거·축약 응답은 빈 tuple이며 선로를 추정하지 않는다.
    path: tuple[tuple[float, float], ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class TrafficSection:
    """화면 집계 구간과 순서가 보존된 개별 링크. 집계 속도 합계를 속도로 노출하지 않는다."""

    section_id: str
    name: str
    direction: str
    length_m: float
    links: tuple[TrafficLink, ...]
    raw_info: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class RoadEvent:
    """고속도로·국도 돌발. 좌표·발생시각의 원문은 raw_info에서 보존한다."""

    event_id: str
    road_type: RoadType
    road_name: str
    road_number: str | None
    direction: str | None
    event_type: str
    event_type_name: str
    link_id: str | None
    message: str | None
    raw_info: dict[str, Any] = field(repr=False)
