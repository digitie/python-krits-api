# 작업 기록

## 2026-10-24

- 원격 `digitie/python-krits-api`를 복제하고 `origin/main`을 기준으로 설정했다.
- 원격 초기 tree는 LICENSE만 있다. 참조 3개 프로젝트의 구조·async·파일 관리 경계를 조사했다.
- Chromium에서 ITS 오픈데이터 소개, 교통·돌발·CCTV·우회·도시간 화면과 노드링크 자료실을 탐색했다.
- T001 문서 PR #1: 독립 리뷰 A의 P2 2건 수정 후 A/B 모두 통과했다.
- Chromium 149로 12종 사양 페이지와 노드링크 10배포·20첨부 재현 검증이 종료 코드 0으로 끝났다.
  문서 CI 통과. 최종 증빙 commit의 CI 확인 후 머지하고 T002를 진행한다.
- T001 PR #1을 `1657e13`으로 머지했다. `origin/main`에서 T002 브랜치를 만들었다.
- KRIC src 레이아웃과 Opinet 공유 버킷을 적용해 async Chromium 기반을 구현 중이다.
- T002 PR #2: 두 독립 리뷰의 접근 화면·timeout·redirect 지적을 수정하고 최종 재검토를 통과했다.
  오프라인 62개/98.39%, live 3개 및 별도 wheel 설치본 live가 통과했다.
  최종 증빙 commit의 원격 CI runner 대기를 확인 중이며 CI 통과 전에는 머지하지 않는다.
