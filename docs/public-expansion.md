# T011 미지원 서비스의 공개 웹 재조사와 확장

2026-10-25 Windows 네이티브 Chromium으로 메인 통합지도, 개별 우회·통계·검색 화면과
기존 미지원5종의 공개 사양 페이지를 다시 조사했다. 인증 API나 키를 사용하지 않았다.
구현 범위는 고속도로 예측 대상/상세 원문과 예측 본선·VDS·VSL의 공개 참고 XLSX다.
VDS 실시간 검지값, VSL 실시간 가변 제한속도, 주의운전 메시지와 위험물 차량 사고 전용 조회는 미지원이다.

## 화면과 요청의 차이

| 화면 | 실제 확인 | 판정 |
|---|---|---|
| 메인 `/` | `/js/singlePage` 스크립트와 예측 탭, fc 노선 요청 | 예측 노선 응답은15개지만 필요한 목록 template이 없어 표시가 비는 동작 관찰 |
| 개별 `/map/detour` | 예측 노선 DOM·예측정보 탭·달력·예측 구간/상세 요청 | 구현의 출처. 메인 통합지도의 오류를 정상 빈 목록으로 수용하지 않음 |
| `/map/statistics` | 소통/사고 통계, 요일·특정일 UI | VDS 차로별 교통량·점유율이나 VSL 표지별 실시간 조회로 볼 근거 없음 |
| `/map/searchLocation` | 위치 검색 UI와 지도 검색 스크립트 | 검지기/VSL/위험물 차량 전용 조회를 확인하지 못함 |
| 기존 미지원5종 사양 페이지 | 인증키 신청·API 안내 HWP, 아래의 공개 XLSX | 안내 문서를 실시간 데이터로 분류하지 않음 |

개별 detourMap.js에는 fc 분기와 별도 `LIST` 응답이 있었다. 앞선 T009의 미지원 판정은
당시 확인한 범위의 판정이며, T011에서 실제 요청 완료를 기다리고 예측 전용 DOM을 확인해 보완했다.
페이지의 networkidle 상태만으로 새 탭의 요청/렌더링 완료를 가정하면 안 된다.

## 공개 예측 메서드

- `list_forecast_roads()` → `DataSnapshot[DetourRoad]`: 예측 전용 고속도로 노선번호.
- `list_forecast_sections(road_number, *, forecast_date, hour, direction="1")`
  → `DataSnapshot[ForecastSection]`: 날짜·시각·방향별 구간/우회 ID·예측 대상 여부·원시 등급·선택 집계값.
- `get_forecast_links(road_number, section_id, detour_id, *, forecast_date, hour, direction="1")`
  → `DataSnapshot[ForecastLink]`: 선택 구간의 MAIN/DETOUR 링크 원문·순서·길이·원시 수치·geometry.

입력 ID는 문자열이다. 날짜는 datetime이 아닌 date, 시각은 bool이 아닌0~23 정수,
고속도로 방향은 문자열1/2다. 존재하지 않는 노선/구간을 임의 endpoint로 요청하지 않는다.
날짜 범위는 페이지의 datepicker 설정을 읽으며 현재는 페이지 현재일~6일 뒤다.
과거 시각은 거부한다. `clock_basis=page_local_calendar`는 페이지의 로컬 달력 기준이며
수집 UTC와 예측 civil date/hour를 구분한다. 근거 없이 서버 시간대를 부여하지 않는다.

실제 페이지의 초기 fc 요청은 `/map/getMainToDetourRoads`의
`body.data={type:"fc",sctnTyCode:"EX"}`다. 응답과 예측 노선 DOM을 교차 확인한다.
구간은 `/map/getMainToDetourSectionsByRoad`의
`{searchType:"fc",roadNo,sctnTyCode:"EX",drcCode,fcDate:"YYYYMMDD",fcHour:"HH"}`,
상세는 `/map/getMainToDetourSection`의 `{searchType:"fc",sctnId,detuId,fcDate,fcHour}`를 사용한다.

공개 JS의 `getLinkList`는 조회 버튼에서도 선택 시각을 현재 시각으로 덮어쓴다.
provider는 해당 함수를 수정하지 않는다. 페이지를 방문하고 같은 페이지의 `ajaxRequest`로
공개 JS에서 확인한 요청을 보내며 실제 POST의 모든 조건과 대응 응답을 확인한다.
일반 HTTP transport·인증 API로 전환하지 않는다. 페이지의 세션 처리는 사이트 함수가 수행하며
쿠키/hidden 값/토큰을 추출·저장하지 않는다. 접근 거부에 추가 요청이나 우회는 없다.

응답은 예측 날짜/시각을 별도로 echo하지 않는다. snapshot의 scope는 관찰한 요청 조건이며
제공자가 그 조건으로 올바른 예측을 계산했다는 검증은 아니다. 실제 고속도로1의 양방향9구간과
첫 구간 본선43/우회148링크를 확인했다. 국도 예측은 검증하지 않아 구현 범위에서 제외했다.
같은 구간·우회 조합을 현재 조회 목록에서 확인한 뒤 상세 한 건만 요청한다.

## 결측·원시값 계약

