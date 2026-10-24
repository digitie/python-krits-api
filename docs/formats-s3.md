# 형식 검사·선택 읽기·S3 원본 보관

T008은 다운로드 manifest를 유지하면서 원본을 검증하고 별도 불변 보고서를 추가한다.
네트워크 없는 검사/파싱도 async 함수이며 파일 작업은 취소 안전 worker에서 수행한다.
`FileStore.verify`로 원본을 검사 전후 재검증한다. 압축을 디스크에 풀지 않는다.

## API와 제한

```python
from krits import FileLimits, inspect_file, read_csv, read_xlsx

async def examine(store, stored):
    report = await inspect_file(store, stored)
    print(report.kind, report.crc_checked, report.report_path)
    # ZIP의 실제 멤버 이름을 선택한다. 원본/첨부 파일명으로 경로를 합성하지 않는다.
    table = await read_csv(store, stored, member="data/links.csv", encoding="cp949")
    print(table.rows, table.row_numbers)

async def history(store, xlsx):
    table = await read_xlsx(store, xlsx)  # 기본은 첫 sheet, sheet_name으로 선택 가능
    print(table.sheet_name, table.rows, table.formulas)
```

`FileLimits` 기본값은 원본1GiB, 항목1만개, central directory8MiB, 멤버512MiB,
총 해제2GiB, 압축비200, prj/cpg 원문 합계1MiB다. 표 읽기는 입력16MiB,
1만행·1024열·셀131072문자로 제한한다. 소비자가 명시적으로 조정할 수 있으며 초과는
부분 성공으로 숨기지 않고 `KritsIntegrityError`다. CPU/파일 worker의 취소는 현재 검사가
끝나기를 기다리므로 이 상한에 맞는 실행 예산을 잡는다.

