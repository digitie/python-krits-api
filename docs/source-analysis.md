# ITS 공개 데이터 사양 조사

조사일: 2026-10-24 KST. 실제 Chromium 149에서 로그인·API 키 없이 탐색했다.
공식 설명의 필드 계약과 웹페이지 응답의 관찰 사실을 분리한다.
API 성공 응답을 호출해 검증한 문서가 아니다.

## 출처와 범위

- [오픈데이터 소개](https://www.its.go.kr/opendata/intro): 12개 서비스 항목.
- [공식 매뉴얼](https://www.its.go.kr/file/opendata/openapi_manual.pdf): 참고 문서.
  이번 계약 조사는 아래 서비스별 현재 화면을 기준으로 한다.
- [교통정보](https://www.its.go.kr/map/traffic), [돌발정보](https://www.its.go.kr/map/outbreak),
  [CCTV](https://www.its.go.kr/map/cctv), [우회도로](https://www.its.go.kr/map/detour),
  [도시간 소요시간](https://www.its.go.kr/map/travelTime): 키 없는 공개 웹 기능.
- [노드링크 자료실](https://www.its.go.kr/nodelink/nodelinkRef): 공개 배포 파일·내역서.

API 공개 사양은 `apiKey`를 필수로 요구한다. 사용자 요구에 따라 키를 받지 않으며
인증 Open API는 호출 대상에서 제외한다. 웹페이지의 XHR은 사이트 내부 인터페이스라
변경 가능성이 있다. 실제 필드/조회 범위가 확인된 기능부터 제공한다.

## 전체 기능 대응표

모든 API는 `apiKey`와 `getType`을 요구한다. 아래 필수/선택 조건은 공식 화면의 내용이며
향후 Python 메서드 인자가 아니다. bbox는 `minX,maxX,minY,maxY`다.

| 서비스/공식 사양 | 공식 요청 조건 | 핵심 출력 | 키 없는 대응 및 확인 단계 |
|---|---|---|---|
| [traffic](https://www.its.go.kr/opendata/opendataList?service=traffic) | `type=all/ex/its`; all 외에는 `routeNo,drcType`; 조건부 bbox | `linkId,startNodeId,endNodeId,roadName,roadDrcType,linkNo,speed,travelTime,createdDate` | 교통 화면의 노선·방향별 구간 목록. T003에서 실제 링크/단위 검증 |
| [event](https://www.its.go.kr/opendata/opendataList?service=event) | `type=all/ex/its/loc/sgg/etc`, `eventType=all/cor/acc/wea/ete/dis/etc`, 선택 bbox | `type,eventType,eventDetailType,startDate,endDate,coordX,coordY,linkId,roadName,roadNo,roadDrcType,lanesBlockType,lanesBlocked,message` | 돌발 화면의 HIGHWAY/NATIONAL GeoJSON 확인. 공식 도로 전체와 같다고 보장하지 않음 |
| [cctv](https://www.its.go.kr/opendata/opendataList?service=cctv) | `type=ex/its`, `cctvType=1..5`, 필수 bbox | `coordtype,datacount,roadsectionid,filecreatetime,cctvtype,cctvurl,cctvresolution,coordx,coordy,cctvformat,cctvname` | 공개 CCTV 검색 UI와 `/map/getCctvSearch` 발견. 메타데이터 T004; 스트림 다운로드 제외 |
| [fcTraffic](https://www.its.go.kr/opendata/opendataList?service=fcTraffic) | `sectionId,fCastDate,fCastHour` | `fcastDate,fcastHour,linkId,sectionId,sectionType,detourId,length,speed` | 우회 화면은 존재. 미래 예측의 동일 제공 여부 미확정, T009 |
| [detectorInfo](https://www.its.go.kr/opendata/opendataList?service=detectorInfo) | 공통 인자만 | `vdsId,linkIds,laneNo,colctedDate,speed,volume,occupancy` | 전용 공개 화면/전국 검지 데이터 미확정, T009 |
| [vms](https://www.its.go.kr/opendata/opendataList?service=vms) | 공통 인자만 | `vmsId,messageNo,message,createdDate,coordX,coordY,roadGrad,roadName,routeNo,roadDrcType` | 지도 VMS 레이어와 Data File 안내. 표시 순서 보존, T005/T009 |
| [safeDriving](https://www.its.go.kr/opendata/opendataList?service=safeDriving) | 필수 bbox | `message,stepType,outbrkType,priority,routeName,routeNo,roadDrcType,startStdLinkId,startX,startY,revRouteName,revRouteNo,revRoadDrcType,revStdLinkId,revX,revY,occrrncId` | 동일 문안/우선순위 대응 미확정, T009 |
| [vsl](https://www.its.go.kr/opendata/opendataList?service=vsl) | 공통 인자만 | `vslId,sectionCode,createdDate,limitSpeed,defLmtSpeed,roadNo,linkId,coordX,coordY,registedDate` | 키 없는 제한속도 현재값 대응 미확정, T009 |
| [weakSection](https://www.its.go.kr/opendata/opendataList?service=weakSection) | API 없음, 파일 | 상습 결빙·안개 취약 CSV | 두 CSV 링크 확인, 다운로드/인코딩 T005/T007 |
| [nodelink](https://www.its.go.kr/opendata/opendataList?service=nodelink) | API 없음, 날짜별 파일 | 전국 노드링크 ZIP, 배포별 내역서 CSV/XLSX | 실제 목록·첨부 확인. T006/T007 |
| [dangerousCarInfo](https://www.its.go.kr/opendata/opendataList?service=dangerousCarInfo) | 공통 인자만 | `streDt,sntcManageNo,acdntOccrrncDt,acdntAt,acdntEndAt,updtDt,xcrdnt,ycrdnt` | 공개 돌발과 동일하다고 가정하지 않음, T009 |
| [disaster](https://www.its.go.kr/opendata/opendataList?service=disaster) | `category=D,eventType=all/D03/D04/D06/D07,startDate,endDate`, 선택 bbox | `eventId,category,eventType,eventDetailType,status,startDate,socName,socExtent,LocationInfoType,LocationInfo,linkId,roadName,roadNo,roadDrcType,lanesBlockType,lanesBlocked,message,endDate` | 돌발 화면 DISASTER 분기 발견. 현재 화면과 과거 기간 API의 차이 T009 |

공식 공통 envelope는 `header.resultCode/resultMsg`, `body.totalCount/items` 계열이다.
성공은 `0/SUCCESS`, 안내 오류는 `4001` 제한, `4002` 인자, `4004` 페이지,
`4005` 키, `4009` 시스템이다. 이를 웹 응답의 `header.state`와 혼동하지 않는다.
공식 문서의 속도 단위에 `시/km` 표기가 있으나 웹 화면은 `km/h`다.
필드 이름만으로 단위를 단정하지 않고 실제 표시와 대조한다. `travelTime`은 공식 초 단위다.
시각 문자열의 timezone은 확인 전 임의로 지정하지 않는다.

## Chromium에서 관찰한 웹 계약

| 화면/요청 | 관찰 결과 | 구현 전 추가 확인 |
|---|---|---|
| `/map/traffic` | 고속도로/국도 노선과 방향 목록, 속도 요약 표시 | 구간 확장 클릭 후 링크별 필드·방향·누락 여부 |
| `/map/getTrafficSearch` | JS는 `{searchKeyword: query}`를 전송하고 검색 목록을 렌더링 | 응답의 `roadId,id,drct,routeTy` 실제 타입/빈 결과 |
| `/map/getMarkers` | POST `{"body":{"data":{"type":"","keyword":""}}}`; HIGHWAY/NATIONAL GeoJSON와 properties.INFO JSON 문자열 관찰 | bbox/현재 화면과 독립인 범위, DISASTER 별도 schema |
| 돌발 INFO | `outbrkId,outbrkTy,outbrkTyNm,occrrncLinkId,roadNm,roadNo,roadDrcTy,x,y,mssageCn,occrrncTm,registDt,edDt` | timestamp 숫자는 epoch 밀리초로 보이지만 명시적 대조 전 raw 보존 |
| `/map/getCityReqTimeByGroup` | `header.state=OK`, `body.data.COURSE[]`: `GRPID,GRPCOURSNM,BSPOTNM,ESPOTNM,REQRETIME` | 소요시간 표시와 수치의 분/초 단위 대조 |
| `/map/getCityList` | 지역 코드와 경계가 있는 cityInfo | ITS 코드와 행정구역 코드를 동일시하지 않음 |
| `/map/getMainToDetourRoads`, `/map/getMainToDetourSectionsByRoad`, `/map/getMainToDetourSection` | 우회 화면 JS에서 경로 발견 | 실제 성공 payload와 예측 지원 여부 |

웹 envelope와 GeoJSON은 서로 다르다. 모든 응답에 동일 envelope를 강제하지 않는다.
페이지 전체 텍스트에는 숨김 모달의 예시 데이터도 포함된다. 모달 샘플을 실제 재난으로 수집하지 않는다.
파서는 화면 렌더링에 쓰인 응답이나 검증된 목록 컨테이너만 사용한다.

## 공개 파일 사양

| 자료 | 현재 화면에서 관찰 | 관리 사양 |
|---|---|---|
| 소통 | 2019-03 이후 안내, 예: `20261023_5Min.zip` 약 717MB; 생성일·생성시분·링크ID·도로관리기관·속도·시간 | 일자·5분 집계 의미 보존, 네트워크/파일 단위 상한 필요 |
| 돌발 | Data File 안내 있음 | 날짜 범위·실제 형식·본문 컬럼은 T005에서 검증 |
| VMS | Data File 안내 있음 | 표출 순서·시각·ID를 보존; 파일 계약 T005 |
| 취약구간 | `행정안전부_상습 결빙구간.csv`, `안개취약.csv` | 헤더·인코딩·CRS/좌표 확인 후 typed 파서 |
| 표준노드링크 | 2008-11 이후 안내, 한 번에 1년 조회, ZIP+배포 내역서 | 대용량 원문·변경 내역·과거 배포를 독립 보관 |

노드링크 자료실과 OpenData nodelink는 같은 파일 목록 UI를 사용했다.
`/js/opendata/nodelinkService.js`는 `/opendata/getNodeLinkDataFileList`로
`body.data={searchType:-1,workingDirectory:"/nodeLink",startDate,endDate}`를 보낸다.
응답은 `header.state=OK`, `body.data.fileVOList[]`를 가진다.
목록의 `seq`와 `nodeFileSeq`/`histFileSeq`를 문자열로 보존한다.
첨부 URL은 `/opendata/nodelinkFileSDownload/DF_<seq>/<fileSeq>`다.
첨부 번호를 0/1로 고정하면 안 된다. 2026-06 배포에서는 ZIP=5, 내역서=6도 관찰했다.

조사 시 최근 1년 목록은 10배포·20첨부였다. 최신은 `DF_221`의
`[2026-10-14]NODELINKDATA.zip`(표시 258.83MB), 내역서는 CSV다.
이전 배포 내역서는 XLSX도 있다. 표시 MB는 실제 bytes/Content-Length가 아니다.
서버 내부 저장 경로나 저장 파일명은 다운로드 URL을 추정하는 데 쓰지 않는다.
ZIP 내부 파일·CRS·인코딩·CRC·전체 바이트 수는 아직 미검증이다.

## 다운로드와 관리 상세 계약

T007 기본 다운로드 상한은 명시적으로 설정하고 1GiB를 초기값 후보로 둔다.
상한은 Content-Length뿐 아니라 실제 수신 bytes에도 적용한다. 게시글 파일명은 표시용이며
저장 경로는 검증한 자료 ID/첨부 ID/해시에서 만든다. 응답이 HTML/로그인/오류면 실패한다.
이동 대상은 허용된 ITS HTTPS 경로만 수용하고 인증·외부 호스트 전달을 금지한다.

임시 파일 → 전송 완료 → 형식/길이/해시 → immutable 원본 → 원자 manifest 순서로 공개한다.
동일 자료 ID에 내용이 바뀌면 새 SHA-256 버전으로 추가한다. 원본 공개 후 manifest 갱신에
실패한 고아 파일은 다음 실행에서 재검증 후 복구하거나 명시적으로 보고한다.
재실행에서 URL/날짜만 보고 다운로드 완료로 믿지 않고 로컬 파일 hash를 검증한다.
ETag/Last-Modified는 서버가 실제 제공하는 경우에만 조건부 재검증에 사용한다.
부분 파일 재개는 Range/ETag 계약이 확인되기 전 구현하지 않는다.

ZIP 원문은 자동 해제하지 않는다. 필요 시 멤버 경로·파일 개수·개별/총 해제 크기·압축비·CRC를
검증한 뒤 선택 파일만 파싱한다. `.prj`와 `.cpg`는 내용의 일부이며 버리지 않는다.
S3 연동은 T008에서 별도 선택 기능으로 두고 라이브러리에 비밀값 자동 탐색을 넣지 않는다.

## 조사 한계와 다음 검증

공식 API 성공 응답, 전체 ZIP 전송, 파일별 encoding/CRS는 검증하지 않았다.
초기 Playwright 설치본이 요구한 Chromium 다운로드는 환경에서 timeout됐으나 기존 설치된
Chromium 실행 파일로 실제 페이지 탐색은 성공했다. TLS 검증을 끄지 않고 browser fetch를 사용했다.
원문 페이지에는 쿠키·제3자 지도 키가 들어갈 수 있으므로 전체 HTML·HAR·storageState를 커밋하지 않는다.
재현 가능한 정제된 조사 스크립트와 요약 증빙을 문서 PR에 추가한다.
