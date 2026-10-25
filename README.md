# python-krits-api

ITS 국가교통정보센터의 공개 웹 교통정보와 파일, 표준노드링크 자료실을
**API 키 없이 Chromium으로 수집**하는 비동기 Python 라이브러리다.
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

Python3.11 이상에서 저장소 버전을 설치한다. PyPI에는 게시하지 않았다.

```bash
python -m pip install "git+https://github.com/digitie/python-krits-api.git@main"
python -m playwright install chromium
```

개발 checkout에서는 다음과 같이 설치한다.

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

공개 웹과 공식 API는 계약이 다르다. [12종 대응 상세](docs/remaining-services.md)와
`list_capabilities()`로 지원 범위를 확인한다.

| 기능 | 공개 메서드 | 범위 |
|---|---|---|
| 도로/소통 | `list_roads`, `get_traffic` | 도로·방향 선택, 구간/개별 링크·속도·경로 |
| 돌발 | `get_events` | 현재 고속도로·국도 |
| CCTV | `search_cctvs` | 명칭 검색 메타데이터 |
| 우회/소요시간 | `list_detour_roads`, `get_detours`, `list_travel_origins`, `get_travel_times` | 현재 비교/기점 위젯 |
| 교통예측 | `list_forecast_roads`, `list_forecast_sections`, `get_forecast_links` | 고속도로 날짜·시각·방향별 예측 대상/상세 원문 |
| VMS | `get_vms` | 현재 표출 원문 |
| 재난 | `get_disaster_zones` | 현재 DISASTER 구역 |
| 공개 파일 | `list_data_files` | 소통/돌발/VMS 기간 ZIP, 취약구간 CSV |
| 참고 데이터 | `list_reference_files` | 예측 본선 구간·VDS 시설물·고속도로/국도 VSL 현황 XLSX |
| 노드링크 | `list_nodelink_releases`, `compare_nodelink_catalogs` | 배포/첨부와 같은 범위 관찰 차이 |
| 원본 관리 | `download_file`, `FileStore` | 청크 전송·해시 버전·manifest·재사용 |
| 형식/S3 | `inspect_file`, `read_csv`, `read_xlsx`, 선택 `S3Store` | 제한 검사/읽기·원격 PUT/GET 해시 |
| 진단 | `get_page_snapshot` | 제목·출처·수집 시각 |

교통예측은 공개 웹의 부분 지원이다. VDS/VSL은 정적 현황 파일만 지원하며 실시간 검지값·가변
제한속도는 미지원이다. 주의운전 메시지·위험물 차량 사고 전용 조회도 미지원이다.

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
임의 URL은 받지 않는다. 기본 5 RPS/burst=1의 공통 버킷은 허용된 문서·스크립트·스타일·
데이터와 각 redirect 전송에 적용한다. 여러 클라이언트에 같은 버킷을 주입할 수 있다.
차단된 자원·인자 검증 실패·캐시 적중에는 토큰을 쓰지 않는다. 자동 재시도는 없다.
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

기본 조회 캐시는 TTL15초/최대32항목이다. 동일한 진행 조회는 한 번만 전송하며 실패는 저장하지 않는다.
반환 수집 시각은 원래 조회 시각을 유지한다. `cache_ttl=0`으로 완료 캐시를 끄거나
`client.clear_cache()`로 완료 값만 비울 수 있다. 진단용 `get_page_snapshot`은 항상 실제로 탐색한다.
기본 timeout은 자산 전송 대기도 포함해 90초다. 상세는 [서버부하 정책](docs/load-control.md)을 따른다.

## 개발 검증

노드링크 원문 보관의 최소 예다. 현재 목록의 첫 배포를 확인해 첨부를 선택하며,
과거 배포/부분 배포 공지와 전국 완전성은 별도로 확인해야 한다.

```python
from datetime import date, timedelta
from krits import FileLimits, FileStore, KritsClient, inspect_file

async def collect():
    end = date.today()
    store = FileStore("../krits-files")
    async with KritsClient(timeout=1200) as client:
        releases = await client.list_nodelink_releases(start_date=end-timedelta(days=300), end_date=end)
        attachment = releases.items[0].data_file
        if attachment is None:
            raise ValueError("선택한 배포에 ZIP 첨부가 없습니다")
        stored = await client.download_file(attachment, store)  # 대용량 실제 전송
        report = await inspect_file(store, stored, limits=FileLimits(
            max_member_bytes=2*1024**3, max_total_bytes=6*1024**3))
        print(stored.sha256, report.members, report.metadata)
```

