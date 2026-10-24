# 완료한 작업

| ID | 결과 | PR | 증빙 |
|---|---|---|---|
| T001 | 12종 서비스·5종 파일 범위 조사, 구조·상세 사양·10단계 계획·검증 정책 | [#1](https://github.com/digitie/python-krits-api/pull/1) | [독립 리뷰 2건·Chromium live·CI](validation/t001.md) |
| T002 | KRIC src 구조, native async Chromium·공유 버킷·생명주기·오류·CI·설치본 | [#2](https://github.com/digitie/python-krits-api/pull/2) | [독립 리뷰 2건·62 오프라인·3 live·wheel·CI](validation/t002.md) |
| T003 | 도로 목록·양방향 소통 구간/개별 링크·현재 고속도로/국도 돌발, 엄격 파서와 조회 범위 | [#3](https://github.com/digitie/python-krits-api/pull/3) | [독립 리뷰 2건·146 오프라인·12 live·wheel·CI](validation/t003.md) |
| T004 | CCTV 검색 메타데이터·현재 고속도로 우회 양방향·기점 위젯 도시간 소요시간 | [#5](https://github.com/digitie/python-krits-api/pull/5) | [독립 리뷰 2건·190 오프라인·22 live·wheel·CI](validation/t004.md) |
| T005 | 소통·돌발·VMS 기간 ZIP·정적 취약구간 CSV 발견, 날짜·첨부 DOM 대조 | [#6](https://github.com/digitie/python-krits-api/pull/6) | [독립 리뷰 2건·240 오프라인·31 live·wheel·CI](validation/t005.md) |

PR 머지를 확인한 뒤 다음 task를 시작한다.

T004 PR #5는 최종 증빙 head의 CI 6개 job 통과 후 `2de4dc6`으로 머지했다.

T005 PR #6은 최종 증빙 head의 CI6개 job 통과 후 `4ece092`로 머지했다.

T006 PR #7 소스 `c8f1cb2`는 두 독립 재리뷰·오프라인268/99.51%·전체live35·설치본·소스CI를 통과했다.
최종 증빙 head CI와 머지 확인 후 완료 표로 옮긴다. [증빙](validation/t006.md).
