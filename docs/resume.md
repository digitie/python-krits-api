# Transport 지도용 T003 후속 — 검증 통과·머지 대기

- `codex/traffic-link-geometry`는 최신 main085c329(T004~T006)을 통합하고 개별 TrafficLink.path의 EPSG:4326 좌표 계약을 추가한다.
- 공개 polylineOl.js의 실제 LineString 변환과 경부선65구간/361링크의 path를 확인했다.
- 현재 T004 이후 작업은 원래 체크아웃에서 계속하며 이 후속은 그 파일·진행 순서를 바꾸지 않는다.
- offline157개·strict mypy·실제 Chromium live12개와 양방향 경로4표본, James/Popper 독립 리뷰와 b3af6bc CI6개가 통과했다. 설치본을 소비하는 Transport 실제 API/375·1440px 지도도 확인했다. PR4는 Draft이며 머지하지 않았다.

# 재개 지점

T001 PR #1(`1657e13`), T002 PR #2(`b11566e`), T003 PR #3(`61b357f`) 머지를 확인했다.
T004 브랜치는 해당 `origin/main`에서 만들었다. CCTV 검색 메타데이터, 현재 고속도로 우회
양방향 비교, 공개 소통 지도 기점 위젯의 도시간 소요시간을 구현했다.
계약과 전용 도시간 탭의 307 제한은 `cctv-detour-travel.md`를 확인한다.
T004 PR #5 최종 소스 `8963485`에서 두 독립 리뷰, 오프라인190/99.18%, 전체live22,
별도 wheel설치본 및 원격CI6개job을 통과했다. `docs/validation/t004.md`를 확인한다.
최종 증빙 commit CI6개 job 통과 후 PR #5를 `2de4dc6`으로 머지했다.
해당 `origin/main`에서 T005 일반 파일 발견을 구현했다. `list_data_files`의 기간 ZIP/정적CSV,
DOM 교차 검증·날짜 경계·초기 요청 거부와 선택적 초기 요청을 검증 중이다.
상세는 `docs/files-catalog.md`. T005 PR #6 소스 `a897c51`에서 두 독립 리뷰, 오프라인240/99.45%,
신규live9·전체live31, 별도wheel설치본·최종증빙CI6개job을 통과하고 `4ece092`로 머지했다.
해당 `origin/main`에서 T006 노드링크 자료실을 구현했다. 최신/역사 XLSX/부분배포/빈기간
신규 live4개 통과. `docs/nodelink-catalog.md`의 실제 ID·번호·MB·범위 계약을 확인한다.
T006 PR #7 최종 소스 `c8f1cb2`에서 두 독립 재리뷰, 오프라인268/99.51%, 전체live35,
별도wheel설치본·소스CI6개 job 통과. 최종증빙CI·머지 확인 중이다.
개발/테스트는 사용자가 허용한 Windows 네이티브로 계속한다. 인증 API를 호출하거나 키를 저장하지 않는다.
사용자 추가 지시에 따라 다운로드 전 Opinet 기준 전송 예산·캐시·동일 요청 공유 하위 단계를 검증한다.
사용자는 T004–T010 완주를 자율 진행하도록 승인했다. 각 task의 게이트는 유지한다.
API 키는 없으며 발급받는 작업을 제안하지 않는다. 구현 transport는 Chromium async다.
