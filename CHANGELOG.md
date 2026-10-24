# 변경 기록

## 0.1.0 개발 중

- ITS 12종 서비스와 5종 파일 범위·키 없는 웹 대응 사양 및 단계별 task 문서.
- native async `KritsClient`, 공개 화면 접근 `PageSnapshot`, 지연 Chromium 생성·자원 소유권.
- 공유 `AsyncTokenBucket`, 직렬 operation, 취소 정리, 종료 후 재사용 거부.
- lock·예산 대기까지 포함한 timeout, HTTP 200 로그인/보안 확인 화면 거부,
  Chromium CDP의 redirect 각 전송 전 origin 검사와 service worker 우회.
- `list_roads`, `get_traffic`, `get_events`: 키 없는 실제 화면 기반 도로 목록,
  방향별 집계 구간/개별 링크, 현재 고속도로·국도 돌발 조회.
- `DataSnapshot`에 출처·UTC 수집 시각·조회 범위·완전성 한계를 제공한다.
- 돌발은 navigation 전부터 최초 응답을 관찰하고 별도 새로고침 없이 반환한다.
  같은 endpoint에서 관찰한 401/403/429는 후속 성공으로 덮지 않는다.
- 재난 분기와 파일 다운로드는 후속 task에서 제공 예정.
