# 재개 지점

T001–T011과 추가 부하 제어 T006A를 완료했다. 현재 진행 중인 구현 task는 없다.
T011 PR #14는 증빙 head `a3f2d6c5d69ade928c97f3a70f5ff2a0f6d79603`의
두 독립 문서 검토와 CI40179595983(6개job) 성공 후
`cdbb0bab9c25eb4104f44e3b58d1f11bca43cdcf`로 origin/main에 머지됐다.
머지 확인 뒤 tasks/tasks-done/journal/resume 완료 기록을 함께 갱신한다.
[완료 목록](tasks-done.md), [T011 증빙](validation/t011.md)을 확인한다.

최종 구현 `b2b4e37`에서 두 독립 재리뷰·offline598/97.26%·저장소 밖sdist598·
전체Chromium78개(skip0)·격리wheel의 기존/새 기능 통합을 통과했다.
예측15노선/양방향각9구간/첫상세191링크, 지선0401의 MAIN 노선1/451 혼재를 확인했다.
추가 공개 API는 list_forecast_roads/list_forecast_sections/get_forecast_links/list_reference_files다.
[확장 사양](public-expansion.md)과 [공식 서비스 대응표](remaining-services.md)에 계약과 한계가 있다.

예측 집계 결측은 None, 상세 원시 speed=1은 raw_speed다. 공식 예측 정확도를 주장하지 않는다.
참고4XLSX는 예측 본선/VDS시설물/고속도로·국도VSL 정적 자료다.
VDS실시간 차로관측·VSL가변속도·주의운전 메시지·위험물차량 전용 사고조회는 미지원이다.
지원표의10종 부분 지원/파일·2종 미지원은10종 실시간 API 동등 구현을 의미하지 않는다.

원본/manifest/검사 보고서는 저장소 밖 `F:\dev\_data\krits`에 있다.
노드링크 ZIP271402628bytes/11항목/CRC/prj2개와 참고4XLSX/CSV를 보존했다.
T011의 전체ZIP과 설치본 참고4개·CSV·ZIP은 보관본 재검증으로 추가 전송0회였다.
[설치/전체ZIP runbook](runbooks/integration.md)을 따른다. 원본/이전 버전을 자동 삭제하지 않는다.

개발·테스트는 허용된 Windows 네이티브다. 인증 API와 키는 사용·저장하지 않았다.
스케줄러/DB/지도 서비스는 소비자가 담당한다. PyPI 게시·외부S3 운영계정·운영배포는 수행하지 않았다.