원본 상한은 기본1GiB, 개별/총 해제 검사 상한은 명시적2/6GiB다. ZIP을 자동 해제하지 않는다.
CSV는 확인된 `encoding=`을 지정한다. 기존 원본 재요청은 로컬 hash를 검증해 재사용한다.
실제 교체 확인은 `refresh=True`다. 현재 포인터·manifest·검사 보고서와 원본을 함께 보존한다.

현재 VMS 표출 원문은 `await client.get_vms()`, 현재 재난구역은
`await client.get_disaster_zones()`로 조회한다. 공식 12종의 지원·미지원과 한계는
`from krits import list_capabilities` 및 [대응표](docs/remaining-services.md)를 확인한다.
교통예측과 VDS/VSL 참고 데이터의 추가 계약은 [공개 기능 확장](docs/public-expansion.md)에 있다.

```python
from datetime import date, timedelta

async def forecast_and_references(client):
    roads = await client.list_forecast_roads()
    day = date.today() + timedelta(days=1)
    sections = await client.list_forecast_sections(roads.items[0].road_number,
        forecast_date=day, hour=12, direction="1")
    for section in sections.items:
        print(section.name, section.main_speed_kmh)  # 미제공 집계값은 None
    references = await client.list_reference_files("detectorInfo")
    for attachment in references.items:
        print(attachment.name, attachment.download_url)
```

예측 날짜/시각은 페이지의 로컬 달력 기준이며 현재일~6일 뒤 범위를 확인한다.
상세 `ForecastLink.raw_speed`는 응답 원시값으로, 유효한 예측 속도라고 단정하지 않는다.
참고 XLSX는 기존 `download_file`/`FileStore`/`inspect_file`/`read_xlsx`로 보관·검사한다.
시설물 현황의 게시 기준일과 실시간 API의 갱신 시각이 같다고 설명하지 않는다.

표준노드링크는 `await client.list_nodelink_releases(start_date=date(...), end_date=date(...))`로
1년 이내 배포와 원본 ZIP·내역서 첨부를 발견한다. `compare_nodelink_catalogs(before, after)`로
같은 기간의 관찰 차이를 계산한다. 배포 범위·첨부 없음·표시 MB 처리와 원본 보존 원칙은
[자료실 사양](docs/nodelink-catalog.md)을 따른다.

`await client.download_file(attachment, FileStore("./its-files"), max_bytes=...)`는 Chromium
청크 전송과 원본 SHA-256/manifest를 제공한다. 기본 재실행은 검증된 마지막 관찰본을 재사용하고,
`refresh=True`면 새 전송으로 교체 여부를 확인한다. 이전 버전을 삭제하지 않는다.
`await store.versions(attachment)`, `await store.current(attachment)`, `await store.verify(stored)`로
보관본을 검증한다. 기본 상한1GiB, 파일명 기반 경로 금지·오류/취소 정리는
[다운로드·보관 계약](docs/download-storage.md)을 따른다.
`inspect_file`은 ZIP의 제한·CRC와 prj/cpg 원문을 검사하고, `read_csv(encoding=...)`·
`read_xlsx(sheet_name=...)`는 제한된 원문 셀을 읽는다. 별도 `[s3]` extra는 명시적 endpoint에
원본 PUT 후 GET SHA-256 검증을 제공한다. [형식·S3 계약](docs/formats-s3.md)을 확인한다.

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
Chromium이 필요하다. 전체 ZIP은 `--run-large-files --file-store <저장소 밖 경로>`의 별도 opt-in이다.
최종 통합 게이트에서는 두 플래그로 skip 없이 실행한다. 설치본 격리 실행과 정확한 범위는
[통합 runbook](docs/runbooks/integration.md)을 따른다.
[변경 기록](CHANGELOG.md)과 [완료 목록](docs/tasks-done.md)에 단계별 결과가 있다.
