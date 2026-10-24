"""출처와 수집 시각을 가진 공개 모델."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

RoadType = Literal["highway", "national"]
OpenDataService = Literal["traffic", "event", "vms", "weakSection"]
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


@dataclass(frozen=True, slots=True)
class Vms:
    """공개 지도 VMS의 표출 원문. 메시지 순번·생성시각은 추정하지 않는다."""

    vms_id: str
    message: str | None
    route_name: str | None
    route_number: str | None
    direction_name: str | None
    raw_info: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DisasterZone:
    """DISASTER 분기의 현재 재난구역. 공식 API의 과거 도로 돌발과 다른 계약이다."""

    disaster_id: str
    zone_type: str
    zone_type_name: str
    title: str
    occurred_at_raw: str | None
    ended_at_raw: str | None
    raw_info: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Cctv:
    """검색 화면의 CCTV 메타데이터. 영상 URL/좌표계의 의미는 추정하지 않는다."""

    cctv_id: str
    name: str
    route_id: str | None
    road_number: str | None
    link_id: str | None
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DetourRoad:
    """우회 화면의 노선번호. 소통 화면의 4자리 도로 ID와 구분한다."""

    road_number: str
    name: str


@dataclass(frozen=True, slots=True)
class Detour:
    """현재 고속도로 본선·우회 비교. 시간은 초, 속도는 km/h다."""

    section_id: str
    detour_id: str
    road_number: str
    name: str
    direction: str
    main_speed_kmh: float
    detour_speed_kmh: float
    main_time_seconds: float
    detour_time_seconds: float
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TravelTime:
    """공개 기점 선택 위젯의 도시간 소요시간. 분 단위이며 경로 ID를 보존한다."""

    group_id: str
    route_name: str
    origin: str
    destination: str
    minutes: float
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class FileAttachment:
    """공개 첨부 발견 결과. DOM에 없는 식별자/바이트 수는 None이며 다운로드 완료가 아니다."""

    service: str
    file_id: str | None
    attachment_id: str | None
    name: str
    download_url: str
    size_bytes: int | None
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class NodeLinkRelease:
    """자료실 게시 배포. 배포 ID와 실제 첨부 그룹 ID를 분리한다."""

    release_id: str
    attachment_group_id: str
    description: str | None
    data_file: FileAttachment | None
    history_file: FileAttachment | None
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CatalogChanges:
    """같은 조회 범위의 관찰 차이. missing은 삭제나 폐기를 뜻하지 않는다."""

    added_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    changed_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredFile:
    """원본 전송 크기·해시 검증 완료본. 내부 형식 검사는 별도이며 원문을 보존한다."""

    attachment: FileAttachment
    path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    collected_at: datetime
    content_type: str


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """안전성/CRC 검사를 마친 ZIP 항목. 이름은 파일시스템 경로로 사용하지 않는다."""

    name: str
    size_bytes: int
    compressed_bytes: int
    crc32: int


@dataclass(frozen=True, slots=True)
class ArchiveMetadata:
    """prj/cpg 원문. CRS·인코딩을 추정하거나 변환하지 않는다."""

    name: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class FileInspection:
    """별도 불변 형식 검사 보고서. 원본 다운로드 manifest를 바꾸지 않는다."""

    sha256: str
    kind: Literal["zip", "xlsx", "csv"]
    inspected_at: datetime
    crc_checked: bool
    members: tuple[ArchiveMember, ...] = ()
    metadata: tuple[ArchiveMetadata, ...] = ()
    encoding: str | None = None
    selected_member: str | None = None
    table_rows: int | None = None
    report_path: Path | None = None
    limits: tuple[tuple[str, int | float], ...] = ()


@dataclass(frozen=True, slots=True)
class CellFormula:
    """XLSX 저장 수식 원문. 계산하거나 실행하지 않는다."""

    row_number: int
    column_number: int
    text: str


@dataclass(frozen=True, slots=True)
class TableData:
    """범위 제한을 통과한 원문 셀 값. 숫자/날짜/ID를 추정 변환하지 않는다."""

    rows: tuple[tuple[str | None, ...], ...]
    row_numbers: tuple[int, ...]
    encoding: str | None
    source_member: str | None
    sheet_name: str | None = None
    formulas: tuple[CellFormula, ...] = ()
