# kcar-deals

K카(kcar.com) 직영 국산 중고차 매물을 수집해 같은 세대·연식 그룹의 시세와 비교하고 "꿀매물" 점수를 매기는 개인 프로젝트.

- 사이트: **https://inh1095.github.io/kcar-deals/**
- 리포트 전문: [`docs/report.md`](docs/report.md) · 진행 기록: [`PROGRESS.md`](PROGRESS.md) · 작업 지시서: [`WORKORDER.md`](WORKORDER.md)

## 실행

```bash
pip install --user requests pycryptodome                 # 의존성 2개
python3.11 search_kcar.py --out data/listings.csv        # 수집 + 시세비교 + 점수
python3.11 build_report.py                               # docs/report.md + docs/index.html
```

검증은 `python3.11 verify.py` (TOP 15 중 3대 재조회 대조 + 사이트 규칙 검사).
네트워크 요청 없이 점수만 다시 계산하려면 `--use-cache` (원본은 `data/raw/pages/`).

## 조건 바꾸기

`search_kcar.py` 인자로 바꾼다.

```bash
python3.11 search_kcar.py --budget 1500 --year 2019 --km 90000 --fuel hybrid,gasoline
python3.11 build_report.py
```

| 인자 | 뜻 | 기본값 |
|---|---|---|
| `--budget` | 차량가 상한(만원) | 1300 |
| `--total-budget` | 총 구매비용 상한(만원, 추정치 기준) | 1400 |
| `--year` | 연식 하한 | 2017 |
| `--km` | 주행거리 상한 | 120000 |
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
| `docs/index.html` | **어머님용 고르기 안내.** 점수로 줄 세우지 않고, 차종마다 엔진·변속기·연료·주행거리를 따져 "무엇을 확인해야 하는지"를 문장으로 보여준다. 현장 체크리스트(인쇄 가능) 포함. `build_guide.py` 가 생성 |
| `docs/all.html` | 분석용 전체 표. 점수·시세차 기준 정렬·검색. `build_report.py` 가 생성 |

```bash
python3.11 build_guide.py    # docs/index.html (어머님용 안내)
python3.11 build_report.py   # docs/report.md + docs/all.html (분석용)
```

차종 지식(엔진 판별, 차급, 연비·세금, 확인 항목 문구)은 `car_knowledge.py` 에 모여 있다.
