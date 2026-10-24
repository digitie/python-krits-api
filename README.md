# python-krits-api

ITS 국가교통정보센터의 공개 웹 교통정보와 파일, 표준노드링크 자료실을
**API 키 없이 Chromium으로 수집**하는 비동기 Python 라이브러리를 개발한다.
공식 API의 인증·쿼터를 사용하는 클라이언트 대신 공개 화면에서 제공되는 유사 기능을 구현한다.
공식 서비스가 아니며 화면과 공식 Open API의 데이터 범위·필드는 다를 수 있다.

현재 단계는 [작업 목록](docs/tasks.md), 상세 범위는 [조사 사양](docs/source-analysis.md),
구조는 [구조 문서](docs/architecture/architecture.md), 개발 순서는 [구현 계획](docs/implementation-plan.md)에 있다.

## 프로젝트 구조

`python-kric-api`의 `src/`, `tests/`, `.github/workflows/`, `docs/architecture/`,
`docs/runbooks/`, 작업·재개 문서 구성을 따른다. 구현 파일은 task 순서대로 추가한다.

| 경로 | 역할 |
|---|---|
| `src/krits/` | 비동기 provider, 파서, 모델, 파일·보관 |
| `tests/fixtures/` | 세션 정보가 제거된 응답 구조 |
| `tests/` | 오프라인 회귀·opt-in Chromium live E2E |
| `docs/source-analysis.md` | 출처별 검증 사실·API 대응·미확정 항목 |
| `docs/tasks.md`, `docs/tasks-done.md` | 의존 순서와 완료 기준 |
| `docs/validation/` | 두 리뷰와 live/CI 증빙 |

네트워크 호출은 native async 전용이다. Python 3.11 이상과 Playwright Chromium을 사용한다.
설치·실행 예시는 T002에서 실제 동작과 함께 추가한다. LICENSE는 기존 GPL-3.0을 유지하며
참조 출처는 [구조 문서](docs/architecture/architecture.md)에 기록한다.
