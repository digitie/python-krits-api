# 나머지 공식 서비스와 공개 웹 대응

2026-10-25 Chromium 149 재조사 기준이다. 인증 API는 호출하지 않았다.
공식 사양은 비교 기준이며 공개 웹의 ID·시각·범위가 공식 API와 같다는 뜻이 아니다.
`list_capabilities()`는 아래 판정을 네트워크 없이 반환한다. 사이트의 실시간 상태 검사는 아니다.

| 공식 서비스 | 공개 구현 | 한계 |
|---|---|---|
| traffic | `list_roads`, `get_traffic`, 기간 파일 목록 | 선택 도로·방향의 현재 구간. 전국 완전성 미보장 |
| event | `get_events`, 기간 파일 목록 | 현재 HIGHWAY/NATIONAL. DISASTER 제외 |
| cctv | `search_cctvs` | 이름 검색 메타데이터. 영상은 제공하지 않음 |
| fcTraffic | `list_forecast_roads`, `list_forecast_sections`, `get_forecast_links`, `list_reference_files` | 고속도로 날짜·시각·방향별 예측 대상/상세 원문과 본선 구간 XLSX. 집계 결측·원시 speed 의미·국도 한계 있음 |
| detectorInfo | `list_reference_files("detectorInfo")` | VDS 시설물 현황 XLSX만 지원. 차로별 실시간 속도/교통량/점유율은 미지원 |
| vms | `get_vms`, 기간 파일 목록 | 현재 지도 표출 원문. 공식 메시지 순번/생성시각 동등성 미보장 |
| safeDriving | 미지원 | 우선순위·단계·시종점 링크 메시지 미확인. 취약구간 파일과 다름 |
| vsl | `list_reference_files("vsl")` | 고속도로/국도 VSL 현황 XLSX만 지원. 실시간 가변/기본 제한속도 조회는 미지원 |
| weakSection | `list_data_files("weakSection")` | 결빙·안개 CSV 원문. 인코딩 명시, CRS 추정 없음 |
| nodelink | `list_nodelink_releases` | 배포·첨부 발견과 원본 보관. 형상 DB/지도는 소비자 책임 |
| dangerousCarInfo | 미지원 | 위험물 차량 사고 전용 ID·상태 조회 미확인. 일반 돌발에서 추정하지 않음 |
| disaster | `get_disaster_zones` | 현재 DISASTER 구역만. 도로 재난성 돌발/과거 조회 제외 |

`list_data_files`는 발견이며, 원본 전송·해시 보관은 공통 `download_file`/`FileStore`,
검사는 `inspect_file`/`read_csv`/`read_xlsx`로 수행한다. 일반 파일의 접근 거부는 오류다.
우회 비교와 도시간 소요시간은 공식 12종 외 추가 공개 웹 기능이다.

## VMS 계약

