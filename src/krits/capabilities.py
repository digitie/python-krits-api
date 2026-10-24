"""공식 12개 서비스와 공개 웹 구현의 대응 범위. 조회 자체는 네트워크를 쓰지 않는다."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Capability:
    """공식 API와 동등함을 뜻하지 않는 공개 웹 지원 판정."""

    service: str
    status: Literal["web_partial", "files", "unsupported"]
    methods: tuple[str, ...]
    limitation: str
    source_url: str


_ROWS: tuple[tuple[str, Literal["web_partial", "files", "unsupported"], tuple[str, ...], str], ...] = (
    ("traffic", "web_partial", ("list_roads", "get_traffic", "list_data_files"), "선택 도로·방향의 현재 화면 구간. 전국 전체 링크와 공식 API 필드의 동등성은 보장하지 않습니다."),
    ("event", "web_partial", ("get_events", "list_data_files"), "현재 고속도로·국도 돌발. DISASTER 구역은 별도 메서드입니다."),
    ("cctv", "web_partial", ("search_cctvs",), "명칭 검색 메타데이터만 지원하며 영상 재생·다운로드를 제공하지 않습니다."),
    ("fcTraffic", "unsupported", (), "공개 우회 화면은 현재 비교값입니다. 날짜·시간을 지정하는 예측 조작과 응답을 확인하지 못했습니다."),
    ("detectorInfo", "unsupported", (), "공개 지도에서 VDS 검지기·차로별 교통량·점유율의 조회 조작과 응답을 확인하지 못했습니다."),
    ("vms", "web_partial", ("get_vms", "list_data_files"), "현재 지도 표출 원문. 공식 메시지 순번·생성시각·도로 커버리지와의 동등성은 보장하지 않습니다."),
    ("safeDriving", "unsupported", (), "공개 지도에서 공식 주의운전 우선순위·단계·시종점 링크 메시지의 조회를 확인하지 못했습니다. 취약구간 파일과 다른 서비스입니다."),
    ("vsl", "unsupported", (), "공개 지도에서 가변 제한속도·기본 제한속도 표지별 조회를 확인하지 못했습니다. 소통 속도로 대체하지 않습니다."),
    ("weakSection", "files", ("list_data_files",), "상습결빙·안개취약 CSV 원문 파일. 명시적 인코딩으로 선택 파싱하며 좌표계는 추정하지 않습니다."),
    ("nodelink", "files", ("list_nodelink_releases",), "기간별 배포·첨부와 원본 보관. 형상 DB·지도 서비스·자동 갱신 스케줄은 소비자 책임입니다."),
    ("dangerousCarInfo", "unsupported", (), "공개 지도에서 위험물 차량 사고 전용 식별자·발생/종료 상태의 조회를 확인하지 못했습니다. 일반 돌발에서 추정하지 않습니다."),
    ("disaster", "web_partial", ("get_disaster_zones",), "현재 DISASTER 재난구역만 지원합니다. HIGHWAY/NATIONAL의 재난성 돌발 분류와 과거 날짜 조회는 포함하지 않습니다."),
)


def list_capabilities() -> tuple[Capability, ...]:
    """2026-10-24 공개 화면 조사 기준 지원표를 반환한다. 실시간 사이트 상태 검사가 아니다."""
    return tuple(Capability(service, status, methods, limitation,
                            f"https://www.its.go.kr/opendata/opendataList?service={service}")
                 for service, status, methods, limitation in _ROWS)
