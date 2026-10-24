# 공개 첨부 다운로드·원본 버전 관리

T007의 공개 API는 `await client.download_file(attachment, store, max_bytes=..., refresh=False)`,
`await store.versions(attachment)`, `await store.current(attachment)`, `await store.verify(stored)`다.
`FileStore(root)`는 명시적인
로컬 보관 경로를 받는다. 다운로드 입력은 목록에서 발견한 `FileAttachment`다.

```python
from datetime import date
from krits import FileStore, KritsClient

async def collect():
    store = FileStore("./its-files")
    async with KritsClient(timeout=600) as client:
        catalog = await client.list_nodelink_releases(
            start_date=date(2026, 1, 1), end_date=date(2026, 10, 24))
        attachment = next(row.history_file for row in catalog.items
                          if row.history_file is not None)
        stored = await client.download_file(attachment, store, max_bytes=10 * 1024 * 1024)
        verified = await store.verify(stored)
        print(verified.path, verified.size_bytes, verified.sha256)
```

예제 날짜는 실제 조회 시점에 맞게 지정한다. 기본 다운로드 상한은1GiB이며 발견 크기가
있으면 전송 전에 확인한다. URL은 HTTPS `www.its.go.kr`의 검증된 노드링크·일반 파일·
취약구간 첨부 경로만 허용한다. query/fragment/외부 origin/포트/인코딩된 경로는 거부한다.
파일명은 표시 메타데이터이며 경로 조합에 사용하지 않는다. redirect는 따라가지 않고 오류로
중단한다. 401/403/429 및 실패는 자동 재시도하지 않는다.

## Chromium 전송과 정리

목록과 동일한 Chromium 세션/공유 토큰 버킷을 사용한다. 이전 문서를 blank로 분리하고
첨부 요청만 허용한다. CDP Request 단계에서 전송 예산을 받은 뒤 response interception을
켜고, 헤더를 검사한 후 `Fetch.takeResponseBodyAsStream`과 최대64KiB의 `IO.read`로 읽는다.
전체 `response.body`, JavaScript ArrayBuffer, `Download.save_as`의 사전 전체 다운로드를
사용하지 않는다. CDP의 [스트림 계약](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)
상 스트림을 가져온 요청은 계속할 수 없어, 성공/실패 모두 소유 page/session을 닫아 종결한다.
외부 주입 context와 그 다른 page는 닫지 않는다.

`Accept-Encoding: identity`를 요청하며 서버가 전송 압축을 적용하면 길이 계약 오류로 중단한다.
Content-Length·발견 bytes가 있으면 실제 수신 길이와 일치해야 한다. 누락된 길이는 실제 수신
bytes 상한으로 제한한다. 빈 파일·과대 청크·HTML/JSON/XML 오류 MIME·본문의 HTML/JSON
시작 표식을 거부한다. 이것은 ZIP/CSV/XLSX 내부 형식 검증이 아니며 T008에서 별도 제공한다.

디스크 작업은 MOIS의 취소 안전 helper로 thread에 위임한다. 청크 쓰기가 끝나기 전에 파일을
지우지 않는다. 마지막에는 fsync 후 임시파일을 다시 해시 검증한다. 취소/실패 시 staging 파일을
지우고 page/CDP/브라우저 소유 자원을 정리한다. 반복 취소에서도 정리를 기다린다.
클라이언트 종료는 진행 중 조회와 다운로드의 로컬 publish까지 기다린다.
timeout은 client의 operation 제한이며 대용량 전송 시 소비자가 충분한 값을 명시한다.

## 불변 원본과 manifest

```text
root/
  staging/download-<무작위>.part
  objects/<SHA 앞2자리>/<SHA256>
  manifests/<첨부 identity SHA256>/<원본 SHA256>.json
  current/<첨부 identity SHA256>.json
```

identity는 서비스·자료 ID·첨부 ID·URL의 해시다. 원본 이름·날짜로 파일을 삭제하거나 덮지 않는다.
원본과 manifest는 같은 파일시스템의 hard link 생성으로 원자적으로 공개한다. hard link가
지원되는 로컬 파일시스템이 필요하다. 이미 존재하면 bytes/hash를 검증하며 손상본을 덮지 않는다.
서로 다른 저장소 인스턴스가 같은 내용을 동시에 저장해도 최초 정상 manifest 하나를 재사용한다.
전원 장애에 대한 파일시스템 전체의 내구성을 보장하는 저널/DB는 제공하지 않는다.

manifest v1에는 `status=verified`, 첨부 서비스/문자열ID/원본이름/발견URL/선택적 발견bytes,
수신bytes, SHA-256, 수집 UTC, MIME, `format_validation=not_checked`를 저장한다.
verified는 전송/로컬 크기·해시 검증을 뜻한다. 제공자 기준일은 수집 UTC로 대체하지 않으며,
의미가 검증되지 않은 원문 날짜를 기준일로 추정하지 않는다. 첨부의 `raw`는 키·세션성 필드
혼입 방지를 위해 manifest에 복사하지 않는다. 원문 카탈로그 설명/부분 배포 범위는 조회 결과와
함께 소비자가 보존한다. 원본의 형식·CRS·인코딩·전국 완전성을 manifest가 입증하지 않는다.

`versions`는 모든 manifest의 구조·identity·경로·크기·원본 hash를 재검증하고 수집시각 순으로
반환한다. 64KiB 초과 manifest, 첨부별1만개 초과, 알 수 없는 경로·심볼릭 링크·손상은 명시적
`KritsIntegrityError`다. 이전 버전이 누락·손상돼도 조용히 건너뛰지 않는다.

manifest 임시파일과 current 포인터 임시파일도 staging에만 작성한다. 공개 디렉터리의 조회가
정상 진행 중 임시파일을 손상으로 오판하지 않는다. 중단된 staging 잔여는 버전으로 취급하지 않는다.

기본 재실행은 메타데이터가 같고 마지막 성공 전송으로 선택된 보관본을 재검증해 반환하므로
ITS 전송은0회다. 불변 manifest의 `collected_at`은 내용의 최초 수집시각이고, current 포인터는
별도 `observed_at`과 마지막 공개 SHA를 원자 replace로 기록한다. A→B→A 복원 시 버전은2개를
유지하면서 current는A를 선택한다. 동시 publish에서는 마지막으로 포인터 공개를 완료한 성공
관찰이 선택된다. 포인터가 없으면 과거 버전을 현재로 추정하지 않고 새 전송을 수행한다.
Windows의 동시 파일 handle 때문에 원자 replace가 잠시 거부되면 파일 worker에서 최대190ms
재시도한다. 계속 거부되면 저장 실패이며 이전 포인터를 유지한다. 네트워크 재시도는 하지 않는다.
`refresh=True`는 명시적 새 전송으로 같은 URL/메타데이터의 내용 교체 여부를 확인한다.
해시가 같으면 최초 버전을 재사용하고, 바뀌면 새 hash manifest를 추가해 이전 정상본을 유지한다.
보관본 재사용은 원격 파일이 바뀌지 않았다는 주장이 아니다. ETag/Range/조건부 재개는 현재
사용하지 않는다. 원본 공개 후 manifest 실패 시 고아 원본이 남을 수 있으며, 재전송 때 해시를
검증해 재사용하고 manifest를 완성한다. 자동 정리로 원본을 삭제하지 않는다.
원자 publish 직후 취소되면 정상 버전이 이미 생겼을 수 있으므로 `versions`로 재확인한다.

서비스 DB·스케줄러·보관 기한 정책은 소비자의 책임이다. S3는 T008의 별도 선택 기능이다.