[소통 지도](https://www.its.go.kr/map/traffic)의 지도 세부사항 선택 상자를 열고 VMS 버튼을 누른다.
[markerOl.js](https://www.its.go.kr/js/map/markerOl.js)의 `getVmsMarkerList`가 사용하는
`/map/getMarkers` POST `body.data={type:"VMS",keyword:""}`의 응답만 읽는다.
기존 화면 설정으로 초기 VMS 요청이 발생하면 먼저 검증해 재사용한다. 별도 refresh를 하지 않는다.
초기 응답도 빈 keyword만 허용하며 다른 검색 조건이면 스키마 오류로 중단한다.
추가 endpoint를 합성하거나 인증 API를 호출하지 않는다.

GeoJSON `FeatureCollection`의 `totalFeatures`와 실제 행 수, `Feature`/properties.type=`VMS`,
문자열 INFO의 `vmsId`와 Feature ID, 중복 ID를 검사한다. `Vms`는
`vms_id`, `message`(`vmsEprssCn`), `route_name`(`routeNm`),
`route_number`(`routeNo`), `direction_name`(`drcNm`), `raw_info`를 가진다.
선택 값의 명시적 null은 None이며 열 자체 누락은 오류다.
`@@@`, `|`, HTML처럼 보이는 메시지도 원문이다. UI로 표시하는 소비자는 텍스트로 처리한다.
공식 `messageNo`/`createdDate`로 원시 null이나 수집 시각을 대신 채우지 않는다.

실제 2,101건의 비어 있지 않은 응답과 메시지 구분자를 확인했다. fixture는 이 중 2건만 보관한다.
snapshot scope는 `layer=VMS,time=current`, 출처는 소통 지도, `complete=False`다.

## 재난구역 계약

[돌발 지도](https://www.its.go.kr/map/outbreak)의 초기 `/map/getMarkers` 빈 type 응답 중
`DISASTER` FeatureCollection만 사용한다. `get_events`가 반환하는 HIGHWAY/NATIONAL의
재난성 돌발을 합치거나 `commonMap.js`의 화면 분류를 공식 API 코드로 바꾸지 않는다.
현재 구역 전체를 반환하며 코드별 UI 필터로 항목을 버리지 않는다.

`DisasterZone`은 `disaster_id`(`dangerId`/Feature ID), `zone_type`(`msfrtnZoneTyCode`),
`zone_type_name`, `title`(`msfrtnZoneSj`), `occurred_at_raw`/`ended_at_raw`, `raw_info`를 가진다.
시간 문자열에 시간대를 추정 부여하지 않는다. `msfrtnZoneScope` WKT·좌표는 raw에 남기며 CRS를 추정하지 않는다.
scope는 `group=DISASTER,time=current,excluded=HIGHWAY,NATIONAL`, `complete=False`다.
공식 disaster의 날짜 범위·도로 링크/발생 유형 조회와 다르다. 실제 화재구역 1건으로 필드를 확인했다.
실제 빈 구역은 가능하지만 누락 collection/잘못된 INFO는 정상 빈 결과가 아니다.

## 초기 판정과 재조사

T001에서 공식 12종 사양 페이지를 실제 Chromium으로 읽었다. T009에서는 같은 날 수집한
traffic/outbreak/cctv/detour/travelTime 화면과 공개 mapOl/markerOl/polylineOl/commonMap 및
각 화면 JS의 UI·요청을 대조했다. 공개 메뉴의 OpenData 링크는 인증 API 사양으로 연결된다.
T009에서는 VMS와 현재 재난구역을 검증했고 나머지5종을 당시 확인한 범위에서 미지원으로 판정했다.
T011은 요청 완료·예측 전용 DOM을 명시적으로 기다려 개별 우회 화면의 fc 분기와 날짜/시각 요청을
실제로 확인했고, VDS/VSL 참고 XLSX도 발견·전송·읽기 검증했다. 이전의 예측 미지원 판정을 수정한다.

이는 사이트 전체에 해당 데이터가 절대 없다는 주장이 아니다. 확인한 공개 UI에서 검증되지 않아
현재는10종의 부분 지원/파일과2종 미지원이며 실시간 API10종을 동등 구현했다는 뜻이 아니다.
세부 요청·결측/원시값·정적 파일·조사 한계는 [T011 확장 사양](public-expansion.md)을 따른다.
[예측 공식 사양](https://www.its.go.kr/opendata/opendataList?service=fcTraffic),
[VDS](https://www.its.go.kr/opendata/opendataList?service=detectorInfo),
[주의운전](https://www.its.go.kr/opendata/opendataList?service=safeDriving),
[VSL](https://www.its.go.kr/opendata/opendataList?service=vsl),
[위험물](https://www.its.go.kr/opendata/opendataList?service=dangerousCarInfo)을 참고한다.
인증 API fallback이나 추정 데이터는 제공하지 않는다.

## Windows 보관 경로 회귀

전체 오프라인 검사에서 기존 동시 저장1건이 실패했다. 두 worker가 처음 manifest 디렉터리를
생성하는 사이 `Path.resolve()`가 한쪽에만 `\\?\` 접두사를 남기는 상황을 별도 실행으로 재현했다.
동일 드라이브/UNC 경로의 비교 표기를 맞췄으며 symlink/바깥 경로 검사는 유지한다.
비교만 정규화하며 실제 I/O는 원래 resolve 경로를 보존해 확장 경로의 trailing dot도 유지한다.
Volume GUID 등 다른 장치 이름은 변환하지 않는다. 동시 생성30쌍과 접두사 단위 테스트를 추가했다.
근거는 [CPython ntpath.realpath 구현](https://github.com/python/cpython/blob/main/Lib/ntpath.py)의
접두사 제거 전 재조회 분기다. 네트워크 재시도나 접근 정책 변경은 없다.
