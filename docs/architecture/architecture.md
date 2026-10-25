# 구조와 책임 경계

## 데이터 흐름

```text
ITS 공개 웹 화면 ─ Chromium async ─ DOM/응답 ─ 순수 parser ─ typed snapshot ─ 소비자
ITS 공개 자료실 ─ Chromium 발견 ─ 첨부 다운로드 ─ 형식/크기/SHA-256 검증 ─ 원본+manifest
```

화면이 사용하는 공개 웹 요청은 browser context 안에서만 수행한다. 인증 Open API와
별도 계약이며 serviceKey/apiKey 설정을 만들지 않는다. 일반 HTTP 직접 호출로 대체하지 않는다.
외부 앱이 자체 DB·수집 스케줄·장기 통계·제공 API를 담당한다.

## 모듈과 공개 계약

| 모듈 | 책임 | 의존 방향 |
|---|---|---|
| `client.py` | `KritsClient`, 공개 조회 메서드·입력 검증 | browser, parse, models |
| `_browser.py` | Playwright async Chromium, 소유권·직렬 operation·종료 | ratelimit, exceptions |
| `_ratelimit.py` | 한 루프의 공유 `AsyncTokenBucket` | asyncio/time |
| `_cache.py` | 제한된 성공 결과 TTL/LRU·진행 조회 공유·취소 정리 | asyncio, exceptions |
| `models.py` | frozen dataclass, 출처·수집 시각·범위·원시 필드 | 표준 라이브러리 |
| `capabilities.py` | 공식12종의 부분 지원·파일·미지원 판정 | 표준 라이브러리 |
| `_references.py` | 공개 참고 XLSX의 검증된 고정 경로 | models |
| `parse.py` | JSON/DOM 레코드의 엄격 검증·타입 변환 | models, exceptions |
| 파일 목록(`client.py/parse.py`) | 기간 검색·실제 DOM 첨부 발견·자료실 관찰 차이 | browser, models |
| `files.py` | CDP response 스트림·64KiB 청크·길이/HTML/상한 검사 | browser, models, storage |
| `storage.py` | 해시 원본·불변 manifest·재검증·교체 이력 | 표준 라이브러리 |
| `_file_io.py` | MOIS 기준 thread 작업 완료 후 취소 전파 | asyncio |
| `formats.py` | bounded ZIP CRC·원문 prj/cpg·명시적 CSV/선택 XLSX | models, storage, defusedxml |
| `s3.py` (선택 extra) | 명시적 S3 signed PUT/GET·원격 해시 | storage, ratelimit, httpx |
| `exceptions.py` | 접근·제한·네트워크·스키마·무결성 오류 | 표준 라이브러리 |

클라이언트는 첫 operation에서 자원을 만들고 `async with`/`aclose()`로 닫는다.
외부 context 주입 시 소유권을 명시하고 호출자의 자원을 닫지 않는다. 종료 후 재사용은 거부한다.
같은 page에 동시에 navigation하지 않도록 operation 단위 lock을 사용한다.
timeout, 취소, 초기화 중 실패에도 소유 자원을 회수한다.
Chromium CDP Fetch의 request 단계에서 소유 page의 각 요청과 redirect hop을 검사한다.
단순 `page.route().continue_()`는 redirect 다음 전송에서 다시 호출되지 않아 이 경계로 쓰지 않는다.
CDP handler와 session은 page 종료와 함께 해제하며 주입 context의 다른 page는 건드리지 않는다.
lock·버킷 대기는 operation timeout에 포함하고, 자원을 아직 사용하지 않은 대기자의 timeout이
진행 중인 다른 operation의 page를 닫지 않도록 한다. 자원 생성 도중 취소 시 생성 결과를
받아 cleanup에 등록한 후 취소를 전파한다.

기본 전송 예산은 5 RPS, burst capacity=1, 자동 재시도 0이다. 같은 버킷을 여러 클라이언트에
주입할 수 있다. CDP request 단계에서 허용된 문서·스크립트·스타일·데이터·각 redirect 전송에
토큰을 적용한다. 차단 요청은 토큰 없이 종결한다. page 종료 전에 토큰 대기 task도 취소·회수한다.
타일·영상·분석 자산은 차단한다. 실제 서버의 허용 한도를 무시하거나 보장하는 설정은 아니다.
성공 조회에는 기본 TTL15초/32항목 LRU를 적용하고 같은 진행 요청을 공유한다. 캐시 결과는
복사해 반환하며 원래 수집 시각을 유지한다. 실패는 저장하지 않고 마지막 대기자 취소 시 실제
조회 task와 그 자원 정리를 완료한다. [자세한 정책](../load-control.md)을 따른다.

## 모델

조회 결과에는 `source_url`, UTC `collected_at`, 조회 조건, 완전성 설명을 포함한다.
식별자는 `str`, 검증된 수치는 `float`/`int`, 빈 선택 값은 `None`으로 둔다.
공식 Open API 원문 필드와 웹 화면 원문 필드를 하나의 의미로 추정 매핑하지 않는다.
원문 레코드 보존 시 세션·키는 제외한다. 파싱 실패를 행 제외로 숨기지 않는다.

자료실 모델은 자료 ID·첨부 ID·파일명·기준일·설명·발견 URL을 보존한다.
동일 날짜에 파일이 교체될 수 있으므로 ID+첨부+SHA-256으로 버전을 식별한다.
manifest의 상태는 발견/다운로드/검증 완료를 구분한다. 최신 선택은 명시적 메타데이터에
기반하며 날짜 파싱 실패를 수집일로 대신하지 않는다.

## 참조 프로젝트의 적용 범위

2026-10-24 로컬 참조 HEAD를 읽었다. 참조 checkout의 미커밋 변경은 복사하지 않는다.

| 저장소/commit | 채택 | 제외 |
|---|---|---|
| [python-kric-api](https://github.com/digitie/python-kric-api) `55361313ad59f13e8699ebcbe130c532002b9b76` | src 레이아웃, py.typed, 문서 라우팅, 작업 기록, 2인 리뷰 | 철도·해운 API/키와 도메인 모델 |
| [python-opinet-api](https://github.com/digitie/python-opinet-api) `dcfb41a1862bb9718a778fdc0fc2e3e807ed7d47` | native async, 공유 FIFO 버킷, lazy 세션, 소유권 | certkey HTTP transport, 유가/좌표 로직 |
| [python-mois-api](https://github.com/digitie/python-mois-api) `3cdee09eb753edbdaf91c28a955e2c6ddd72ec17` | 청크 다운로드, thread 파일 I/O와 취소 안전, SHA-256 | 인허가 카탈로그, 지오코더, 서비스 DB |

KRIC·Opinet의 GPL-3.0-or-later, MOIS의 MIT 출처를 보존한다. 실제 코드 복사 시
`NOTICE`에 파일별 출처를 추가한다. 객체 저장소 연동은 T008에서 명시적 설정으로 제공한다.
