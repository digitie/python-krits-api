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

