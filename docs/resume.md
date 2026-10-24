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
신규live9·전체live31, 별도wheel설치본·소스CI6개job을 통과했다. 최종증빙CI·머지 확인 중이다.
사용자는 T004–T010 완주를 자율 진행하도록 승인했다. 각 task의 게이트는 유지한다.
API 키는 없으며 발급받는 작업을 제안하지 않는다. 구현 transport는 Chromium async다.
