# Transport 지도용 T003 후속 — 검증 통과·머지 대기

- `codex/traffic-link-geometry`는 머지된61b357f 위에서 개별 TrafficLink.path의 EPSG:4326 좌표 계약만 추가한다.
- 공개 polylineOl.js의 실제 LineString 변환과 경부선65구간/361링크의 path를 확인했다.
- 현재 T004 이후 작업은 원래 체크아웃에서 계속하며 이 후속은 그 파일·진행 순서를 바꾸지 않는다.
- offline157개·strict mypy·실제 Chromium live12개와 양방향 경로4표본, James/Popper 독립 리뷰와 b3af6bc CI6개가 통과했다. 설치본을 소비하는 Transport 실제 API/375·1440px 지도도 확인했다. PR4는 Draft이며 머지하지 않았다.

# 재개 지점

T001 문서 PR #1은 `1657e13`으로 머지했다. T002 브랜치에서
패키지 구조·비동기 Chromium 생명주기·공유 제한기·예외·CI를 구현했다.
T002 PR #2의 두 독립 리뷰·로컬 검사·live·원격 CI 6개 job이 통과했다.
PR #2는 `b11566e`로 머지했다. `origin/main`에서 T003 소통·돌발 조회를 구현 중이다.
도로 목록·방향별 구간/개별 링크·돌발의 공개 메서드와 엄격 파서를 추가했다.
T003 PR #3 최종 소스 `bc143ea`에서 두 독립 리뷰, 오프라인 146개/99.15%, 실제 Chromium
live 12개, 설치본 검증이 통과했다. `docs/validation/t003.md`를 확인한다.
T003 증빙 `d3fa583`의 원격 CI 6개 job이 모두 통과했다. PR #3 최종 문서 commit의 CI와
머지를 확인한 뒤 `origin/main`에서 T004 CCTV·우회·도시간 조회로 진행한다.
API 키는 없으며 발급받는 작업을 제안하지 않는다. 구현 transport는 Chromium async다.
