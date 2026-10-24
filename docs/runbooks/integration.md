# 설치본·전체 ZIP 통합 검증

기본 오프라인 검사는 외부 네트워크를 쓰지 않는다. `--run-live`는 실제 ITS/Chromium,
`--run-large-files`는 전체 ZIP 전송/검사의 별도 opt-in이다. 전체 게이트에서 skip은 성공이 아니다.
최신 배포 ZIP 원문 전체를 검사한다는 의미이며 전국 링크 누락이 없다는 검증은 아니다.

## 전체 live

PowerShell 예다. 대용량 원본은 Git 저장소 밖 보관소에 한 번 내려받고 이후 hash를 검증해 재사용한다.
원본 파일명으로 저장 경로를 만들거나 자동 압축 해제하지 않는다.

```powershell
$env:KRITS_CHROMIUM_EXECUTABLE='C:\path\to\chrome.exe'
python -m pytest -m live --run-live --run-large-files --file-store F:\dev\_data\krits -s
```

`--run-large-files`만 주고 `--file-store`를 생략하거나 저장소 내부를 지정하면 실패한다.
카탈로그는 최근300일, 선택은 화면 첫 배포의 NODELINKDATA.zip이다. 날짜/ID를 상수로 고정하지 않는다.
첨부 없음·이름/형식 변경은 실패다. 전송 기본1GiB, ZIP 항목10,000/중앙 디렉터리8MiB,
개별2GiB/총6GiB/압축비200 상한을 명시한다. 실제 bytes·CRC·SHA256·원문 prj/cpg·항목 목록을
검사하고 재실행에서 Chromium operation이 발생하지 않음을 확인한다. 모든 배포를 자동 삭제/교체하지 않는다.

## wheel 격리 설치본

새로운 빈 target 디렉터리를 사용한다. 예시 이름의 SHA는 실제 소스 commit으로 바꾼다.
기존 target에 덮어 설치하면 이전 파일이 남을 수 있으므로 새 경로를 쓴다.

```powershell
python -m build
python -m pip install --no-deps --target C:\Temp\krits-wheel-SHA dist\python_krits_api-0.1.0-py3-none-any.whl
python -I tools\installed_e2e.py --package-root C:\Temp\krits-wheel-SHA --file-store F:\dev\_data\krits --chromium C:\path\to\chrome.exe --run-live --run-large-files --history-encoding cp949
```

`--no-deps`이므로 Playwright/defusedxml과 Chromium은 검증 환경에 먼저 설치돼 있어야 한다.
도구는 wheel target을 import 경로 맨 앞에 두고 실제 `krits.__file__`과 distribution 위치를 확인한다.
`-I`는 PYTHONPATH/사용자 site의 `.pth` 처리를 제외한다. 의존 패키지 탐색에만 사용자 site 경로를
뒤에 추가하며 저장소의 editable `.pth`를 실행하지 않는다. target은 저장소 밖에 있어야 한다.

진단·도로/소통·돌발·CCTV·우회·소요시간·VMS·재난구역·일반 파일/자료실을 호출하고,
작은 내역서 원본의 다운로드·형식 읽기·재검증/재사용을 확인한다. CP949는 현재 실제 CSV에서
검증한 인코딩으로 명시 지정한다. 이후 파일이 바뀌면 근거를 다시 확인해 인자를 바꿔야 한다.
전체 ZIP은 선행 pytest로 수집된 current 버전만 재사용해 추가 대용량 전송을 하지 않는다.
설치본에서도 CRC·메타데이터와 같은 원본 SHA를 확인한다.

외부 S3 계정은 제공되지 않았으므로 전체 live의 S3 검증은 localhost 독립 서명 HTTP 계약이다.
실제 AWS/MinIO 운영 계정·버킷·자격증명·PyPI 게시·운영 배포는 이 게이트의 범위가 아니다.
