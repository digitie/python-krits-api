# 변경 기록

## 0.1.0 개발 중

- ITS 12종 서비스와 5종 파일 범위·키 없는 웹 대응 사양 및 단계별 task 문서.
- native async `KritsClient`, 공개 화면 접근 `PageSnapshot`, 지연 Chromium 생성·자원 소유권.
- 공유 `AsyncTokenBucket`, 직렬 operation, 취소 정리, 종료 후 재사용 거부.
- lock·예산 대기까지 포함한 timeout, HTTP 200 로그인/보안 확인 화면 거부,
  Chromium CDP의 redirect 각 전송 전 origin 검사와 service worker 우회.
- 교통 데이터 목록과 파일 다운로드는 후속 task에서 제공 예정.
