# 작업 지침

## 목표와 읽기 순서

`python-krits-api`는 ITS 국가교통정보센터의 공개 웹 교통정보와 파일,
표준노드링크 자료실을 키 없이 수집하는 비동기 Python provider다. import 이름은 `krits`다.
작업 전 `CLAUDE.md` → `AGENTS.md` → `SKILL.md` → `docs/architecture/architecture.md` →
`docs/implementation-plan.md` → `docs/tasks.md` → 대상 코드를 읽는다.
사용자 요청이 우선한다. 문서·docstring·유지보수 주석은 한국어로 쓴다.

## 반드시 지킬 개발 순서

1. 원격 기준은 `origin/main` (`https://github.com/digitie/python-krits-api`)이다.
   `main` 직접 push 없이 `codex/` 브랜치와 Draft PR을 쓴다.
2. T001 사양 문서 PR을 먼저 머지하고, 이후 task를 의존 순서대로 구현한다.
3. **각 PR은 서로 독립적인 적대적 리뷰어 2명과 실제 Chromium live E2E를 통과한 뒤에만 머지한다.**
   리뷰어는 별도 에이전트로 실행하며 작성자의 자체 점검으로 대체하지 않는다.
   리뷰 A는 데이터 계약·완전성, 리뷰 B는 자원·파일 무결성·오류·테스트를 공격적으로 검증한다.
4. P0~P2 지적을 수정하고 해당 리뷰어의 재검토를 받는다. 최종 소스 commit에 두 리뷰가
   유효해야 한다. 검증 증빙만 추가한 commit은 리뷰 대상 소스 tree와 SHA를 명시한다.
5. CI 통과·리뷰 결과·live 실행 명령/시각/결과/범위를 PR과 `docs/validation/`에 남긴다.
   실패·skip·외부 장애를 성공으로 기록하지 않는다. live를 못 하면 머지를 보류한다.
6. 머지를 확인한 뒤 `origin/main`에서 다음 task 브랜치를 만든다.
   `docs/tasks.md`, `docs/tasks-done.md`, `docs/journal.md`, `docs/resume.md`를 함께 갱신한다.

## 수집과 데이터 불변 조건

- API 키 생성·입력·환경변수를 요구하지 않는다. `openapi.its.go.kr`의 인증 API를 호출하거나
  웹사이트에 포함된 제3자 지도 키를 추출·재사용하지 않는다.
- Playwright async Chromium에서 공개 페이지를 방문하고 DOM/웹페이지 자체 응답을 수집한다.
  로그인·접근 거부·CAPTCHA·401/403/429를 우회하지 않고 명시적 예외로 중단한다.
- 네트워크는 `await`/`async with`/`async for`만 제공한다. 동기 facade와 Async 접두사 별칭을 만들지 않는다.
- 세션은 지연 생성하며 소유한 자원만 닫는다. 취소·예외에서도 browser/context/page/임시파일을 정리한다.
  공유 `AsyncTokenBucket`과 단일 루프 소유권, 재시도별 요청 예산을 유지한다.
- DOM 변경, 잘못된 JSON, 누락 필드는 정상 빈 목록과 구분한다. 전국 완전 수집을 입증하지
  못한 화면 결과는 조회 범위·시각·출처·완전성 상태와 함께 반환한다.
- 노드/링크/도로/첨부 식별자는 문자열로 보존한다. 시간·CRS·단위는 근거 없이 추정하지 않는다.
  웹페이지와 공식 API가 같은 필드/커버리지를 가진다고 설명하지 않는다.
- 노드링크 ZIP은 원문 보존이 우선이다. 날짜만 보고 기존 버전을 삭제하지 않는다.
  메모리 전체 적재·무제한 압축 해제·원본 파일명 기반 경로 조합을 금지한다.
- provider는 모델·파서·조회·원본 파일 및 manifest를 담당한다.
  주기 스케줄러·서비스 DB·지도 서비스·FastAPI는 소비자가 소유한다.
- 인증 쿠키, 세션 식별자, 브라우저 storage, 제3자 키와 대용량 원본은 커밋하지 않는다.

## 검증

T001은 문서 링크/참조 구조 점검과 공개 페이지의 실제 Chromium 탐색으로 검증한다.
T002부터 아래 게이트를 적용한다. live는 명시적 opt-in이며 기본 테스트는 네트워크가 없다.

```bash
python -m compileall src/krits tests
python -m mypy src/krits
python -m pytest -m "not live" --cov=krits --cov-fail-under=90
python -m pytest -m live --run-live
python -m build
```

상세 리뷰 절차는 `docs/runbooks/hostile-review.md`, live 기준은 `docs/testing.md`를 따른다.
