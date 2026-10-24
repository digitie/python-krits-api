# CCTV·우회·도시간 공개 계약

2026-10-24 실제 Chromium 149에서 조사했다. 인증 Open API, 제3자 지도/영상 호스트를 호출하지
않는다. 모든 결과는 `DataSnapshot`의 조회 범위·출처·수집 UTC 시각과 `complete=False`를 포함한다.
공식 API의 필드/기간/전국 커버리지와 같다고 보장하지 않는다.

## CCTV

`search_cctvs(keyword)`는 `/map/cctv`의 `#inp_search` 입력과 `#btn_search` 클릭을 사용한다.
`/map/getCctvSearch`의 요청은 다른 지도 조회와 달리 `{searchKeyword: 문자열}`이며 응답은
envelope 없는 배열이다. `[]`는 정상 검색 결과 없음이고 객체/null/잘못된 행은 스키마 오류다.
빈 검색은 화면에서 전송하지 않으므로 클라이언트도 거부한다. 키워드는 공백 제거 후 1~100자다.

`cctvId`, `routeNo`, `roadNo`, `linkId`를 서로 다른 문자열로 보존한다. 선행 0이 있는
`000000gnrh...`, `0010`을 숫자로 바꾸지 않는다. 설치명은 `instlLcDc`, 나머지는 `raw`에 둔다.
좌표 x/y의 CRS와 원문 상태 코드의 의미는 추정하지 않는다. 메타데이터만 반환하며 CCTV를
클릭하거나 `/api/cctv/hls`·영상 재생·영상 다운로드 요청을 하지 않는다.

## 현재 고속도로 우회

`list_detour_roads()`는 `/map/detour`의 `.rt_box li.dep1`에서 표시 노선번호와 이름을 읽는다.
소통 화면의 `road_id=0010`과 이 화면의 `road_number=1`은 서로 다른 계약이다.
`get_detours(road_number)`는 해당 노선의 `a.title`을 클릭하고
`/map/getMainToDetourSectionsByRoad`의 다음 요청을 관찰한다.

```json
{"body":{"data":{"searchType":"rt","roadNo":1,"sctnTyCode":"EX","keyword":""}}}
```

사이트의 jQuery가 DOM 노선번호를 숫자로 전송하는 동작을 요청 상관관계에서만 반영한다.
응답 `body.data.SECTIONS.DOWNROAD/UPROAD`의 `ROAD_NO`, `SCTN_TY_CODE=EX`,
`DRC_CODE=1/2`를 교차 검증한다. `MLN_SCTN_ID`와 `DETU_ID`는 별도 문자열로 보존한다.
양방향 순서와 반복 항목을 제거하지 않는다. 두 배열이 명시적으로 비었을 때만 정상 빈 결과다.

`MAIN_PASNG_SPED/DETOUR_PASNG_SPED`는 공개 JS의 `Km/h` 표기,
`MAIN_PASNG_TIME/DETOUR_PASNG_TIME`은 `Number().secToExprsn(...,'m')` 변환으로 단위를
확인했다. 시간 모델은 소수 초를 보존한다. 길이/좌표/등급/예측 가능 여부는 raw 원문이다.
현재 구현은 고속도로 현재 비교이며 국도·미래 예측의 지원을 주장하지 않는다.

## 도시간 소요시간

`list_travel_origins()`와 `get_travel_times(origin)`은 `/map/traffic`의
`.region_list .select select` 기점 선택 위젯을 사용한다. 동적 option 목록을 검증하고
선택 값과 change 이벤트를 사이트에 전달한다. 원래 select가 커스텀 셀렉트에 숨겨져 있어
Playwright `select_option(..., force=True)`를 쓴다. 접근 제한을 변경하는 기능이 아니다.

요청 `/map/getCityReqTimeByGroup`의 `body.data.grpIds`는 **도시 문자열**이고 배열이 아니다.
응답 `body.data.COURSE[]`의 `GRPID/GRPCOURSNM/BSPOTNM/ESPOTNM/REQRETIME`를 검증한다.
각 행의 기점이 조회 값과 같아야 한다. `REQRETIME=166`은 대전→부산 화면의
`2시간 46분`과 일치하며 `Number().minToExprsn`을 사용하므로 모델은 분 단위다.
미래 예측값이나 개별 표준링크 통행시간이라고 설명하지 않는다.

전용 `/map/travelTime` 탭은 그룹 ID **배열**을 전송하며 조사 시 HTTP 307과 Location 없는
JSON 헤더를 반환했다. 이 경로는 정상 수집으로 세지 않고 사용하지 않는다. 정상 200을
반환하는 공개 소통 지도 위젯의 도시 문자열 계약만 구현한다. 307/401/403/429는 우회하지 않는다.
