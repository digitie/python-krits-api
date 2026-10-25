# T003 fixture 출처

2026-10-24 실제 Chromium 149에서 키 없이 공개 화면을 열고 도로 목록/돌발 초기 로딩/
구간 펼치기가 받은 응답에서 선별했다. HTTP 직접 호출이나 인증 Open API 응답이 아니다.

- `traffic-highway.json`: 도로 ID `0010`, 방향 `1`의 첫 2구간·4링크.
- `traffic-national.json`: 도로 ID `0001`, 방향 `3`의 첫 1구간·21링크.
- `events.json`: HIGHWAY/NATIONAL 각각 첫 2개 돌발. DISASTER는 조사 시 빈 분기다.

소통 fixture는 `EVENT`/`CCTVP` 분기와 렌더링용 geometry/path, 국도 leaf의 중복 info 객체를
제거했다. 원문 필드·숫자 타입·INFO 집계값·문자열 코드·순서는 보존했다.
행을 선별했으므로 `totalFeatures`는 선별한 행 수로 조정했다.
돌발 `properties.INFO`는 원래 JSON 문자열 그대로다. 세션·쿠키·키는 포함하지 않는다.
현재 실제 값과 일치한다는 테스트가 아니라 응답 구조와 의미 보존 회귀에 사용한다.
# T004 fixture

2026-10-24 Chromium 공개 화면에서 `서울` CCTV 검색, 고속도로 노선번호 `1` 우회,
소통 지도 기점 `대전` 도시간 위젯 응답을 수집했다. cctv.json은 앞 2건이며 미사용 URL 필드를
제거했고, detour.json은 방향별 앞 2건이다. travel.json은 해당 도시의 6건이다.
세션/지도 키/영상/전체 HTML을 포함하지 않는다. 운영 수량을 상수로 보장하는 자료가 아니다.

## T005 파일 목록

`files-traffic/event/vms.json`은 2026-10-24 실제 Chromium에서 2026-10-22~23을 입력하고
조회한 각 2건 응답이다. fileStrDate 등은 의미를 추정하지 않고 원문 보존했다.
`files-weak.json`은 같은 날 실제 DOM의 이름·href만 추출한 4개(이름/아이콘 중복 포함)다.
테스트의 기간 첨부 DOM 값은 실제 관찰한 ID/title/href와 같은 값이다. 원본 ZIP/세션은 포함하지 않는다.

## T006 노드링크

`nodelink.json`과 `nodelink-links.json`은 2026-10-24 실제 자료실에서 2025-10-24~2026-10-24를
조회한 배포 중 seq221/211/210 세 건과 대응 DOM 6첨부다. CSV/XLSX·0/1·5/6·1/2 번호를 포함한다.
`nodelink-partial*.json`은 2024년 조회의 seq201 한 건·원본1첨부다. 내역서 null과 개통 구간만
담았다는 원문 설명을 보존한다. 원본 ZIP·세션·HTML은 포함하지 않는다.


## T011 공개 예측/참고 데이터

2026-10-25 Chromium의 개별 우회 화면에서 type=fc 예측 노선15건과 날짜/시각 지정 공개 웹
요청을 확인했다. forecast-roads.json은15노선, forecast-sections.json은 고속도로1/방향1의
9구간 중 앞2건, forecast-links.json은 같은 첫 구간의 MAIN43/DETOUR148링크 중 각 앞2건이다.
축약한 FeatureCollection의 totalFeatures만2로 조정했고 원문 ID/타입/순서/좌표는 보존했다.
우회 두 번째 링크의 자체 ROAD_NO=47을 본선1로 바꾸지 않는다.
forecast-links-0401.json은 같은 조회의 구간/우회ID `0401` 상세 MAIN8/DETOUR17개에서
MAIN 노선1·451 각각 첫 링크와 DETOUR 앞2개만 보존했다. totalFeatures만2로 조정했다.
MAIN도 상위 노선1과 다른 ROAD_NO를 포함하며 앞자리0을 보존해야 한다.
집계값이 없고 상세 PASNG_SPED=1인 실제 상태를 유효한 예측값으로 꾸미지 않는다.
API 키·토큰·hidden input·쿠키·전체 HTML·XLSX 원본은 fixture에 포함하지 않는다.
참고 XLSX의 실제 원문은 저장소 밖 FileStore에 보관하고 live 검사로 검증한다.
