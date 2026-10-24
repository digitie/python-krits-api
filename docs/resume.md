# 재개 지점

현재 단계는 T007 다운로드·manifest 구현이다. T001–T006A는 머지 완료다.
T007은 CDP64KiB 스트림·상한/길이/HTML 검사·해시 원본·불변 manifest·재검증/재사용을 추가했다.
최종 소스 `5f3d558`에서 두 독립 재리뷰, 오프라인382/98.06%, 전체live55,
별도 wheel의 실제 CSV 전송/재사용과 소스CI6개job을 통과했다.
검증 증빙 head CI 확인 후 PR #9를 머지한다. 계약은 `download-storage.md`를 따른다.
별도 작업 PR #4의 개별 링크 EPSG:4326 경로 기능은 `65fdf78`로 머지됐고 T006A에
`1915033`으로 통합했다. [해당 검증 이력](validation/traffic-link-geometry.md)은 보존한다.
PR #8은 최종 증빙 CI6개 job 통과 후 `d31eeb5`로 머지했다. 해당 `origin/main`에서
`codex/t007-download-manifest`를 만들었다. T008–T010까지 자율 진행한다.

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
별도wheel설치본·최종증빙CI6개 job 통과 후 `085c329`로 머지했다.
개발/테스트는 사용자가 허용한 Windows 네이티브로 계속한다. 인증 API를 호출하거나 키를 저장하지 않는다.
사용자 추가 지시에 따라 다운로드 전 Opinet 기준 전송 예산·캐시·동일 요청 공유 하위 단계를 검증한다.
`origin/main`에서 T006A를 구현 중이다. 실제 전송 단위 5RPS/burst1, 기본 TTL15초/32항목과
동일 진행 조회 공유·취소 정리를 추가했다. 최종 통합 소스 `1915033`의 두 독립 리뷰,
오프라인309/99.05%, 전체live43, 빌드와 원격CI6개job을 통과했다.
검증 증빙 head `97630e1`의 CI 확인 후 PR #8을 머지했다. 상세는 `validation/t006a.md`다.
사용자는 T004–T010 완주를 자율 진행하도록 승인했다. 각 task의 게이트는 유지한다.
provider는 API 키를 요구하거나 저장하지 않는다. 구현 transport는 Chromium async다.
