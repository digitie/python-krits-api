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
LICENSE는 기존 GPL-3.0을 유지하며 참조 출처는 [구조 문서](docs/architecture/architecture.md)와
`NOTICE`에 기록한다.

## 설치와 현재 제공 기능

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

T003에서 도로 목록·방향별 소통·현재 돌발 조회를 추가했다. `get_page_snapshot()`은
공개 페이지의 제목·출처·UTC 수집 시각을 확인한다. 파일 다운로드는 후속 task에서 추가한다.

```python
import asyncio
from krits import AsyncTokenBucket, KritsClient

async def main():
    budget = AsyncTokenBucket(1, capacity=1)
    async with KritsClient(rate_limiter=budget) as client:
        roads = await client.list_roads(road_type="highway")
        traffic = await client.get_traffic(roads.items[0].road_id, direction="1")
        for section in traffic.items:
            for link in section.links:
                print(section.name, link.link_id, link.speed_kmh)
        events = await client.get_events()
        print(events.source_url, events.collected_at, len(events.items))

asyncio.run(main())
```

`get_traffic`의 `road_id`는 `list_roads`의 4자리 문자열이다. 표시 노선번호 `1`과 도로 ID
`0010`은 다르다. `road_type`은 `highway`/`national`, 방향은 고속도로 `1`/`2`,
국도 `3`/`4`이며 기본값은 각각 `1`/`3`이다. 실제 웹의 방향 코드를 보존한다.
구간 ID와 개별 표준 링크 ID도 구분하며 링크 순서를 바꾸거나 중복 제거하지 않는다.
개별 링크의 `speed_kmh`와 `length_m`를 제공하고, 집계 INFO의 속도 합계를 속도로 사용하지 않는다.
단위가 확정되지 않은 `TIME`, 돌발 발생시각·좌표는 `raw`/`raw_info`로 보존한다.
소통 속도의 명시적 null은 `None`으로 보존한다. 0은 제공자 원시 수치이며 정차/정보 없음의
해석을 임의로 부여하지 않는다. 응답 JSON 수치를 문자열로 바꿔 보내는 스키마 변경은 오류다.

조회 결과는 `DataSnapshot.items`, `source_url`, `collected_at`, `scope`,
`complete=False`, `completeness_note`를 가진다. 전국 모든 도로의 완전 수집을 뜻하지 않는다.
`get_events(road_type="national")`처럼 도로 종류를 선택할 수 있으며 `DISASTER` 재난 분기는
별도 계약이라 포함하지 않는다. 국도 돌발의 메시지는 실제 null일 수 있다.
필수 필드·행 수·도로/방향 불일치와 잘못된 JSON은 `KritsSchemaError`, 제공자 처리 실패는
`KritsProviderError`다. 정상 빈 FeatureCollection만 빈 `items`로 반환한다.

페이지 이름은 `opendata`, `traffic`, `outbreak`, `cctv`, `detour`, `travel_time`, `nodelink`다.
임의 URL은 받지 않는다. 기본 1 RPS/burst=1은 명시적 수집 operation의 예산이며
페이지가 로드하는 개별 자산의 전송 수 제한은 아니다. 자동 재시도는 없다.
Chromium CDP에서 소유 page의 HTTP(S) 요청을 redirect의 각 전송 전에 검사해
외부 지도·미디어·이미지 전송을 차단한다. 인증 Open API를 호출하지 않는다.

브라우저는 첫 호출에서 만들고 `async with` 또는 `await client.aclose()`로 닫는다.
`browser_context=`를 주입하면 라이브러리는 자신이 만든 page만 닫고 context는 호출자가 닫는다.
주입 context도 `service_workers="block"`으로 생성하는 것을 권장한다.
소유 page에서는 기존 service worker를 우회한다. 다른 page·팝업·WebSocket 수집은 제공하지 않는다.
클라이언트·공유 버킷은 같은 이벤트 루프에서 사용한다. `timeout`은 lock·버킷 대기를 포함한 operation의 상한(초)이며
취소·실패 후 자원 정리 시간은 별도다. 종료 후 추가 호출은 `KritsClosedError`다.
접근 거부·다른 URL 이동, 호출 제한, 네트워크, 화면 구조 오류는 각각
`KritsAccessError`, `KritsRateLimitError`, `KritsNetworkError`, `KritsSchemaError`로 구분한다.

기존 Chromium을 사용하려면 `KritsClient(executable_path="...")`를 지정한다.
기본 동작은 Playwright가 설치한 Chromium이며 환경변수를 자동 탐색하지 않는다.
live 테스트/조사 도구만 `KRITS_CHROMIUM_EXECUTABLE`을 선택적으로 읽는다.

## 개발 검증

공개 일반 파일 목록은 `await client.list_data_files("event", start_date=date(...), end_date=date(...))`로
조회한다(`traffic/event/vms`, 1년 이내). 정적 취약구간 CSV는
`await client.list_data_files("weakSection")`로 발견한다. 날짜 인자는 `datetime.date`다.
목록·DOM 대조와 다운로드 권한의 검증 범위는 [파일 발견 사양](docs/files-catalog.md)을 따른다.

CCTV 메타데이터는 `await client.search_cctvs("서울")`, 현재 고속도로 우회는
`await client.list_detour_roads()`에서 얻은 `road_number`로 `await client.get_detours("1")`,
도시간은 `await client.list_travel_origins()`의 도시로 `await client.get_travel_times("대전")`을
사용한다. 영상은 내려받지 않는다. 우회 시간은 초, 도시간 시간은 분이다.
지원 범위와 공개 화면의 제한은 [상세 계약](docs/cctv-detour-travel.md)에 기록했다.

```bash
python tools/check_docs.py
python -m compileall src/krits tests
python -m mypy src/krits
python -m pytest -m "not live" --cov=krits --cov-fail-under=90
python -m pytest -m live --run-live -s
python -m build
```

기본 테스트는 네트워크나 설치된 브라우저를 요구하지 않는다. live에는 실제 ITS 네트워크와
Chromium이 필요하다. 전체 파일 다운로드 검증은 아직 제공하지 않는다.