`ForecastSection`의 MAIN/DETOUR_PASNG_SPED/TIME은 실제 응답에 없거나 null일 수 있다.
화면도 undefined/null을 정보 없음으로 처리하므로 이 네 집계 필드만 선택 값으로 선언했다.
각각 `main_speed_kmh`, `detour_speed_kmh`, `main_time_seconds`, `detour_time_seconds`의 None이다.
그 외 필수 목록/ID/노선·방향·예측 대상/등급 누락과 잘못된 타입은 스키마 오류다.
`PREDICT_AT=Y`는 예측 대상 여부이며 유효한 예측 수치가 있다는 뜻이 아니다.

관찰 시 집계값은 모두 없었고 상세 링크의 PASNG_SPED는 모두1이었다.
이 값을 정체 속도나 공식 API의 유효한 예측 속도로 단정하지 않는다.
`ForecastLink.raw_speed`와 raw_info에 그대로 보존하고 링크 원시값으로 집계 결측을 채우지 않는다.
상세 링크의 ROAD_NO는 MAIN/DETOUR 모두 상위 조회 노선번호와 다를 수 있다.
실제 노선1의 구간 `0401` 본선에는 ROAD_NO `1`과 `451`이 함께 있었다.
구간 소속은 선택한 MLN_SCTN_ID로 검사하고 링크 자체의 ROAD_NO는 원문에 보존한다.
본선 노선/양쪽 구간 ID를 검사하고 우회 링크의 자체 노선번호를 보존한다.
순서를 바꾸거나 LINK_ID로 중복 제거하지 않는다. 같은 경로의 LINK_SEQ 중복은 오류다.
좌표는 [공개 polylineOl.js](https://www.its.go.kr/js/map/polylineOl.js)의 GeoJSON 계약으로 검사하고
geometry 원문을 보존한다. 별도 좌표 변환이나 예측 알고리즘을 추가하지 않는다.

## 공개 참고 데이터와 파일 관리

`list_reference_files(service)`는 다음3종의 실제 공개 사양 페이지에서 XLSX anchor를 발견한다.
서비스는 `fcTraffic`, `detectorInfo`, `vsl`만 받으며 날짜 인자는 없다.

| service | 공개 참고 데이터 | 실제 첫 시트/행 |
|---|---|---|
| fcTraffic | [본선 구간 정보.xlsx](https://www.its.go.kr/file/opendata/fcTraffic/section_id_info.xlsx) | 본선_구간_정보_기본/141 |
| detectorInfo | [VDS 시설물 정보.xlsx](https://www.its.go.kr/file/opendata/vds/vdsStatus.xlsx) | Sheet1/5,937 |
| vsl | [고속도로 VSL 현황.xlsx](https://www.its.go.kr/file/opendata/vsl/highwayVSLStatus.xlsx) | Sheet4/849 |
| vsl | [국도 VSL 현황.xlsx](https://www.its.go.kr/file/opendata/vsl/nationalVSLStatus.xlsx) | TN_VSL/1,745 |

표의 행 수는 조사 시점의 원문이며 고정 계약이 아니다. 게시 기준일·ID·바이트 수는 DOM에
없으므로 추정하지 않는다. `edition=not_provided`, file_id/attachment_id/size_bytes=None이다.
HWP API 안내서는 데이터 파일로 분류하지 않는다. 같은 anchor의 반복만 병합하며 이름 불일치,
알려진 XLSX 누락/경로 변경은 정상 빈 결과가 아닌 스키마 오류다.
4개의 실제 고정 경로만 다운로드 검증에 추가했고 임의 `/file` 경로를 허용하지 않았다.

`download_file`/`FileStore`/`inspect_file`/`read_xlsx`를 그대로 사용한다. 원본·해시·불변 manifest와
검사 보고서를 보존하고 재실행은 로컬 hash 검증 후 재사용한다. 원문 교체 확인은 refresh=True다.
갱신일을 제공하지 않는 정적 참고 자료이므로 현재 시설물 전체나 실시간 상태라고 설명하지 않는다.
테스트는 최대 전송50MiB, 선택 XML64MiB/100,000행의 명시적 상한으로 첫 시트를 읽었다.
전체 원본은 저장소 밖에 보관하며 fixture에는 파일 원문을 포함하지 않는다.

## 나머지 실시간 서비스의 판정

VDS 참고 XLSX는 위치/시설물 현황이지 차로별 교통량·점유율의 현재 관측값이 아니다.
VSL 참고 XLSX와 소통 링크의 정적 LMTT_SPED도 표지별 가변 제한속도 응답이 아니다.
따라서 두 서비스는 `files`로 판정하고 실시간 항목은 미지원으로 명시한다.
주의운전과 위험물 차량은 재조사한 공개 화면/응답에서 전용 메시지/사고 계약을 찾지 못했다.
주의운전의 단계·우선순위·시종점 링크와 위험물 전용 식별자·상태를 일반 돌발에서 추정하지 않는다.
살얼음 UI는 운영 시간 조건과 WMS 타일 중심이며 공식 주의운전 메시지 계약으로 대체하지 않는다.
인증키를 요구하는 예제 실행/API 호출로 넘어가지 않는다.

지원표는10종의 부분 지원/파일과2종 미지원이며, 이 수치가10종의 실시간 API 동등 구현을 뜻하지 않는다.
공통 전송 예산·캐시·동일 조회 공유·취소 정리와 각 단계401/403/429 중단을 유지한다.
