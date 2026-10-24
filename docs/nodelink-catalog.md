# 표준노드링크 자료실 계약

## 기간 조회와 모델

`await client.list_nodelink_releases(start_date=date(...), end_date=date(...))`는
`/nodelink/nodelinkRef`를 열고 달력에 두 날짜를 입력해 실제 조회 버튼을 클릭한다.
날짜는 양 끝을 포함하고 종료일 기준 1년 이내다. 연속 여러 해를 조회하는 스케줄링은 소비자가
범위를 나눠 수행한다. 클라이언트가 숨겨진 전체 기간 요청을 생성하지 않는다.

```json
{"body":{"data":{"searchType":-1,"workingDirectory":"/nodeLink","startDate":"2025-10-24","endDate":"2026-10-24"}}}
```

같은 `/opendata/getNodeLinkDataFileList`의 초기 자동 응답도 탐색 전부터 관찰해 접근/호출 제한과
형식을 확인한다. 이후 응답의 첨부 ID 순서가 실제 DOM `#data_file_list_result a.down`에 반영될
때까지 기다린다. DOM의 표시 크기 span을 제거한 파일명, title 첨부번호, id, href를 교차 검증한다.
잘못된 JSON/필드 누락/중복 ID/DOM 불일치는 오류이며 명시적인 빈 `fileVOList=[]`만 빈 목록이다.

`DataSnapshot[NodeLinkRelease]`에 출처·수집 UTC·기간·`complete=False`를 포함한다.
`NodeLinkRelease`는 다음 식별자를 분리한다.

| 원문 | 모델 | 의미 |
|---|---|---|
| `seq` | `release_id` | 자료실 배포/게시 ID |
| `atchFileId` | `attachment_group_id`, 첨부 `file_id` | 실제 첨부 그룹 ID |
| `nodeFileSeq` | `data_file.attachment_id` | 원본 ZIP 첨부번호 |
| `histFileSeq` | `history_file.attachment_id` | 변경 내역서 첨부번호 |
| `updtCn` | `description` | 배포 설명·주의사항 원문 |
| `regDt/registDt`, 나머지 | `raw` | 시각 의미/시간대 추정 없이 보존 |

ID는 문자열이다. `atchFileId`를 `DF_`와 `seq`의 조합으로 만들지 않는다. 첨부번호도 0/1로
고정하지 않는다. 실제 최근 기간에 `DF_211`의 node=5/hist=6, `DF_210`의 node=1/hist=2를 확인했다.
DOM href `/opendata/nodelinkFileSDownload/<atchFileId>/<fileSeq>` 자체를 사용하며
그룹/번호를 응답과 대조한다. 내부 저장 경로·UUID·원본 이름으로 URL이나 로컬 경로를 만들지 않는다.

## 파일과 배포 범위

노드 원본과 내역서는 별도 `FileAttachment`다. ZIP뿐 아니라 CSV/XLSX 내역서도 그대로 발견한다.
`nodeFileMg/histFileMg`는 반올림 표시 MB이므로 곱해서 정확한 bytes를 만들지 않는다.
`size_bytes=None`이며 표시 크기는 raw에 남는다. 형식은 광고된 확장자일 뿐 내용 확인이 아니다.

첨부 관련 필드가 모두 존재하고 이름/확장자/번호가 명시적으로 null인 경우에만
`data_file/history_file=None`을 허용한다. 필드 자체가 사라지거나 이름은 없는데 번호/확장자가
남거나 번호가 충돌하면 오류다. 배포 하나에는 적어도 한 첨부가 있어야 한다.

2026-10-24 조사에서 2025-10-24~2026-10-24는 10배포20첨부였다. 2024년 범위는 7배포로
내역서가 없는 배포도 있었다. 예를 들어 2024-12-27 배포는 구리~안성 개통 구간만 담은
긴급 배포라고 **설명에 명시**돼 있다. 날짜가 최신이라는 이유로 전국 자료나 권장 버전이라고
해석하지 않는다. 2025년 변경 공지와 개별 설명을 소비자가 함께 확인해야 한다.

## 관찰 차이

`compare_nodelink_catalogs(before, after)`는 I/O 없는 순수 함수다. 동일 출처와 동일 기간만
비교해 `added_ids/missing_ids/changed_ids`를 반환한다. 목록 순번 `rowSeq`만 바뀐 것은 무시하며
설명·첨부 ID/번호/이름/URL과 원시 메타데이터 변경을 탐지한다. 배포 ID 중복은 오류다.

`missing`은 이번 관찰에 없다는 뜻이며 삭제·폐기 증거가 아니다. 이전 snapshot/원본을 수정하거나
삭제하지 않는다. 같은 ID/URL의 파일이 내용만 바뀌고 메타데이터가 같으면 목록 단계에서 탐지할
수 없다. T007의 실제 SHA-256 다운로드/manifest가 그 버전 차이를 담당한다. 조회 기간이 다른
목록을 비교해 과거 배포가 삭제됐다고 판정하지 않는다.

## 검증 범위

현재/2025년 XLSX 포함/2024년 내역서 없는 배포/정상 빈 기간을 실제 Chromium에서 확인한다.
기간을 고정한 역사 조회는 해당 광고 형식의 존재 확인용이며 최신 배포 ID·건수를 상수로 보장하지
않는다. 원본 전송·ZIP 내부·CRS·인코딩·CRC는 T007/T008/T010에서 별도 검증한다.
