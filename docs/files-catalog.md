# OpenData 일반 파일 발견 사양

2026-10-24 공개 Chromium 조사 기준이다. 파일 목록 발견과 실제 다운로드/무결성 검증은 별도다.
다운로드 구현은 T007, 파일 내용/ZIP 파싱은 T008에서 검증한다. API 키나 인증 API를 쓰지 않는다.

## 공개 메서드

```python
from datetime import date
from krits import KritsClient

async with KritsClient() as client:
    files = await client.list_data_files(
        "event", start_date=date(2026, 10, 22), end_date=date(2026, 10, 23)
    )
    weak = await client.list_data_files("weakSection")
```

`traffic/event/vms`는 양 끝을 포함하는 `date` 범위를 명시한다. 문자열과 datetime은 거부한다.
시작≤종료이며 한 번에 종료일 기준 직전 1년 이내다. 이는 사이트 `checkValidate`의
`compareEnd.setFullYear(endYear-1)`과 같으며 윤일에서 이전 해 3월 1일로 넘어가는 경계도 검증한다.
최소 제공 연도나 미래 조회의 자료 존재 여부는 추정하지 않는다. 미래 날짜도 정상 빈 배열일 수 있다.
`weakSection`은 정적 파일이며 날짜 인자를 거부한다. 소비자가 수집 주기를 소유한다.

결과는 `DataSnapshot[FileAttachment]`이며 출처 URL·UTC 수집 시각·service/기간 또는 static
범위와 `complete=False`를 포함한다. 기간 조회가 전국 모든 자료/배포를 완전히 포함함을 뜻하지 않는다.

## 기간 ZIP 목록

`/opendata/opendataList?service=traffic|event|vms`를 열기 전부터 초기 자동 요청의 401/403/429를
감시한다. 초기 로드의 네트워크가 유휴 상태가 될 때까지 기다리고, 실제 발생한
`/opendata/getTestDataFileList` 응답을 모두 확인한 뒤 달력 입력값을 채우고 조회
버튼을 클릭한다. 초기 제한 뒤 선택200으로 성공하는 경로를 허용하지 않는다.
초기 자동 조회가 없는 경우에도 동작한다. 초기 요청이 반드시 있다고 가정해 응답을 기다리지 않는다.

```json
{"body":{"data":{"searchType":-1,"workingDirectory":"event","startDate":"2026-10-22","endDate":"2026-10-23"}}}
```

`header.state=OK`, `body.data.fileVOList[]`를 요구한다. `body.dataLen=1`은 파일 개수가 아니다.
정상 빈 `[]`와 잘못된 구조/JSON, 제공자 실패, 접근 제한을 서로 구분한다.
응답 ID 목록이 DOM `#data_file_list_result a`에 반영될 때까지 기다리고 다음 필드를 대조한다.

| 원문 | 모델/검증 |
|---|---|
| `fileId` | `file_id`, 비어 있지 않은 문자열·중복 거부 |
| `fileSeq` | 원문은 0 이상 정수, `attachment_id`에는 문자열 `"0"`처럼 보존 |
| `fileStreNm` | `name`, 실제 DOM title과 일치 |
| `dataType` | 선택한 service와 일치 |
| `workingDirectory` | 실제 DOM 다운로드 경로의 연도와 일치 |
| `fileSize` | `size_bytes`, 0 이상 정수, 수신 크기 검증 완료를 의미하지 않음 |
| `fileStrDate` 및 나머지 | `raw`, epoch/수정시각/배포일로 임의 변환하지 않음 |

다운로드 URL은 **DOM href**에서 얻는다. 응답의 내부 경로/저장 파일명으로 임의 URL을 만들지 않는다.
관찰한 경로는 `/opendata/fileDownload/<service>/<연도>/<파일명>`이며 같은 HTTPS ITS origin만
허용한다. 외부 URL·query·fragment·경로 이탈·인코딩된 경로·DOM/응답 불일치는 스키마 오류다.
게시 파일명은 표시용이며 저장 경로를 만드는 데 쓰지 않는다.

실제 2026-10-22~23 조회에서 각 종류 2개를 확인했다. 23일 자료는 소통
`20261023_5Min.zip` 751,694,293 bytes, 돌발 `20261023.zip` 102,937 bytes,
VMS `20261023.zip` 27,284,750 bytes였다. 운영 파일 수/날짜/크기를 불변 상수로 취급하지 않는다.
파일명 `.zip`은 광고된 형식이며 실제 ZIP 중앙 디렉터리/CRC를 T005에서 확인한 것은 아니다.

## 정적 취약구간 파일

`/opendata/opendataList?service=weakSection`에서
`a[href^='/file/opendata/weakSections/']`를 읽는다. 이름 링크와 빈 이름 아이콘 링크가 중복돼
같은 URL로 묶되, 이름이 없는 파일만 있거나 같은 URL의 이름이 충돌하면 오류다.

관찰된 파일은 `행정안전부_상습 결빙구간.csv`와 `안개취약.csv`이며 경로는 각각
`/file/opendata/weakSections/freezingWeakSections.csv`, `.../fogWeakSections.csv`다.
DOM에는 파일 ID·첨부 ID·배포 날짜·바이트 수가 없으므로 `file_id/attachment_id/size_bytes`는
`None`이다. 이름/URL에서 가짜 공식 ID나 배포 날짜를 만들지 않는다.

## 권한과 경계

목록·첨부 링크는 로그인 없이 확인했다. 소통/돌발의 실제 파일 URL에 Chromium HEAD를 보내
200, `application/octet-stream`, 목록과 일치하는 Content-Length 및 첨부 파일명을 확인했다.
HEAD 성공을 전체 전송이나 ZIP 무결성 성공으로 기록하지 않는다. 실제 전송 중 로그인/접근 제한이
있으면 다운로드 단계에서 명시적으로 중단한다. 사이트의 일반 헤더 로그인 링크 존재 자체를
접근 거부로 보지 않는다. 실제 password/CAPTCHA/로그인 제목·리디렉션/401/403/429는 오류다.
쿠키·세션·CSRF 값은 모델/fixture/문서에 저장하지 않는다.
