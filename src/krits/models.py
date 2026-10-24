"""출처와 수집 시각을 가진 공개 모델."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PageSnapshot:
    """공개 페이지 접근 결과이며 교통 데이터 수집 완료를 의미하지 않는다."""

    source_url: str
    title: str
    collected_at: datetime
