# PROGRESS

개인 검토용 비공식 분석. 출처 K카(kcar.com). 원본 응답은 `data/raw/`에 두고 커밋하지 않는다.

## 0. 준수 범위 확인 (2026-09-08)

`https://www.kcar.com/robots.txt` (HTTP 200) 확인 결과:

```
User-agent:*
Allow: /
Disallow: /html/  /js/  /pub/  /mp/  /mb/  /cs/csVoc  /account/
Disallow: /bc/LatelyViewedCar/list
Disallow: /car/info/
Disallow: /bc/detail/carInfoDtl?
Disallow: /br/detail/brandCarInfoDtl?
Disallow: /ur/RentDtl?
```

판단:

- 목록/검색 페이지 `\/bc\/search` 는 **Allow** (sitemap.xml에도 priority 0.9로 등재). 목록 수집은 허용 범위.
- 프런트 번들 `\/_nuxt\/*.js` 는 Disallow 목록에 없음 → 엔드포인트 파악 목적의 조회 허용. (`\/js\/` 는 Disallow 이므로 건드리지 않음.)
- **상세 페이지 `\/bc\/detail\/carInfoDtl?` 와 `\/car\/info\/` 는 Disallow.** 따라서 상세 페이지는 **한 건도 요청하지 않았다.** 상세에서만 얻을 수 있는 필드(총 구매비용, 보험 이력, 소유자 변경 횟수, 등록일, 보증)는 `null`로 두고, 사이트에는 상세 링크만 게시한다(링크는 크롤링이 아님).
- `api.kcar.com/robots.txt` 는 404(제한 명시 없음). 이 API는 Allow 대상인 `\/bc\/search` 페이지가 목록을 그리기 위해 호출하는 동일 데이터원이다.
- 요청 예절: 순차 요청만(동시 요청 없음), 간격 1.8초, User-Agent 고정 1개. 403/429/캡차 발생 시 우회 없이 즉시 중단하도록 코드에 구현.

이용약관: kcar.com 이용약관 페이지는 SPA 라우팅이라 정적 HTML에서 본문을 얻지 못했다. 본 작업은 (1) robots.txt 허용 경로만 조회, (2) 개인 구매 검토 목적의 비상업적 분석, (3) 원본 재배포 없음(사진·연락처·원본 JSON 미게시), (4) 분석 표와 K카 상세 링크만 공개 — 로 범위를 제한했다. 상업적 이용 금지 문구를 산출물 전면에 유지한다.

## 1. 마일스톤 1 — API 파악 (완료)

K카는 Nuxt(SSR) SPA이고 `\/bc\/search` HTML에는 매물이 없다(`__NUXT__` 상태에 목록 없음, 클라이언트 페치). 순서대로 해결:

1. `curl`로 `\/bc\/search` HTML → `<script src="\/_nuxt\/*.js">` 9개 수집.
2. 번들에서 `.post("/...")` 문자열을 전부 추출 → B2C 목록 엔드포인트 확정.
3. Playwright는 **불필요**해서 시도하지 않음(1번으로 해결). 시스템 라이브러리 sudo 문제를 피했다.

확정 사항:

| 항목 | 값 |
|---|---|
| 엔드포인트 | `POST https://api.kcar.com/bc/search/list/drct` (K카 직영) |
| 총건수 조회 | 같은 엔드포인트에 `countFlag:true` |
| 페이징 | `pageno`(1-base), `limit`(100까지 확인) |
| 응답 | `data.data.rows[]`, `data.data.totalCnt`, `data.data.totalPageCnt` |
| 인증 | 불필요(비로그인 공개 목록) |

파라미터 인코딩: 요청 본문은 `{"enc": base64(AES-128-CBC(JSON))}`. 키·IV가 프런트 번들에 그대로 하드코딩돼 있다(`setEncDef` → `setEnc(data, "SKFJ2424DasfaJRI", "sfq241sf3dscs321")`, CryptoJS AES/CBC/Pkcs7). 인증·접근제어가 아니라 단순 파라미터 직렬화 포맷이며, 브라우저가 보내는 것과 동일한 요청을 재현한 것이다.

서버측에서 실제로 동작하는 필터(검증 완료, `countFlag`로 건수 비교):

| 파라미터 | 형식 | 확인 |
|---|---|---|
| `wr_lt_prc` | 만원, 상한 | 전체 7,361 → `1300` 적용시 1,969 |
| `wr_gt_mfg_dt` | `YYYYMM`, 하한 | + `201701` → 1,093 |
| `wr_lt_milg` | km, 상한 | + `120000` → **966** |
| `wr_in_mnuftr_nm` | `현대\|기아` | **무시됨**(건수 불변) → 제조사·연료·차종·사고는 응답 필드로 로컬 필터 |

탭 선택: `\/bc\/search\/list\/drct`(직영 7,361대)만 사용. `\/acm`(제휴딜러 749대)·`\/rent`(렌터카)·C2C(`\/api\/v1\/ds\/*`, 개인거래)는 제외 — 지시서의 "K카 진단 기준 사고 이력"과 "렌터카·영업용 제외"에 맞는 건 직영 차량이다.

목록 응답이 이미 84개 필드를 담고 있어 상세 페이지 없이도 지시서 2-2 필드 대부분을 채운다: `carCd, carWhlNm, mnuftrNm, modelGrpNm, modelNm, grdNm, grdDtlNm, mfgDt, prdcnYr, milg, prc, fuelNm, trnsmsnNm, engdispmnt, carctgrNm, acdtHistCnts, optnNm, cntrNm, cntrRgnNm, useNm, rentRegYn, msizeImgPath` 등.

상세 페이지가 Disallow라 채울 수 없는 필드: `total_cost`(K카 표시 총 구매비용), `insurance_history`, `owner_changes`, `listed_date`, `warranty`. → CSV에 `null`. 총 구매비용은 대신 `total_cost_est`(차량가 + 취득세 7% + 매도·이전대행 추정 3만원 단위 보정)를 **추정치로 명시**해 예산 상한 검증에만 쓴다.
