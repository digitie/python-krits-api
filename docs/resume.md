# 재개 지점

T001–T010과 추가 부하 제어 T006A를 완료했고, 사용자 후속 요청 T011을 진행한다.
현재 브랜치는 최신 origin/main에서 만든 codex/t011-public-expansion이다.
미지원5종을 메인 통합지도·개별/통계/검색 화면까지 재조사해 실제 공개 응답이 검증된 기능을 추가한다.
두 독립 리뷰·Chromium live·CI 통과 후 머지한다.
T011 최종 구현 b2b4e37은 두 재리뷰·offline598/97.26%·전체Chromium78개(skip0)·
별도wheel 기존/새 기능·참고4파일/전체ZIP재사용·sdist·소스CI6개job을 통과했다.
[T011 증빙](validation/t011.md)의 최종 문서 CI를 확인하고 PR #14를 머지한다.
T010 PR #12의 증빙 head `bfad2e5`는 CI40069682240의 6개 job을 통과했고,
`1d430aba47caaffa27e81e963307f77678d9e7c1`로 origin/main에 머지됐다.
[완료 목록](tasks-done.md)과 [최종 증빙](validation/t010.md)에 상세 이력이 있다.

최종 리뷰 소스 `1dac9f7`에서 두 독립 재리뷰·오프라인498개/coverage97.05%·
별도 sdist498개·mypy/build를 통과했다. 전체 Chromium live64개는 `2581b24`,
최종 영향 범위 ZIP1개와 별도 wheel 전체 기능 통합은 `1dac9f7`에서 통과했다.
각 SHA와 실행 범위는 증빙에 구분한다. T010 동안 provider runtime 변경은 없다.

전체 노드링크 ZIP271,402,628bytes/11항목의 SHA·CRC·prj 원문을 확인했고,
저장소 밖 `F:\dev\_data\krits`에 원본/manifest/검사 보고서를 보관한다.
실제 대용량 전송은1회이며, 이후 실행과 설치본은 보관본을 재검증해 전송0회로 재사용했다.
작은 CSV655bytes/CP949/9행과 ZIP 내부 내역서 선택 읽기도 확인했다.

개발·검증은 사용자가 허용한 Windows 네이티브다. 인증 API나 키는 사용·저장하지 않았다.
T011은 고속도로 예측 대상/상세 원문과 예측 본선·VDS·VSL 참고 XLSX를 추가했다.
VDS 실시간 관측·VSL 실시간 제한속도·주의운전·위험물 차량 전용 조회는 미지원이다.
[확장 사양](public-expansion.md)에 사이트 시각 덮어쓰기·원시 speed=1·집계 결측·정적 파일 한계를 명시했다.
[대응표](remaining-services.md), [설치/전체 ZIP runbook](runbooks/integration.md)을 확인한다.
공식 API 동등성·전국 완전성을 주장하지 않으며 스케줄러/DB/지도 서비스는 소비자 책임이다.
PyPI 게시·외부 S3 운영 계정·운영 배포는 수행하지 않았다.
