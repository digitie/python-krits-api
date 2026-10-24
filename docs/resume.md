# 재개 지점

현재 T010 통합·릴리스 준비를 진행한다. T001–T009는 순서대로 PR 머지 완료다.
T009 PR #11의 최종 소스 f441c93에서 두 독립 재리뷰·offline493/97.05%·mypy/build/CI6개job,
전체live63(c5cf9bf)와 수정 후 영향 범위9(f441c93)를 확인했다.
증빙 head84ba1da CI6개job 성공 후 c22fa34로 머지했다. [검증 기록](validation/t009.md)을 확인한다.
현재 브랜치는 해당 origin/main에서 만든 codex/t010-integration이다.

T010은 전체 노드링크 ZIP을 저장소 밖 FileStore에 한 번 수집하고 CRC/prj/cpg·해시·재사용을
검증한다. 별도 wheel 설치본으로 전체 공개 기능과 작은 내역서·전체 ZIP 재사용을 검증한다.
README·CHANGELOG·지원 범위를 확정하고 두 독립 리뷰·실제 live·CI를 통과한 뒤 머지한다.
최종 검증이 끝나기 전 완료로 표시하지 않는다.

개발·검증은 사용자가 허용한 Windows 네이티브다. 인증 API나 키는 사용·저장하지 않는다.
공통 FIFO 버킷·TTL/LRU·진행 조회 공유·취소 정리와 실패/빈 결과 구분을 유지한다.
공식12종 중 공개 계약을 확인하지 못한5종은 명시적 미지원이다. [대응표](remaining-services.md) 참조.
provider는 스케줄러·서비스 DB·지도 서비스를 포함하지 않는다.
기존 단계의 상세 결과는 [완료 목록](tasks-done.md), 원래 사양은 [조사 사양](source-analysis.md)에 있다.
