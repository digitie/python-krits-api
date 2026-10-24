"""조회 실패와 정상 빈 결과를 구분하는 공개 예외."""


class KritsError(Exception):
    """라이브러리 오류의 공통 기반."""


class KritsClosedError(KritsError):
    """종료된 클라이언트의 재사용."""


class KritsAccessError(KritsError):
    """로그인 이동 또는 공개 접근 거부."""


class KritsRateLimitError(KritsError):
    """공급자의 호출 제한 응답."""


class KritsNetworkError(KritsError):
    """브라우저 시작·통신·시간 제한·자원 정리 실패."""


class KritsSchemaError(KritsError):
    """공개 화면이나 응답 구조가 기대한 계약과 다름."""


class KritsProviderError(KritsError):
    """공개 웹 응답이 명시적으로 제공자 처리 실패를 보고함."""


class KritsIntegrityError(KritsError):
    """다운로드·보관본·manifest의 크기 또는 무결성 검증 실패."""
