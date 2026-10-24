# T003 공개 소통·돌발 조회 계약

2026-10-24 Chromium 149에서 공개 화면을 조작해 확인했다. 공식 Open API는 호출하지 않는다.
안정 진입점은 `KritsClient.list_roads`, `get_traffic`, `get_events`다.

## 도로 목록과 방향

`/map/traffic`의 `#ul_highway li.dep1`, `#ul_national li.dep1`에서 도로 ID,
표시 노선번호, 이름을 읽는다. 조사 시 고속도로 73개·국도 51개였으며 수를 상수로 고정하지 않는다.
`data-roadid=0010`과 노선번호 `1`은 별개 문자열이다. 고속도로 방향은 `1/2`, 국도는 `3/4`다.
방향의 공식 Open API `up/down/start/end`와 임의 매핑하지 않는다.

선택한 탭·도로의 화면 내부 jQuery `drct` 값을 지정한 뒤 원래 구간 펼치기 버튼을 누른다.
이는 반대방향 버튼과 같은 상태를 사용하며 두 방향 데이터를 수집하기 위해 불필요한 기본방향
요청을 먼저 보내지 않는다. 형식이 잘못된 ID/방향/도로 종류는 브라우저를 만들기 전에 거부한다.
목록에 없는 형식상 유효 ID는 페이지 조회 후 `ValueError`다.

## 소통 웹 응답

`/map/getLinks`의 관찰한 요청은 `body.data` 아래 `roadId`(4자리 문자열), `drct`(숫자),
`type`(`0` 고속도로/`1` 국도), `roadNo`, `event`, `cctv`, `cctvPannel`을 가진다.
라이브러리는 화면의 요청을 관찰하며 직접 HTTP POST를 만들지 않는다.
이번 동작에서 시작한 URL·method·도로·방향·종류가 맞는 요청의 응답만 사용한다.
이전 navigation에서 남은 응답을 이번 조회의 응답으로 사용하지 않는다.

응답 `FeatureCollection`의 `roadId`는 관찰상 표시 노선번호(`1`)였고 `drct`는 문자열이었다.
`features` 길이와 정수 `totalFeatures`, 도로 번호와 방향이 모두 일치해야 한다.
구간별 properties의 `INFO`(객체)와 `LINK_INFO`(배열)를 구분한다.

| 항목 | 고속도로 | 국도 |
|---|---|---|
| 도로 ID | `FRWY_ID` | `NLRD_ID` |
| 집계 구간 ID | `CNZN_ID` | `NLRD_GROUP_ID` |
| 구간명 | `SCTN_NM` | `G_SCTN_NM` |
| 링크 ID | 개별 `LINK_INFO[].LINK_ID` | 개별 `LINK_INFO[].LINK_ID` |

`INFO.COUNT`는 개별 링크 수와 같아야 한다. 고속도로의 집계 `LINK_ID` 배열은 개별 링크와
같은 순서여야 한다. 국도 집계 `LINK_ID`는 첫 링크만 나타내므로 전체 링크로 오인하지 않는다.
모든 구간·링크의 도로 ID·방향·구간 ID가 조회 조건과 맞아야 한다. 이름이 같은 구간과
반복 링크를 제거하지 않고 원본 순서대로 반환한다.

개별 `PASNG_SPED`를 km/h 수치로 노출한다. 사이트의 속도 표시/범례와 개별 링크 사용 코드를
대조했다. 집계 `PASNG_SPED`는 합계일 수 있어 평균 속도로 노출하지 않는다.
`LENGTH`는 화면의 합계 `/1000` km 표시와 대조한 미터 수치다.
`TIME`은 화면의 여러 계산과 직접 표시가 일관되지 않아 단위를 추정하지 않고 raw로만 보존한다.
null 속도는 `None`, 숫자 0은 원문 0이다. 음수·비유한 수·bool·문자열 숫자는 스키마 오류다.
구간의 원시 집계값은 `raw_info`, 개별 링크의 추가 원문은 `raw`에 있다. 개별 `path`는 (경도,위도) tuple로도 제공한다.
공개 `polylineOl.js`가 `new ol.geom.LineString(link.path).transform('EPSG:4326', ...)`로
표시하는 실제 코드를 Chromium에서 대조했다. 경로는 추정·간소화·다른 provider 링크와 결합하지 않는다.
미제공 경로는 빈 tuple이며 잘못된 타입·좌표·점 수는 전체 응답을 스키마 오류로 거절한다.
좌표계 근거: [공식 지도 선형 표시 코드](https://www.its.go.kr/js/map/polylineOl.js).
응답의 렌더링용 집계 geometry, EVENT/CCTVP 분기는 이 소통 모델에 포함하지 않는다.

## 돌발 웹 응답

이전 문서를 `about:blank`로 비워 timer와 요청을 분리한 뒤, `/map/outbreak` navigation 전부터
최초 `/map/getMarkers` 요청을 관찰한다. `type=""`, `keyword=""`, id/drct 누락인 필터 없는
초기 로드 응답을 사용하며 별도 새로고침을 보내지 않는다. 초기 401/403/429를 다른 응답의
성공으로 덮지 않도록 같은 endpoint의 관찰된 접근 거부·제한도 검사한다.
고속도로 `HIGHWAY`, 국도 `NATIONAL`의 각각 `FeatureCollection`과 행 수를 검증한다.
`DISASTER`는 별도 재난 계약이므로 이번 모델에서 제외하고 scope에 명시한다.

properties.INFO는 소통과 달리 JSON 문자열이다. `outbrkId`는 Feature ID와 일치하고,
`dataType=H/N`은 해당 분기와 맞아야 한다. 이벤트/도로/링크 코드는 문자열을 보존한다.
`outbrkTy`, `outbrkTyNm`, 도로명은 필수다. 국도 `mssageCn=null`은 정상이며 빈 문자열도
선택 값 `None`으로 취급한다. 발생·등록·종료 시각과 좌표는 `raw_info`에 원문으로 남기고
밀리초·timezone·CRS 변환을 추정하지 않는다.

## 범위·오류·검증

모든 결과는 `DataSnapshot`에 출처 URL, UTC 수집 시각, query scope, `complete=False`,
전국 데이터 완전성 한계를 포함한다. 해당 웹 조회의 행 수 일치와 전국 데이터 완전성은 다르다.
성공 형식과 행 수가 명시된 빈 FeatureCollection만 정상 빈 결과다.
틀린 JSON/INFO/행 수/식별자는 `KritsSchemaError`, 제공자 `header.state != OK`는
`KritsProviderError`, 로그인·접근 거부/redirect는 `KritsAccessError`, 429는
`KritsRateLimitError`다. 자동 재시도는 없다. request listener는 성공·실패·취소 모두에서 제거한다.

오프라인 fixture는 [출처 설명](../tests/fixtures/README.md), 실제 검증은
`tests/test_live_data.py`에 있다. 최신 행 수나 ID를 고정하지 않고 양 도로 종류·양 방향과
돌발 전체/국도 선택을 실제 Chromium에서 검증한다.
