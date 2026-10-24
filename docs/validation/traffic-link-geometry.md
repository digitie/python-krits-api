# 개별 소통 링크 경로 검증

T003이 머지된61b357f 위의 Transport 지도 소비를 위한 작은 후속이다. 원래 체크아웃의 T004 이후 작업은 변경하지 않는다.

- 공개 polylineOl.js의 `new ol.geom.LineString(link.path).transform('EPSG:4326', ...)`를 실제 Chromium에서 확인했다.
- SDK `TrafficLink.path`는 개별 속도와 같은 LINK_INFO 행의 경도/위도 tuple이다. 링크 코드를 바꾸거나 다른 provider와 결합하지 않는다.
- 원시 path는 raw에 보존한다. 누락/null은 빈 tuple, 잘못된 타입·범위·점 수는 스키마 오류다.
- WSL Python3.13 strict mypy 7파일 PASS, 오프라인157개/99.23% PASS, 실제 Chromium live12개 PASS다.
- live 시각은2026-10-24 11:11 KST다. 고속도로 양방향65/64구간·361/354링크,
  국도 양방향47구간·1186/1187링크를 조회했다. 경로가 제공된 모든 점의 WGS84 범위를 검사했고,
  경로가 제공된 링크가 최소1개 이상임을 검증했다. 전체 링크에 경로가 있다는 보장은 아니며
  후속 live(11:19 KST)에서 경로 제공 수/전체 링크 수는 각각361/361, 354/354, 1186/1186, 1187/1187이었다. 이 표본의 전 링크에 경로가 있었지만 향후 응답의 누락 가능성을 없애지는 않는다.
- 최초 live 실행에서 기존 redirect fixture가 암묵적 favicon 요청 때문에1건 실패했다.
  로컬 fixture에 명시적 data favicon을 추가해 실행 환경 차이를 제거했다. redirect 허용 정책·런타임은 바꾸지 않았고
  금지 대상 전송 없음과 허용된 redirect의 정확한 요청 목록을 계속 단언한다. 재실행12개 모두 통과했다.
- b3af6bc의 Python3.11~3.14·typecheck/build·문서 CI가 모두 통과했다. James/Popper 독립 리뷰2건의 잔여 P0/P1/P2는 없다. Transport의 격리 설치본(런타임동일417e3d5)에서 실제 API73도로·경부361경로와375/1440px 지도 렌더/상세 이동을 확인했다. 머지는 별도 승인·통합 단계로 남긴다. API키/제3자지도키를 추출·재사용하지 않았다.
