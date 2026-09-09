# kcar-deals

K카(kcar.com) 직영 국산 중고차 매물을 수집해 같은 세대·연식 그룹의 시세와 비교하고 "꿀매물" 점수를 매기는 개인 프로젝트.

- 사이트: **https://inh1095.github.io/kcar-deals/**
- 리포트 전문: [`docs/report.md`](docs/report.md) · 진행 기록: [`PROGRESS.md`](PROGRESS.md) · 작업 지시서: [`WORKORDER.md`](WORKORDER.md)

## 실행

```bash
pip install --user requests pycryptodome                 # 의존성 2개
python3.11 search_kcar.py --out data/listings.csv        # 직영 재고 전체 수집 + 시세비교
python3.11 build_report.py                               # docs/report.md + docs/index.html
```

검증은 `python3.11 verify.py` (TOP 15 중 3대 재조회 대조 + 사이트 규칙 검사).
네트워크 요청 없이 점수만 다시 계산하려면 `--use-cache` (원본은 `data/raw/pages/`).

## 조건 바꾸기

`search_kcar.py` 인자로 바꾼다.

```bash
python3.11 search_kcar.py --budget 1500 --year 2019 --km 90000 --seats 5 --fuel hybrid,gasoline
python3.11 build_report.py
```

| 인자 | 뜻 | 기본값 |
|---|---|---|
| `--budget` | 차량가 상한(만원) | 2500 |
| `--total-budget` | 총 구매비용 상한(만원, 추정치 기준) | 2700 |
| `--year` | 연식 하한 (CSV 기준. 탭 표시 하한은 build_guide.MAIN_YEAR) | 2019 |
| `--km` | 주행거리 상한 (CSV 기준. 탭 표시 상한은 build_guide.MAIN_KM) | 100000 |
| `--seats` | 좌석 수 (5인승만 고르려면 5) | 5 |
| `--suv-max` | SUV 크기 상한: `small`=셀토스급, `compact`=투싼·스포티지급, `none`=제한 없음 | compact |
| `--fuel` | `gasoline,hybrid,lpg,diesel` 중 선택 | 전부 |
| `--sleep` | 요청 간 대기(초) | 1.8 |

제조사·차종·사고·렌터카 제외 규칙과 **점수 가중치**는 `search_kcar.py` 상단 상수 블록
(`W_PRICE_GAP`, `W_KM_GAP`, `W_ACCIDENT`, `W_FUEL`, `PRICE_GAP_FULL` 등)에서 고친다.

## 수집 범위

`kcar.com/robots.txt`가 상세 페이지(`/bc/detail/carInfoDtl?`, `/car/info/`)를 Disallow하므로
**상세 페이지는 조회하지 않는다**. 목록 API만 쓰고, 요청은 순차·1.8초 간격이며 403/429/캡차가
보이면 우회 없이 중단한다. 따라서 총 구매비용(K카 표시값)·보험 이력·소유자 변경 횟수·등록일·
보증은 미수집(`null`)이며, 사이트에는 사진 없이 분석 표와 K카 링크만 게시한다(`noindex`).

개인 검토용 비공식 분석입니다. 출처는 K카이며 가격·매물 상태는 수시로 바뀝니다.
구매 판단은 매물 페이지에서 직접 확인하세요. 상업적 이용 금지.

## 페이지 두 개

| 페이지 | 용도 |
|---|---|
| `docs/index.html` | **어머님용 고르기 안내.** 맨 위에 **추천 5대**(문자로 보낼 텍스트 포함), 그 아래 기준별 6개 탭(풀옵션·가성비·가심비·하이브리드 2·전체). 점수로 줄 세우지 않고, 차종마다 엔진·변속기·연료·주행거리를 따져 "무엇을 확인해야 하는지"를 문장으로 보여준다. 현장 체크리스트(인쇄 가능) 포함. `build_guide.py` 가 생성 |
| `docs/all.html` | 분석용 전체 표. 점수·시세차 기준 정렬·검색. `build_report.py` 가 생성 |

```bash
python3.11 build_guide.py    # docs/index.html (어머님용 안내)
python3.11 build_report.py   # docs/report.md + docs/all.html (분석용)
```

차종 지식(엔진 판별, 차급, 연비·세금, 확인 항목 문구)은 `car_knowledge.py` 에 모여 있다.

**추천 5대 규칙**(`build_guide.pick_top5`, 상수 `PICK_SIZES`·`PICK_KM`·`PICK_MIN_EQUIP`·`PICK_MIN_ADAS`·`PICK_N`):
"차를 팔지 않고 끝까지 탄다" 가정 — 감가는 쓰지 않고 **10년 총지출(차값 + 세금·기름값×10)** 이 적은 순.
대상은 K5 크기 이상(중형·준대형 세단) · 7만km 이하 · 경고 없음 · 흔한 차(재고 30+) · 건식 DCT 제외 ·
장비 17+ · 안전장치 3+. 같은 차종+연료 조합은 한 번만.
SUV 5대(`pick_top5_suv`)는 같은 기준으로 소형·준중형 SUV(투싼·스포티지급까지, 쏘렌토·싼타페는 너무 커서 제외)에서 뽑되,
이 급 가솔린 터보가 대부분 건식 DCT라 제외하지 않고 '시승 필수'로 표시하며 같은 차종+엔진 조합을 한 번만 센다.

## 수집·비교 방식

**직영 재고 전체를 받는다.** 예산 이하 매물만 받아 중앙값을 내면 "예산 이하 차들끼리의
중앙값"이 되어 시세가 실제보다 낮게 잡힌다. 그래서 직영 재고 전량(약 7,400대)을 받아
시세 기준으로 쓰고, 조건 필터는 그 다음에 건다. 요청은 75회 내외, 순차·1.8초 간격.

**비교군은 좁은 쪽부터 단계적으로 후퇴한다.** 같은 세대 + 같은 좌석수 + 연식 ±1년을
바닥으로 두고, 그 안에서 연료 → 배기량 → 엔진(`grdNm`) → 트림 등급(`grdDtlNm`)까지
좁힌 뒤 3대 이상 남는 **가장 좁은 그룹**을 쓴다. 트림이 가격을 크게 가르기 때문이다
(예: 쏘나타 DN8은 최하 트림 1,170만원, 최상 트림 2,220만원).
트림까지 맞추지 못한 경우 안내 페이지는 **시세차를 주장하지 않고** 그 사실을 표시한다.

`data/market_stats.json` 에 차종별 재고량·순위와 세대별 연식 시세가 저장된다.
안내 페이지는 이 값으로 "흔한 차인가"(부품·정비·재판매)와 감가 흐름을 보여준다.