ZIP은 `ZipFile` 객체를 만들기 전에 EOCD·central directory 길이와 실제 항목 수를 제한한다.
경로는 원문 바이트에서 검사해 Windows의 separator 정규화 전에도 이탈을 막는다.
절대/드라이브/역슬래시/빈 segment/점·상위 segment/NUL, 대소문자 중복,
심볼릭 링크·특수 파일·암호화와 크기·압축비 상한 초과를 거부한다.
지원 압축은 stored/deflate이며 다중 디스크와 ZIP64 EOCD는 현재 명시적 미지원이다.
central directory는 EOCD 바로 앞의 정확한 선언 위치여야 한다. 다른 영역을 읽게 만드는
concat offset 보정·directory와 EOCD 사이의 미지원 추가 레코드는 거부한다.
일반 EOCD의 sentinel 값이 없어도 직전 ZIP64 locator는 선제 거부한다. 표준 zipfile이
별도 ZIP64 directory로 교체해 사전검사와 다른 영역을 읽는 우회를 허용하지 않는다.
ZIP64 멤버의 크기 표현은 EOCD가 일반 형식이고 모든 상한을 만족하면 표준 zipfile이 처리한다.
ZIP 안의 모든 멤버를64KiB씩 EOF까지 읽어 선언 길이와 CRC를 확인한다.
[Python zipfile](https://docs.python.org/3/library/zipfile.html)의 CRC 검사를 사용하되
사전 크기/경로 검사와 실제 읽기 상한을 추가했다.

`.prj`/`.cpg`는 멤버별64KiB 이내 원문 bytes를 `ArchiveMetadata`로 보존한다.
CRS를 지정하거나 좌표를 변환하지 않고 `.cpg`도 자동 인코딩 선택에 쓰지 않는다.
CSV는 `encoding=`을 명시해야 한다. UTF-8/CP949 등을 조용히 fallback하지 않으며
strict decoding·CSV 구문 검사를 한다. 모든 값은 문자열이고 선행0을 보존한다.
헤더·날짜·숫자·ID의 의미를 추정하지 않으며 행/열 순서와 빈 셀을 유지한다.
표준 csv의 기본 field 상한보다 큰 셀은 추가 제한에 걸릴 수 있다. 전역 field 설정을 바꾸지 않는다.

XLSX는 package CRC를 먼저 검사하고 선택 sheet의 저장 셀 값과 수식 원문을 분리한다.
숫자/date serial·boolean 등은 XML 원시 문자열이며 표시 서식으로 날짜나 ID를 복구하지 않는다.
수식은 계산하지 않고, 저장 cached 값이 없으면 None이다. 비어 있는 행/열 좌표를 임의로
1백만행까지 확장하지 않으며 `row_numbers`로 원래 행 번호를 보존한다.
공유 문자열·inline 문자열을 읽고, 외부 relationship·경로 이탈·DTD/entity는 거부한다.
XML은 [defusedxml](https://pypi.org/project/defusedxml/)의 명시적 DTD/entity/외부 참조 금지로
파싱한다. 현재 지원 namespace는 ECMA transitional SpreadsheetML이며 다른 namespace,
sheet/row/cell 필수 구조 누락과 손상은 오류다. 병합 셀·계산·스타일/매크로 실행을 제공하지 않는다.
정상 빈 `<sheetData/>`와 필수 컨테이너 누락·중복·내부 namespace 변경은 구분한다.
공유 문자열의 본문 t/r와 별도 발음 주석 rPh를 합치지 않는다.
[Open XML 문자열 구조](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.sharedstringitem)
상의 본문 문자열만 반환한다.

검사 결과는 `inspections/<원본SHA>/<보고서SHA>.json`에 원자 공개한다. 원본 SHA,
검사 UTC, kind, CRC 여부, 멤버 길이/CRC, prj/cpg base64 원문, 적용 상한,
선택 표의 encoding/member/행 수를 남긴다. `FileInspection.report_path`로 찾는다.
원본의 `format_validation=not_checked` 다운로드 manifest는 최초 전송 기록으로 보존한다.
보고서가 해당 SHA의 후속 검사 근거다. ZIP 검사만으로 내부 셰이프파일의 의미·전국 범위나
CRS 적합성을 입증하지 않는다.

## 선택 S3

```bash
python -m pip install 'python-krits-api[s3]'
```

```python
from krits.s3 import S3Config, S3Store

async def archive(store, stored, endpoint, bucket, access_key, secret_key):
    config = S3Config(endpoint, bucket, access_key, secret_key, region="us-east-1")
    async with S3Store(config) as remote:
        obj = await remote.put_file(store, stored)
        print(obj.bucket, obj.key, obj.sha256)
```

S3 자격정보는 소비자의 객체 저장소용이며 ITS 인증키와 무관하다. 기본 기능에서 요구하거나
자동 탐색하지 않는다. endpoint/bucket/자격정보를 명시하고 bucket은 미리 준비한다.
환경변수·기본 credential chain·프록시를 자동 탐색하지 않고 TLS 검증을 유지한다.
HTTP는 `allow_http=True`와 literal loopback/localhost일 때만 허용한다.
endpoint query/userinfo/path와 안전하지 않은 prefix는 거부한다. 자격정보는 repr에서 제외한다.

원본을 로컬 재검증한 뒤 `<prefix>/objects/<SHA 앞2자리>/<SHA>`에 signed PUT하고,
동일 객체를 실제 GET하여 수신 크기와 SHA-256을 다시 비교한다. ETag를 hash로 해석하지 않는다.
64KiB 청크·비동기 HTTPX와 같은 루프의 공유 `AsyncTokenBucket`을 사용한다.
각 PUT/GET은 토큰을 쓰며 redirect·자동 재시도는 없다. 401/403/429는 즉시 오류다.
GET은 로컬 원본 크기를 상한으로 삼고 전송 압축을 거부한다. 오류 본문은 메모리에 적재하지 않는다.
종료의 lock 대기부터 소유 HTTP client 정리까지 추적하고 반복 취소에도 끝까지 정리한 뒤 전파한다.
로컬 원본/manifest/검사 보고서는 그대로 유지한다. 이 API는 S3에 원본 객체를 보관하며
로컬 manifest나 mutable current 포인터의 동기화/서비스 DB·수명 정책은 소비자가 담당한다.

서명은 MOIS의 canonical header/HMAC 구조를 적용했고 NOTICE에 MIT 출처를 남겼다.
[AWS 공식 SigV4 예제](https://docs.aws.amazon.com/AmazonS3/latest/developerguide/sig-v4-header-based-auth.html)의
GET 검증 벡터와 일치한다. 요청/응답은 [HTTPX async streaming](https://www.python-httpx.org/async/)을 쓴다.
초기 실제 HTTP 검증은 localhost의 독립 서명 검사 서버에서 PUT→GET·손상 검출로 수행했다.
운영 AWS/MinIO endpoint의 정책·TLS·서명 호환은 소비자가 해당 endpoint로 별도 검증한다.
