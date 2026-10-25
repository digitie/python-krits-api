"""공개 사양 페이지의 실제 XLSX 참고 데이터 경로. API 안내 HWP는 데이터로 분류하지 않는다."""

from .models import ReferenceService

REFERENCE_PATHS: dict[ReferenceService, tuple[str, ...]] = {
    "fcTraffic": ("/file/opendata/fcTraffic/section_id_info.xlsx",),
    "detectorInfo": ("/file/opendata/vds/vdsStatus.xlsx",),
    "vsl": ("/file/opendata/vsl/highwayVSLStatus.xlsx", "/file/opendata/vsl/nationalVSLStatus.xlsx"),
}
