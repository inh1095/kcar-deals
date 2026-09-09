#!/usr/bin/env python3
"""data/listings.csv + market_stats.json → docs/index.html (어머님용 고르기 안내)

기준을 탭으로 나눠 직접 고르실 수 있게 만든다.

  가성비           — 10년 총지출(차값 + 유지비×10)이 가장 적은 차
  가심비           — 매일 체감하는 장비·안전이 가장 많고 값도 과하지 않은 차
  하이브리드 가성비  — 위 가성비 기준을 하이브리드 안에서만
  하이브리드 가심비  — 위 가심비 기준을 하이브리드 안에서만
  전체 비교        — 조건 통과 전부

'다시 팔지 않고 오래 탄다'는 전제이므로 감가는 순위에 쓰지 않는다(참고로만 표시).
하이브리드는 물량이 적어 연식 하한을 한 해 낮춘다(본문에 명시).

    python3.11 build_guide.py

LLM 없이 단독 실행된다. 차종 지식과 판정 규칙은 car_knowledge.py 에 있다.
사이트 규칙: 사진 없음, 외부 스크립트·폰트 없음, noindex, 상단에 수집 일시·출처·면책.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os

import car_knowledge as K

# ── 기준 상수 (여기만 고치면 순위가 바뀐다) ─────────────────────────────────
TOP_N = 3                    # 각 탭에 카드로 보여줄 대수
ANNUAL_KM = K.ANNUAL_KM
HOLD_YEARS = 10              # 오래 탈 기간 가정

MAIN_YEAR = 2020             # 일반 탭 연식 하한
HYBRID_YEAR = 2020           # 하이브리드 탭 연식 하한

# '풀옵션' 기준. 장비 24가지 중 이 개수 이상 + 첨단 안전장치 4가지 전부.
FULL_EQUIP = 20
FULL_ADAS = 4

# 탭에 올릴 주행거리 상한. CSV 는 이보다 넓게 받아 두고(어머님 매물 등 참고용) 여기서 좁힌다.
MAIN_KM = 80000

# 매일 체감하는 장비. 전 차량에 다 있는 항목(후방센서·열선시트 등)은 구분이 안 되므로 뺀다.
PREMIUM_FEEL = ["통풍시트", "전동시트", "무선충전", "어라운드뷰",
                "헤드업디스플레이", "선루프", "스마트크루즈", "뒷좌석열선"]

MIN_ADAS = 2                 # 추천 공통 안전 하한
MIN_EQUIP = 10               # 추천 공통 장비 하한
GASIMBI_RUN_CAP = 2_500_000  # 가심비 탭의 연 유지비 상한(원) — '값도 적당' 조건

COMMON_STRONG = 100
COMMON_OK = 30
RARE = 15

# 어머님이 직접 보내주신 매물(있으면 전용 칸에 따로 보여준다)
MOTHER_PICK = "EC61399954"

# 어머님께 보낼 추천 5대 — 어머님이 타시던 K5 크기 이상(중형 세단 이상)만.
# 자리: 가성비 1위 · 가심비 1위 · 하이브리드 가심비 2대 · 풀옵션 가성비 1위
PICK_SIZES = (K.SIZE_MID_SEDAN, K.SIZE_LARGE_SEDAN)
PICK_N_HYB = 2
PICK_KM = 70000              # 추천 5대의 주행거리 상한 ("키로수 적은 걸로")
PICK_GRADES = ("안심", "괜찮음")   # 풀옵션 자리에만 적용
PICK_HYB_MIN_ADAS = 3        # 하이브리드 자리는 안전장치 3가지 이상

DISCLAIMER = ("개인이 참고용으로 만든 비공식 정리입니다. 가격과 매물 상태는 수시로 바뀌고 "
              "차는 팔리면 사라집니다. 실제 구매 결정은 반드시 매물 페이지와 현장에서 "
              "직접 확인하세요. 상업적 이용 금지.")

GRADE_STYLE = {
    "안심": ("g-a", "확인할 점이 적습니다"),
    "괜찮음": ("g-b", "몇 가지만 확인하면 됩니다"),
    "따져보기": ("g-c", "확인할 점이 여러 개 있습니다"),
    "주의": ("g-d", "확인할 점이 많습니다"),
}


# ── 로드 ─────────────────────────────────────────────────────────────────────
def _json(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def load(csv_path="data/listings.csv"):
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    d = os.path.dirname(csv_path) or "."
    meta = _json(os.path.join(d, "meta.json"))
    stats = _json(os.path.join(d, "market_stats.json"))
    for r in rows:
        for k in ("km", "price", "year", "cc", "seats", "group_n", "total_cost_est",
                  "group_median_km", "airbags", "adas_n", "parking_aid_n",
                  "equip_n", "equip_total", "trim_rank", "trim_total"):
            r[k] = int(float(r[k])) if r.get(k) not in ("", None) else None
        for k in ("price_gap", "km_gap", "group_median_price"):
            r[k] = float(r[k]) if r.get(k) not in ("", None) else None
        r["opt"] = [o for o in (r.get("options") or "").split("|") if o]
        r["adas_list"] = [o for o in (r.get("adas") or "").split("|") if o]
    return rows, meta, stats


# ── 매물 평가 ────────────────────────────────────────────────────────────────
def evaluate(r: dict, stats: dict) -> dict:
    pt = K.identify_powertrain(r["model"], r["trim"], r["fuel"], r["cc"], r["year"])
    eng = K.ENGINES[pt["engine"]]
    size = K.size_of(r["model"])
    sn = K.SIZE_NOTES[size]
    fuel_note = K.FUEL_NOTES.get(r["fuel"], K.FUEL_NOTES["가솔린"])

    warn: list[str] = []
    caution: list[str] = []
    good: list[str] = []
    checks: list[str] = []

    # 돈 ---------------------------------------------------------------------
    tax = K.car_tax(r["cc"], r["year"]) or 0
    fuel_cost = K.annual_fuel_cost(pt["engine"], r["fuel"], model=r["model"]) or 0
    running = tax + fuel_cost
    run_hold = running * HOLD_YEARS
    total_hold = r["price"] * 10000 + run_hold
    gen_stats = (stats.get("generations") or {}).get(r["model"] or "")
    dep3, dep_basis = K.forward_depreciation(r["price"], r["year"], gen_stats)

    # 만족 요소 --------------------------------------------------------------
    feel = [o for o in PREMIUM_FEEL if o in r["opt"]]
    n_adas = r["adas_n"] or 0
    sat = len(feel) + n_adas
    won_per_sat = total_hold / sat if sat else None

    # 엔진 ------------------------------------------------------------------
    if eng["theta2"]:
        warn.append("엔진이 세타2 GDI 계열입니다 (리콜·보증 확인 필수)")
        checks.append(K.THETA2_NOTICE)
    if eng["nature"] == "자연흡기" and pt["tx"] in (K.TX_AUTO, K.TX_IVT) and not eng["theta2"]:
        good.append("터보도 DCT도 없습니다. 붙어 있는 부품이 가장 적어 "
                    "고장 날 수 있는 곳 자체가 적습니다")
    if eng["nature"] == "터보":
        caution.append("터보 엔진입니다")
        checks.append("터보는 터보차저·인터쿨러가 추가로 붙습니다. 부품이 늘어난 만큼 "
                      "손볼 곳도 늘어납니다. 시동 직후 '쉬익' 하는 큰 소리나 흰 연기가 "
                      "나는지 보고, 시동 걸고 바로 세게 밟지 않는 습관이 필요합니다.")
    if "GDI" in eng["name"] or "직분사" in eng["name"]:
        checks.append("직분사(GDI) 엔진은 엔진오일이 조금씩 줄어드는 경우가 보고됩니다. "
                      "오일 게이지를 뽑아 양과 색을 보고, 보충 이력이 있는지 물어보세요.")

    # 변속기 ----------------------------------------------------------------
    if pt["tx"] == K.TX_DCT_DRY:
        caution.append("변속기가 건식 DCT입니다")
        checks.append("건식 DCT는 수동변속기 클러치를 자동으로 여닫는 구조라 클러치가 "
                      "소모품입니다. **시승할 때 반드시 막히는 길이나 오르막에서 "
                      "시속 10~30km로 천천히 가보세요.** 울컥거림이 거슬리면 피하시는 게 "
                      "낫습니다. 시내 위주로 다니신다면 특히 중요합니다.")
    else:
        good.append(f"변속기가 {pt['tx']}입니다 — {K.TX_EXPLAIN[pt['tx']]}")

    # 연료 ------------------------------------------------------------------
    if r["fuel"] == "디젤":
        caution.append("디젤입니다")
    elif r["fuel"] == "하이브리드":
        caution.append("하이브리드 배터리 보증을 확인해야 합니다")
        good.append("기름값이 가장 적게 들고 저속에서 매우 조용합니다")
    elif r["fuel"] == "LPG":
        caution.append("LPG 연료통 검사 기간을 확인해야 합니다")
        good.append("연료비가 가솔린의 절반 수준입니다")
    checks += fuel_note["watch"]

    # 사고 ------------------------------------------------------------------
    if r["accident"] == "무사고":
        good.append("K카 진단 기준 무사고입니다")
    else:
        caution.append("K카 진단 기준 '단순수리' 이력이 있습니다")
        checks.append("'단순수리'는 문·펜더처럼 볼트로 붙는 겉판 교환이 대부분이고 뼈대를 "
                      "건드린 것과는 다릅니다. 하지만 **어디를 얼마나 수리했는지 진단서를 "
                      "종이로 받아 확인하세요.** 뼈대 수리나 여러 곳 동시 수리가 적혀 "
                      "있으면 값이 싸도 피하세요.")

    # 주행거리·연식 ---------------------------------------------------------
    if r["km"] >= 95000:
        caution.append(f"주행거리 {r['km']:,}km — 10만km 정비 시점이 가깝습니다")
    if r["km"] < 60000:
        good.append(f"주행거리가 {r['km']:,}km로 짧습니다")
    checks += K.mileage_notes(r["km"])
    checks += K.age_notes(r["year"])

    # 시세 위치 -------------------------------------------------------------
    basis = r.get("group_basis") or ""
    exact = basis.endswith("트림")
    pg = r["price_gap"]
    if pg is not None and not exact:
        caution.append("같은 트림 비교 대상이 적어 시세차를 신뢰할 수 없습니다")
        checks.append(f"이 차와 트림이 똑같은 차가 3대도 없어 {basis}(으)로 넓혀 "
                      f"비교했습니다. 트림이 섞여 <b>이 시세차는 믿을 수 없습니다.</b> "
                      f"K카 페이지에서 같은 트림끼리 직접 비교해 보세요.")
        pg = None
    elif pg is None:
        caution.append(f"비교할 차가 {r['group_n']}대뿐이라 시세를 알기 어렵습니다")
    if pg is not None:
        if pg >= 0.10:
            good.append(f"같은 트림 {r['group_n']}대와 비교해 {pg:.0%} 저렴합니다")
        elif pg <= -0.10:
            warn.append(f"같은 트림 {r['group_n']}대와 비교해 {abs(pg):.0%} 비쌉니다")
        elif pg <= -0.03:
            caution.append(f"같은 트림 {r['group_n']}대와 비교해 {abs(pg):.0%} 비싼 편입니다")

    # 흔한 차 (부품·정비) ---------------------------------------------------
    mstat = (stats.get("models") or {}).get(r["model_group"] or "", {})
    cnt, rank = mstat.get("count", 0), mstat.get("rank")
    nmodels = stats.get("model_count", 0)
    # 세대(model) 재고 — 부품을 가장 직접적으로 공유하는 단위.
    # 차종(model_group) 재고는 세대가 섞여 있어 이 값과 따로 본다.
    gen_cnt = ((stats.get("generations") or {}).get(r["model"] or "", {}) or {}).get("count", 0)
    if cnt >= COMMON_STRONG:
        good.append(f"K카 직영 재고에 {cnt}대나 있는 아주 흔한 차입니다 "
                    f"(차종 {nmodels}종 중 {rank}위) — 부품 구하기 쉽고 어느 정비소나 "
                    f"고쳐 본 경험이 있습니다")
    elif cnt >= COMMON_OK:
        good.append(f"재고 {cnt}대로 흔한 편입니다 — 부품·정비에 무리가 없습니다")
    elif cnt < RARE:
        caution.append(f"재고가 {cnt}대뿐인 드문 차입니다")
        checks.append(f"이 차는 K카 직영 재고 전체에서 {cnt}대뿐입니다"
                      f"(차종 {nmodels}종 중 {rank}위). 드문 차는 특정 부품을 주문해야 할 수 "
                      f"있고 동네 정비소가 안 만져 봤을 수 있습니다. "
                      f"오래 타실 거라면 이 점이 특히 중요합니다.")

    if gen_cnt and gen_cnt < 12 and cnt >= RARE:
        caution.append(f"이 세대(‘{r['model']}’)는 재고가 {gen_cnt}대뿐입니다")
        checks.append(f"차종 전체로는 흔하지만 <b>이 세대는 재고가 {gen_cnt}대뿐</b>입니다. "
                      f"세대가 다르면 부품이 달라지는 경우가 많으니, 오래 타실 거라면 "
                      f"같은 값대에 더 흔한 세대가 있는지 함께 보세요.")

    # 안전 ------------------------------------------------------------------
    if n_adas >= 3:
        good.append(f"사고를 막아 주는 안전장치가 {n_adas}가지 있습니다 "
                    f"({', '.join(r['adas_list'])})")
    elif n_adas == 0:
        caution.append("첨단 안전장치가 확인되지 않습니다")
    if "자동긴급제동" not in r["adas_list"]:
        caution.append("자동 긴급제동(앞차 추돌 방지)이 확인되지 않습니다")
        checks.append("<b>자동 긴급제동이 옵션 목록에 없습니다.</b> 안전장치 중 사고를 가장 "
                      "많이 줄여 주는 기능이라, 같은 값대에 이 기능이 있는 차와 꼭 비교해 "
                      "보세요. 표기가 빠진 경우도 있으니 차에서 직접 확인하세요.")
    for name, why in (
            ("자동긴급제동", "앞차를 못 봤을 때 차가 스스로 브레이크를 잡아 줍니다"),
            ("후측방경보", "차선을 바꿀 때 옆·뒤 차를 사이드미러에 알려 줍니다"),
            ("차선이탈경보", "차선을 넘으면 경고해 줍니다"),
            ("스마트크루즈", "앞차와 거리를 자동으로 맞춰 줍니다")):
        if name in r["adas_list"]:
            good.append(f"{name} — {why}")
    if (r["airbags"] or 0) >= 4:
        good.append(f"에어백이 {r['airbags']}종류 들어 있습니다")

    # 주차·크기 -------------------------------------------------------------
    if "후방카메라" not in r["opt"]:
        caution.append("후방카메라가 확인되지 않습니다")
        checks.append("후방카메라가 목록에 없습니다. 실제로 있는지 차에서 확인하시고, "
                      "없으면 설치 비용(20~40만원)을 감안하세요.")
    if "어라운드뷰" in r["opt"]:
        good.append("360도 어라운드뷰가 있어 주차할 때 차 주변이 위에서 보입니다")
    if sn["park_level"] == "어려움":
        caution.append("차가 커서 주차가 부담될 수 있습니다")
    elif sn["park_level"] == "쉬움":
        good.append("차가 작아 주차가 편합니다")
    if size == K.SIZE_SMALL_SUV:
        good.append("시트가 적당히 높아 타고 내리기 가장 편한 차급입니다")

    # 트림·장비 -------------------------------------------------------------
    eq_n, eq_tot = r["equip_n"] or 0, r["equip_total"] or 24
    eq_ratio = eq_n / eq_tot if eq_tot else 0
    tr, tr_tot = r["trim_rank"], r["trim_total"] or 0
    if tr and tr_tot >= 3 and tr <= max(2, tr_tot // 3):
        good.append(f"이 세대 트림 {tr_tot}개 중 <b>위에서 {tr}번째 등급</b>입니다 — "
                    f"오래 타실 거라면 트림이 만족도를 가장 크게 바꿉니다")
    elif tr and tr_tot >= 4 and tr >= tr_tot - 1:
        caution.append(f"이 세대 트림 {tr_tot}개 중 기본에 가까운 등급입니다")
    if eq_ratio >= 0.75:
        good.append(f"편의·안전 장비를 {eq_n}가지({eq_tot}가지 중) 갖췄습니다")
    elif eq_ratio <= 0.42:
        caution.append(f"장비가 {eq_n}가지({eq_tot}가지 중)로 적은 편입니다")
    if feel:
        good.append("매일 체감하는 장비: " + "·".join(feel))

    # 유지비 코멘트 ---------------------------------------------------------
    if running <= 1_700_000:
        good.append(f"연 유지비가 {running // 10000}만원으로 낮습니다 "
                    f"({HOLD_YEARS}년 {run_hold // 10000:,}만원)")
    elif running >= 2_600_000:
        caution.append(f"연 유지비가 {running // 10000}만원입니다 "
                       f"({HOLD_YEARS}년 {run_hold // 10000:,}만원)")
        checks.append(f"이 차는 세금·기름값이 연 {running // 10000}만원이라 "
                      f"{HOLD_YEARS}년이면 <b>{run_hold // 10000:,}만원</b>이 됩니다. "
                      f"차값에 더해 이 돈이 나간다고 보셔야 합니다.")

    # 등급 ------------------------------------------------------------------
    if len(warn) >= 2:
        grade = "주의"
    elif len(warn) == 1 or len(caution) >= 5:
        grade = "따져보기"
    elif len(caution) >= 3:
        grade = "괜찮음"
    else:
        grade = "안심"

    return dict(pt=pt, eng=eng, size=size, size_note=sn,
                warn=warn, caution=caution, good=good,
                checks=[c for c in checks if c], grade=grade,
                tax=tax, fuel_cost=fuel_cost, running=running, run_hold=run_hold,
                total_hold=total_hold, dep3=dep3, dep_basis=dep_basis,
                feel=feel, sat=sat, won_per_sat=won_per_sat,
                eq_ratio=eq_ratio, stock=cnt, rank=rank, gen_stock=gen_cnt)


# ── 순위 기준 ────────────────────────────────────────────────────────────────
def eligible(i: dict) -> bool:
    """추천 공통 하한 — 안전·장비가 너무 적거나 경고가 있는 차는 추천에서 뺀다."""
    return ((i["adas_n"] or 0) >= MIN_ADAS and (i["equip_n"] or 0) >= MIN_EQUIP
            and i["ev"]["grade"] != "주의" and not i["ev"]["warn"])


def rank_value(items):
    """가성비 — 10년 총지출이 적은 순."""
    return sorted([i for i in items if eligible(i)], key=lambda i: i["ev"]["total_hold"])


def rank_satisfaction(items):
    """가심비 — 만족 요소가 많은 순, 같으면 총지출이 적은 순. 유지비 상한을 둔다."""
    pool = [i for i in items if eligible(i) and i["ev"]["running"] <= GASIMBI_RUN_CAP]
    return sorted(pool, key=lambda i: (-i["ev"]["sat"], i["ev"]["total_hold"]))


def is_full_option(i: dict) -> bool:
    """풀옵션 — 장비 20가지 이상이고 첨단 안전장치 4가지를 다 갖춘 차."""
    return (i["equip_n"] or 0) >= FULL_EQUIP and (i["adas_n"] or 0) >= FULL_ADAS


def rank_full(items):
    """풀옵션만 모아 10년 총지출이 적은 순. 옵션은 이미 최상위라 값으로 줄인다."""
    return sorted([i for i in items if eligible(i) and is_full_option(i)],
                  key=lambda i: i["ev"]["total_hold"])


def pick_diverse(ranked, n=TOP_N):
    out, seen = [], set()
    for i in ranked:
        key = i["model_group"] or i["model"]
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
        if len(out) >= n:
            break
    return out


def pick_pool(main):
    """추천 5대의 대상 — K5 크기 이상(PICK_SIZES) · PICK_KM 이하."""
    return [i for i in main
            if i["ev"]["size"] in PICK_SIZES and (i["km"] or 0) <= PICK_KM]


def pick_top5(main):
    """어머님께 보낼 추천 5대. 각 차에 'pick_label'(어느 자리로 뽑혔는지)을 붙여 돌려준다.

    대상은 pick_pool(): 어머님이 타시던 K5 크기 이상(중형 세단·준대형 이상 세단), PICK_KM 이하.
      1. 가성비 1위        — rank_value 1위 (10년 총지출 최소)
      2. 가심비 1위        — rank_satisfaction 1위 (만족 요소 최다)
      3~4. 하이브리드 가심비 — 하이브리드 중 만족 요소 순 PICK_N_HYB대 (안전장치 PICK_HYB_MIN_ADAS+)
      5. 풀옵션 가성비 1위  — 장비 FULL_EQUIP+ · 안전 FULL_ADAS종, 건식 DCT 제외, 등급 PICK_GRADES
    같은 차종+연료 조합은 한 번만 뽑는다(쏘나타 가솔린과 쏘나타 하이브리드는 다른 차로 본다)."""
    pool = pick_pool(main)
    hy = [i for i in pool if i["fuel"] == "하이브리드"]
    picks: list[dict] = []
    seen: set = set()

    def key(i):
        return (i["model_group"] or i["model"], i["fuel"])

    def take(label, ranked, n=1, cond=None):
        got = 0
        for i in ranked:
            if key(i) in seen or (cond and not cond(i)):
                continue
            seen.add(key(i))
            picks.append(dict(i, pick_label=label))
            got += 1
            if got >= n:
                break

    take("가성비 1위", rank_value(pool))
    take("가심비 1위", rank_satisfaction(pool))
    take("하이브리드 가심비", rank_satisfaction(hy), PICK_N_HYB,
         lambda i: (i["adas_n"] or 0) >= PICK_HYB_MIN_ADAS)
    take("풀옵션 가성비 1위", rank_full(pool), 1,
         lambda i: i["ev"]["pt"]["tx"] != K.TX_DCT_DRY and i["ev"]["grade"] in PICK_GRADES)
    return picks


# ── 공통 콘텐츠 ──────────────────────────────────────────────────────────────
CHANNELS = [
    ("K카 (케이카) 직영", "https://www.kcar.com/bc/search",
     "이 페이지가 쓰는 곳입니다. 회사가 직접 사서 진단하고 파는 '직영'이라 차량 상태 "
     "기준이 일정하고, 일정 기간 책임 환불 제도가 있습니다. 집까지 배송도 됩니다.",
     "수집함 — 이 페이지의 모든 차", True),
    ("현대·제네시스 인증중고차", "https://certified.hyundai.com/p/search/vehicle",
     "<b>안전과 보증만 보면 여기가 가장 낫습니다.</b> 제조사가 직접 정밀 진단하고 신차 "
     "보증의 남은 기간을 이어 줍니다. 5년/10만km 이내만 취급하고, 값은 같은 조건에서 "
     "다른 곳보다 비쌉니다.", "수집 못 함 — 사이트가 자동 조회를 거부", False),
    ("기아 인증중고차", "https://www.kia.com/kr/customer-service/certified-used-car",
     "현대와 같은 구조의 기아 공식 채널입니다. 제조사 진단·보증이 붙습니다.",
     "미조사", False),
    ("엔카 (encar)", "https://www.encar.com/dc/dc_carsearchlist.do",
     "매물이 가장 많습니다. 다만 대부분 <b>딜러가 올린 매물</b>이라 차량 상태와 응대가 "
     "딜러마다 다릅니다. '엔카 진단'이 붙은 매물만 골라 보세요.",
     "수집 금지 — robots.txt가 매물 데이터를 금지", False),
    ("KB차차차", "https://www.kbchachacha.com/public/search/main.kbc",
     "KB캐피탈이 운영하는 딜러 매물 플랫폼입니다. 금융(할부) 조건을 함께 보기 편합니다.",
     "미수집 — 목록이 자동 조회로 열리지 않음", False),
]

LOOKUPS = [
    ("자동차리콜센터", "https://www.car.go.kr/",
     "차대번호로 리콜 대상인지, 조치가 끝났는지 조회합니다. 무료입니다."),
    ("보험개발원 카히스토리", "https://www.carhistory.or.kr/",
     "보험 수리 이력, 침수·전손 여부, 소유자 변경 횟수를 조회합니다. 약 2,200원입니다."),
    ("자동차민원 대국민포털", "https://www.ecar.go.kr/",
     "자동차 등록 원부로 용도(자가용/영업용) 이력을 봅니다."),
]

HYBRID_CHECKS = [
    "<b>고전압 배터리 보증이 얼마나 남았는지</b>를 차대번호로 확인한다. 이게 하이브리드에서 "
    "가장 중요하다. 보증이 남아 있으면 배터리는 걱정하지 않아도 된다.",
    "시동을 걸고 <b>전기로만 조용히 움직이는지</b> 확인한다. 저속에서 엔진이 계속 돌면 "
    "배터리 상태를 의심한다.",
    "계기판의 <b>배터리 충전 표시가 정상 범위에서 오르내리는지</b> 본다. "
    "한쪽에 붙어 움직이지 않으면 물어본다.",
    "12V 보조배터리도 따로 있다. 수명이 다하면 시동이 안 걸리므로 교체 시기를 물어본다.",
    "브레이크는 회생제동을 쓰므로 일반차보다 패드가 덜 닳는다. "
    "<b>주행거리가 많아도 브레이크가 멀쩡한 것은 정상</b>이다.",
    "하이브리드는 정체 구간에서 가장 유리하다. <b>시내 위주로 다니시면 최고의 선택</b>이다.",
]

FIELD_CHECKLIST = [
    ("가기 전에 집에서 (5분)", [
        "매물 번호로 K카 페이지를 열어 가격·주행거리·연식이 이 표와 같은지 본다. "
        "다르면 이미 팔렸거나 값이 바뀐 것이다.",
        "자동차리콜센터(car.go.kr)에서 차대번호로 <b>리콜 대상인지, 조치가 끝났는지</b> 조회한다.",
        "보험개발원 카히스토리(carhistory.or.kr)에서 <b>보험 수리 이력</b>을 조회한다. "
        "약 2,200원이지만 침수·전손까지 나오므로 꼭 본다.",
        "전화로 '차가 아직 있는지, 진단서와 정비이력을 종이로 볼 수 있는지' 확인한다.",
        "가능하면 <b>아침 첫 방문</b>으로 예약한다. 시동을 한 번도 걸지 않은 차를 봐야 한다.",
    ]),
    ("차 밖에서 (10분)", [
        "밝은 낮에, 비 오지 않을 때 본다. 어두우면 판금·도색 흔적이 안 보인다.",
        "차 앞에 쪼그려 앉아 옆에서 차체 선을 따라 본다. 물결처럼 울렁이면 판금한 자리다.",
        "문·보닛·트렁크 틈이 좌우 대칭인지 손가락을 넣어 본다. 한쪽이 넓으면 사고 흔적이다.",
        "문틈·보닛 안쪽의 <b>고무 몰딩을 살짝 들어</b> 도색이 겹쳐 있는지 본다.",
        "볼트 머리의 페인트가 벗겨졌거나 공구 자국이 있는지 본다. 뗐다 붙인 흔적이다.",
        "타이어 4개 상표가 같은지, 옆면 4자리 숫자(제조 주차)를 본다. "
        "'2419'는 2019년 24주 생산. 5년 넘었으면 교체 비용을 감안한다.",
        "타이어 홈에 100원짜리를 거꾸로 꽂아 이순신 장군 감투가 보이면 교체 시기다.",
        "타이어가 한쪽만 심하게 닳지 않았는지 본다. 한쪽만 닳으면 정렬·하부 문제다.",
        "차 밑을 들여다보고 바닥에 기름이나 물이 떨어진 자리가 있는지 본다.",
    ]),
    ("차 안에서 (10분)", [
        "문을 다 닫고 <b>냄새를 맡는다.</b> 곰팡이·흙 냄새가 나면 침수 의심이다.",
        "안전벨트를 끝까지 쭉 뽑아 아래쪽에 흙물 자국이나 곰팡이가 있는지 본다. "
        "침수차를 잡는 가장 쉬운 방법이다.",
        "트렁크 바닥 매트를 들어내고 스페어타이어 자리에 녹이나 흙이 있는지 본다.",
        "운전석에 앉아 <b>어머님이 편한 자세가 나오는지</b> 본다. 페달까지 발이 편히 닿고 "
        "계기판이 잘 보이고 앞유리 시야가 답답하지 않아야 한다.",
        "타고 내리기를 <b>세 번 반복해 본다.</b> 매일 하실 동작이다.",
        "브레이크·가속 페달 고무의 닳은 정도를 본다. 주행거리에 비해 많이 닳았으면 의심한다.",
        "에어컨을 가장 세게, 히터도 가장 뜨겁게 켜 본다. 곰팡이 냄새가 나는지 본다.",
        "창문·사이드미러 접힘·와이퍼·경음기·등화·후방카메라·내비를 하나씩 눌러 본다.",
        "시동을 켠 상태에서 계기판에 <b>경고등이 남아 있는지</b> 본다. 엔진·배터리·"
        "브레이크·에어백 경고등이 켜져 있으면 그 자리에서 이유를 물어야 한다.",
    ]),
    ("시동과 엔진룸 (10분)", [
        "<b>시동을 한 번도 걸지 않은 차를 본다.</b> 보닛을 손등으로 만져 따뜻하면 "
        "이미 걸었던 차다. 미리 데워 둔 차는 냉간 증상을 감춘다.",
        "시동 거는 순간 소리를 듣는다. '딱딱딱' 금속성 소리, 심한 떨림, '끼익' 벨트 소리가 "
        "있으면 원인을 물어본다.",
        "엔진오일 게이지를 뽑아 <b>양이 정상 범위인지, 색이 새까맣지 않은지</b> 본다.",
        "냉각수 통의 물이 적정선인지, 색이 탁하거나 기름이 떠 있지 않은지 본다.",
        "엔진 주변에 젖어 번쩍이는 곳(누유)이나 하얗게 말라붙은 자국(냉각수)이 있는지 본다.",
        "배터리 제조일 스티커를 본다. 3년 넘었으면 곧 교체다(10~20만원).",
        "엔진룸이 유난히 반짝반짝 세척돼 있으면 오히려 의심한다. 누유 흔적을 지운 경우가 있다.",
    ]),
    ("반드시 시승 (15분 이상)", [
        "<b>시승 없이 계약하지 않는다.</b> 안 된다고 하면 다른 차를 본다.",
        "가다 서다 하는 <b>정체 구간</b>을 꼭 지나본다. 시속 10~30km에서 울컥거림이나 "
        "떨림이 있는지 본다. (건식 DCT 차는 이 구간이 핵심이다)",
        "오르막에서 가속해 본다. 힘이 없거나 변속이 늦으면 원인을 물어본다.",
        "시속 60~80km에서 핸들에서 손을 살짝 떼 본다. 한쪽으로 쏠리면 정렬이나 사고 이력이다.",
        "빈 곳에서 브레이크를 세게 밟아 본다. 핸들이 떨리거나 '끼익' 소리가 나면 교체가 필요하다.",
        "창문 닫고 라디오 끄고 <b>소리에만 집중해</b> 달린다. '웅~' 소리가 커지면 베어링, "
        "'덜덜' 소리는 하부 부싱이다.",
        "정차 중 기어를 D와 R로 번갈아 넣어 본다. '쿵' 충격이 크면 변속기·마운트 문제다.",
        "후진으로 주차를 한 번 해 본다. 후방 시야와 카메라 화질을 직접 확인한다.",
        "시승 후 다시 차 밑을 보고 새로 떨어진 액체가 없는지 본다.",
    ]),
    ("서류와 계약 (10분)", [
        "<b>K카 진단서(성능·상태점검기록부)를 종이로 받아</b> 수리 부위 표시를 직접 본다. "
        "'교환'과 '판금'이 어디에 몇 군데인지 센다.",
        "자동차등록증의 차대번호가 차 앞유리 밑 번호와 같은지 대조한다.",
        "등록증의 <b>소유자 변경 횟수</b>를 본다. 3회 이상이면 이유를 물어본다.",
        "'용도'가 자가용인지 본다. 영업용·대여용 이력이 있으면 값이 더 싸야 한다.",
        "등록증의 <b>승차정원이 5인</b>인지 확인한다(이 목록은 5인승만 골랐다).",
        "정비 이력을 받아 <b>10만km 정비(변속기오일·점화플러그·냉각수)</b> 여부를 확인한다.",
        "총 구매비용을 <b>종이로 받는다.</b> 차값 외 이전비·매도비·탁송비가 항목별로 "
        "적힌 견적을 받는다. 말로 들은 금액과 다른 경우가 있다.",
        "K카 보증(기본·연장) 범위와 기간을 문서로 확인한다. 엔진·변속기 포함 여부가 핵심이다.",
        "계약서에 서명하기 전 <b>하루 자고 결정하셔도 된다.</b> 재촉하는 곳은 피한다.",
    ]),
]

RED_FLAGS = [
    "정비소에 가서 점검해 보자고 했을 때 <b>거절하거나 미루는</b> 경우",
    "진단서·정비이력을 종이로 못 준다고 하는 경우",
    "차가 이미 시동이 걸려 따뜻해져 있고, 식힌 뒤 다시 걸어보자면 거절하는 경우",
    "안전벨트 아래쪽이나 트렁크 안쪽에 <b>흙물 자국·곰팡이</b>가 있는 경우 (침수 의심)",
    "계기판에 <b>경고등이 켜져 있는데</b> '원래 그렇다'고 넘어가는 경우",
    "실내에서 <b>방향제 냄새가 유독 강한</b> 경우 (냄새를 덮는 경우가 있다)",
    "같은 차·같은 연식보다 값이 <b>유난히 싼데</b> 이유를 설명하지 못하는 경우",
    "주행거리가 아주 짧다는데 <b>페달 고무·핸들·시트가 많이 닳아 있는</b> 경우",
    "계약을 <b>오늘 안 하면 안 된다</b>고 재촉하는 경우",
]

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:#f7f6f3;color:#1b1b1b;
font-family:system-ui,-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
font-size:19px;line-height:1.8;letter-spacing:-.01em}
main{max-width:920px;margin:0 auto;padding:24px 18px 80px}
h1{font-size:1.85rem;line-height:1.35;margin:.4em 0 .2em}
h2{font-size:1.4rem;margin:2.2em 0 .5em;padding-bottom:.35em;border-bottom:3px solid #2f6f4f}
h3{font-size:1.12rem;margin:1.5em 0 .4em}
p{margin:.7em 0}
.lead{font-size:1.05rem;color:#333}
.top{background:#2f6f4f;color:#fff;padding:18px 20px;border-radius:12px;margin:16px 0}
.top b{color:#ffe9a8}
.top p{margin:.4em 0;font-size:.97rem;line-height:1.7}
.box{background:#fff;border:1px solid #e0ddd6;border-radius:12px;padding:18px 20px;margin:16px 0}
.warnbox{background:#fff7f5;border:1px solid #e8bfb4;border-left:6px solid #c0392b}
.tipbox{background:#f4faf6;border:1px solid #bcdcc7;border-left:6px solid #2f6f4f}
.mombox{background:#fffdf3;border:2px solid #d9c47a;border-radius:12px;padding:18px 20px;
margin:16px 0}

/* 탭 — 라디오 + CSS 만으로 전환된다(자바스크립트가 막혀도 동작) */
.tabs{margin:20px 0}
.tabs>input{position:absolute;opacity:0;pointer-events:none}
.tabbar{display:flex;gap:6px;flex-wrap:wrap;border-bottom:3px solid #2f6f4f}
.tabbar label{cursor:pointer;padding:11px 15px;border:2px solid #cfd8d2;border-bottom:none;
border-radius:12px 12px 0 0;background:#eceee9;font-weight:700;font-size:.97rem;color:#4a5a50;
margin-bottom:-3px}
.tabbar label small{display:block;font-weight:400;font-size:.76rem;color:#6b7a70;margin-top:2px}
.tabbar label.hyb{background:#e7f1ea;border-color:#a9cbb6;color:#1c5c38}
#t1:checked~.tabbar label[for=t1],#t2:checked~.tabbar label[for=t2],
#t3:checked~.tabbar label[for=t3],#t4:checked~.tabbar label[for=t4],
#t5:checked~.tabbar label[for=t5],#t6:checked~.tabbar label[for=t6]{background:#2f6f4f;
color:#fff;border-color:#2f6f4f}
#t1:checked~.tabbar label[for=t1] small,#t2:checked~.tabbar label[for=t2] small,
#t3:checked~.tabbar label[for=t3] small,#t4:checked~.tabbar label[for=t4] small,
#t5:checked~.tabbar label[for=t5] small,#t6:checked~.tabbar label[for=t6] small
{color:#d7ecdd}
.panel{display:none;background:#fff;border:2px solid #2f6f4f;border-top:none;
border-radius:0 0 12px 12px;padding:20px}
#t1:checked~.panels>#p1,#t2:checked~.panels>#p2,#t3:checked~.panels>#p3,
#t4:checked~.panels>#p4,#t5:checked~.panels>#p5,#t6:checked~.panels>#p6{display:block}

.card{background:#fff;border:1px solid #ddd9d1;border-radius:14px;padding:20px;margin:18px 0;
box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card.mom{border:2px solid #d9c47a;background:#fffdf3}
.pick{background:#fff;border:1px solid #cfe3d7;border-left:6px solid #2f6f4f;border-radius:12px;
 padding:14px 18px;margin:12px 0}
.pick h3{margin:0 0 .3em;font-size:1.15rem;line-height:1.45}
.pick h3 a.cname{color:#123f6e}
.pick p{margin:.35em 0;font-size:.97rem}
.pick .pspec{color:#333}
.plabel{display:inline-block;background:#2f6f4f;color:#fff;border-radius:6px;padding:2px 9px;
 font-size:.8rem;margin-right:6px;vertical-align:middle;white-space:nowrap}
.card h3{margin-top:0;font-size:1.2rem;line-height:1.4}
.rank{display:inline-block;background:#2f6f4f;color:#fff;border-radius:999px;
width:1.9em;height:1.9em;line-height:1.9em;text-align:center;font-size:.95rem;
font-weight:700;margin-right:.4em}
.rank.mom{background:#b8952f;width:auto;padding:0 .8em;border-radius:999px}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.85rem;
font-weight:700;margin-left:.3em;white-space:nowrap}
.g-a{background:#dff2e4;color:#1c5c38}
.g-b{background:#e6f0fb;color:#1c4a7a}
.g-c{background:#fdf1dc;color:#8a5a12}
.g-d{background:#fbe3e0;color:#932018}
.spec{display:flex;flex-wrap:wrap;gap:6px 0;margin:12px 0;padding:10px 0;list-style:none;
border-top:1px solid #eee;border-bottom:1px solid #eee}
.spec li{flex:1 1 50%;font-size:.93rem;color:#333}
.money{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.money div{flex:1 1 150px;background:#faf9f6;border:1px solid #e5e2da;border-radius:10px;
padding:10px 12px}
.money span{display:block;font-size:.79rem;color:#666}
.money strong{font-size:1.06rem}
.money .hi{background:#eef4f0;border-color:#8fbfa2;border-width:2px}
.pros,.cons{margin:.5em 0;padding-left:1.3em}
.pros li{color:#1c5c38;margin:.25em 0}
.cons li{color:#8a3b12;margin:.25em 0}
details{margin:10px 0;border:1px solid #e0ddd6;border-radius:10px;background:#fff}
details[open]{background:#fffdf8}
summary{cursor:pointer;padding:12px 16px;font-weight:700;font-size:1rem;
background:#f2f1ee;border-radius:10px}
details[open] summary{border-radius:10px 10px 0 0;border-bottom:1px solid #e0ddd6}
.dbody{padding:6px 18px 16px}
ol.chk,ul.chk{padding-left:1.4em;margin:.6em 0}
ol.chk li,ul.chk li{margin:.55em 0;line-height:1.7}
a{color:#1a5fa8}
a.cname{color:#1a5fa8;text-decoration:underline;text-decoration-thickness:2px;
text-underline-offset:2px;display:inline-block;padding:3px 0;min-height:28px}
a.cname:hover{color:#0d3f78;background:#eef4fb}
.card h3 a.cname{color:#123f6e}
.btn{display:inline-block;background:#2f6f4f;color:#fff !important;text-decoration:none;
padding:11px 20px;border-radius:10px;font-weight:700;margin:6px 6px 6px 0;font-size:1rem;
border:none;cursor:pointer;font-family:inherit}
.btn.alt{background:#fff;color:#2f6f4f !important;border:2px solid #2f6f4f}
table.simple{border-collapse:collapse;width:100%;font-size:.91rem;margin:10px 0}
table.simple th,table.simple td{padding:8px 6px;border-bottom:1px solid #e5e2da;text-align:left}
table.simple th{background:#f2f1ee}
table.simple td.num,table.simple th.num{text-align:right}
table.simple .sub{font-size:.82rem;color:#666}
table.simple tr.me{background:#fff6d9}
.wrap{overflow-x:auto;background:#fff;border:1px solid #e0ddd6;border-radius:10px;margin:8px 0}
table.cmp{border-collapse:collapse;width:100%;font-size:.88rem;min-width:600px}
table.cmp th,table.cmp td{padding:7px 8px;border-bottom:1px solid #eee;text-align:left;
white-space:nowrap;vertical-align:middle}
table.cmp th{background:#eef0ec;position:sticky;top:0;cursor:pointer;user-select:none;
font-weight:700;font-size:.79rem;line-height:1.25;z-index:2}
table.cmp th:hover{background:#e2e6e0}
table.cmp th.key{background:#cfe3d7}
table.cmp td.num,table.cmp th.num{text-align:right}
table.cmp tbody tr:nth-child(even){background:#fbfbf9}
table.cmp tbody tr:hover{background:#eef6f0}
table.cmp tbody tr.me{background:#fff6d9;font-weight:600}
table.cmp .sub{font-size:.8rem;color:#666;white-space:normal}
.ctl{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.ctl input,.ctl select{padding:9px 11px;border:1px solid #bbb;border-radius:8px;
font-size:.95rem;font-family:inherit}
.ctl input{flex:1 1 240px}
footer{margin-top:50px;padding-top:18px;border-top:1px solid #ccc;font-size:.85rem;color:#555}
@media print{
 body{background:#fff;font-size:12pt}
 .noprint{display:none !important}
 details{border:none}details summary{display:none}details .dbody{padding:0}
 .panel{display:block !important;border:none;padding:0}
 .tabbar{display:none}
 h2{page-break-after:avoid}.card{page-break-inside:avoid}
}
@media(max-width:600px){
 body{font-size:18px}h1{font-size:1.5rem}h2{font-size:1.22rem}
 .spec li{flex:1 1 100%}main{padding:16px 14px 60px}
 .tabbar label{padding:9px 10px;font-size:.86rem;flex:1 1 45%}
 .panel{padding:14px}
}
"""

CMP_JS = """
document.querySelectorAll('table.cmp').forEach(function(t){
  t.querySelectorAll('th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var tb=t.tBodies[0], rs=Array.prototype.slice.call(tb.rows);
      var dir=th.dataset.dir==='asc'?-1:1;
      t.querySelectorAll('th').forEach(function(o){delete o.dataset.dir});
      th.dataset.dir=dir===1?'asc':'desc';
      rs.sort(function(a,b){
        var x=a.cells[i],y=b.cells[i],nx=x.dataset.v,ny=y.dataset.v;
        if(nx!==undefined&&ny!==undefined){return (parseFloat(nx)-parseFloat(ny))*dir}
        return x.textContent.localeCompare(y.textContent,'ko')*dir;
      });
      rs.forEach(function(r){tb.appendChild(r)});
    });
  });
});
function wire(n){
  var q=document.getElementById('q'+n),ff=document.getElementById('f'+n),
      fa=document.getElementById('a'+n),fk=document.getElementById('k'+n),
      fe=document.getElementById('e'+n),cnt=document.getElementById('c'+n),
      tbl='#tbl'+n+' tbody tr';
  if(!q)return;
  function flt(){
    var sv=(q.value||'').trim().toLowerCase(),fv=ff?ff.value:'',
        av=fa?parseInt(fa.value||'0',10):0,
        kv=fk?parseInt(fk.value||'0',10):0,
        ev=fe?parseInt(fe.value||'0',10):0,k=0;
    document.querySelectorAll(tbl).forEach(function(tr){
      var ok=(!sv||tr.textContent.toLowerCase().indexOf(sv)>=0)
          && (!fv||tr.dataset.fuel===fv)
          && (!av||parseInt(tr.dataset.adas||'0',10)>=av)
          && (!kv||parseInt(tr.dataset.km||'0',10)<=kv)
          && (!ev||parseInt(tr.dataset.equip||'0',10)>=ev);
      tr.style.display=ok?'':'none'; if(ok)k++;
    });
    cnt.textContent=k+'대 표시 중';
  }
  [q,ff,fa,fk,fe].forEach(function(e){if(e)e.addEventListener('input',flt)});
  [q,ff,fa,fk,fe].forEach(function(e){if(e)e.addEventListener('change',flt)});
  flt();
}
[1,2,3,4,5,6].forEach(wire);
"""


def h(v) -> str:
    return html.escape(str(v if v not in (None, "") else "-"))


def rich(s: str) -> str:
    out = html.escape(s).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    parts = out.split("**")
    if len(parts) > 1:
        out = parts[0] + "".join((f"<b>{p}</b>" if i % 2 else p)
                                for i, p in enumerate(parts[1:], 1))
    return out


def won(x) -> str:
    return f"{int(x) // 10000:,}"


# ── 카드 ─────────────────────────────────────────────────────────────────────
def card(r: dict, rank, mode: str, mom: bool = False) -> str:
    e = r["ev"]
    cls, gtext = GRADE_STYLE[e["grade"]]
    trim_txt = (f" · 트림 <b>{r['trim_rank']}/{r['trim_total']}등급</b>"
                if r["trim_rank"] and r["trim_total"] and r["trim_total"] >= 2 else "")
    rank_html = (f'<span class="rank mom">어머님 매물</span>' if mom
                 else f'<span class="rank">{rank}</span>')
    hi_v = ' class="hi"' if mode == "value" else ""
    hi_s = ' class="hi"' if mode == "sat" else ""
    money = (
        f'<div><span>차값</span><strong>{r["price"]:,}만원</strong></div>'
        f'<div><span>연 유지비(세금+기름)</span><strong>{won(e["running"])}만원</strong></div>'
        f'<div{hi_v}><span>{HOLD_YEARS}년 총지출(차값+유지비)</span>'
        f'<strong>{won(e["total_hold"])}만원</strong></div>'
        f'<div{hi_s}><span>만족 요소(체감장비+안전)</span>'
        f'<strong>{e["sat"]}/12가지</strong></div>')
    pros = "".join(f"<li>{rich(g)}</li>" for g in e["good"][:5])
    cons = "".join(f"<li>{rich(c)}</li>" for c in e["warn"] + e["caution"])
    checks = list(e["checks"])
    if r["fuel"] == "하이브리드":
        checks = HYBRID_CHECKS + checks
    checks_html = "".join(f"<li>{rich(c)}</li>" for c in checks)
    basis = r.get("group_basis") or ""
    if r["price_gap"] is None:
        gap = f'비교 가능한 차가 {r["group_n"]}대뿐이라 시세 비교 어려움'
    elif basis.endswith("트림"):
        gap = (f'같은 차·같은 연식·<b>같은 트림</b> {r["group_n"]}대 중앙값 '
               f'{r["group_median_price"]:,.0f}만원 대비 <b>{r["price_gap"]:+.0%}</b>')
    else:
        gap = (f'<span style="color:#8a5a12">{basis} 기준 {r["price_gap"]:+.0%} — '
               f'<b>트림이 섞여 이 숫자는 믿을 수 없습니다</b></span>')
    return f"""
<div class="card{' mom' if mom else ''}">
<h3>{rank_html}<a class="cname" href="{h(r['url'])}" target="_blank"
rel="noopener nofollow">{h(r['maker'])} {h(r['model'])} {h(r['trim'])}</a>
<span class="badge {cls}">{e['grade']} · {gtext}</span></h3>
<p class="lead">{rich(K.character_of(r['model']))}</p>
<ul class="spec">
<li><b>{h(r['year_month'])}</b> 연식 · 주행 <b>{r['km']:,}km</b></li>
<li>{h(r['accident'])} · {h(e['size'])} · {h(r['seats'])}인승</li>
<li>{h(e['eng']['name'])} · {h(e['pt']['tx'])}</li>
<li>안전장치 <b>{r['adas_n'] or 0}가지</b> · 에어백 {r['airbags'] or 0}종</li>
<li>장비 <b>{r['equip_n'] or 0}/{r['equip_total'] or 24}가지</b>{trim_txt}</li>
<li>{h(r['location'])}</li>
</ul>
<div class="money">{money}</div>
<p style="font-size:.91rem;color:#444">{gap} · 참고: 3년 뒤 예상 감가 {e['dep3']:,}만원
(끝까지 타시면 나가는 돈이 아닙니다)</p>
<p><b>좋은 점</b></p><ul class="pros">{pros or '<li>-</li>'}</ul>
<p><b>걸리는 점</b></p><ul class="cons">{cons or '<li>특별히 걸리는 점이 없습니다</li>'}</ul>
<details><summary>이 차를 보러 가면 꼭 확인할 것 ({len(checks)}가지)</summary>
<div class="dbody"><ul class="chk">{checks_html}</ul></div></details>
<p class="noprint"><a class="btn" href="{h(r['url'])}" target="_blank"
rel="noopener nofollow">K카에서 이 차 보기</a></p>
</div>"""


# ── 추천 5대 ─────────────────────────────────────────────────────────────────
def pick_why(i: dict) -> str:
    e = i["ev"]
    parts = [f"{i['year']}년식 {i['km'] / 10000:.1f}만km",
             f"장비 {i['equip_n'] or 0}/{i['equip_total'] or 24}가지",
             f"안전장치 {i['adas_n'] or 0}가지 전부" if (i["adas_n"] or 0) >= FULL_ADAS
             else f"안전장치 {i['adas_n'] or 0}가지",
             f"연 유지비 {won(e['running'])}만원"]
    if i["fuel"] == "하이브리드":
        parts.append("하이브리드라 기름값이 가장 적게 듭니다")
    if i["accident"] == "무사고":
        parts.append("무사고")
    return " · ".join(parts)


def pick_check(i: dict) -> str:
    e = i["ev"]
    cs = [c for c in e["caution"] if "시세" not in c][:2]
    if not cs:
        return "특별히 걸리는 점이 없습니다. 시승과 진단서 확인만 하시면 됩니다"
    return " · ".join(cs)


def pick_text(picks: list[dict], meta: dict) -> str:
    """문자·카톡으로 붙여 보낼 수 있는 순수 텍스트."""
    lines = [f"[어머님 추천 5대 — K카 직영, {meta.get('collected_at', '')} 기준]"]
    for n, i in enumerate(picks, 1):
        tag = " (하이브리드)" if i["fuel"] == "하이브리드" else ""
        lines.append(f"{n}. [{i.get('pick_label', '')}] {i['maker']} {i['model']} {i['trim']}{tag}")
        lines.append(f"   {i['year_month']} · {i['km']:,}km · {i['price']:,}만원 · "
                     f"{i['accident']} · 장비 {i['equip_n'] or 0}/{i['equip_total'] or 24}"
                     f" · 안전 {i['adas_n'] or 0}/4")
        lines.append(f"   {i['url']}")
    lines.append("※ 가격·매물은 수시로 바뀝니다. 링크에서 직접 확인하세요. "
                 "전체 목록: https://inh1095.github.io/kcar-deals/")
    return "\n".join(lines)


def pick5_html(picks: list[dict], meta: dict, main: list[dict]) -> str:
    pool = pick_pool(main)
    n_hy = sum(1 for i in pool if i["fuel"] == "하이브리드")
    n_hy_ok = sum(1 for i in pool if i["fuel"] == "하이브리드"
                  and (i["adas_n"] or 0) >= PICK_HYB_MIN_ADAS and eligible(i))
    rows = []
    for n, i in enumerate(picks, 1):
        e = i["ev"]
        cls, _g = GRADE_STYLE[e["grade"]]
        hyb = ' <span class="badge" style="background:#e3f0ff;color:#1c4e80">하이브리드</span>' \
            if i["fuel"] == "하이브리드" else ""
        rows.append(f"""
<div class="pick">
<h3><span class="rank">{n}</span><span class="plabel">{h(i.get('pick_label', ''))}</span>
<a class="cname" href="{h(i['url'])}" target="_blank"
rel="noopener nofollow">{h(i['maker'])} {h(i['model'])} {h(i['trim'])}</a>
<span class="badge {cls}">{e['grade']}</span>{hyb}</h3>
<p class="pspec"><b>{h(i['year_month'])}</b> · <b>{i['km']:,}km</b> ·
<b>{i['price']:,}만원</b> · {h(i['accident'])} · {h(i['location'])}</p>
<p><b>왜 이 차</b> — {h(pick_why(i))}. {rich(K.character_of(i['model']).split('. ')[0].rstrip('.'))}.</p>
<p><b>가서 확인할 것</b> — {rich(pick_check(i))}</p>
</div>""")
    txt = pick_text(picks, meta)
    return f"""
<h2 id="pick5">어머님께 드리는 추천 5대</h2>
<p class="lead">어머님이 타시던 <b>K5 크기 이상(중형·준대형 세단)</b>, <b>{PICK_KM // 10000}만km 이하</b>
{len(pool)}대만 놓고 다섯 자리를 정해 뽑았습니다.
<b>가성비 1위</b>(10년 동안 돈이 가장 덜 드는 차) · <b>가심비 1위</b>(장비·안전장치가 가장 많은 차) ·
<b>하이브리드 {PICK_N_HYB}대</b>(하이브리드 중 만족 요소가 많은 순) ·
<b>풀옵션 1위</b>(옵션·안전을 다 갖춘 차 중 돈이 가장 덜 드는 차).
아반떼·니로·셀토스 같은 준중형·소형은 K5보다 작아 뺐습니다.</p>
<p style="font-size:.95rem;color:#555">참고 — 이 예산에서 K5 크기 이상 하이브리드는 {n_hy}대인데
대부분 기본 트림이고, 안전장치 {PICK_HYB_MIN_ADAS}가지 이상에 걸리는 점이 없는 차는
{n_hy_ok}대뿐입니다. 하이브리드는 조용하고 기름값이 적게 드는 대신 <b>같은 값이면 옵션이
적다</b>는 점을 두 대를 나란히 보시며 정하시면 됩니다.</p>
{''.join(rows)}
<div class="box noprint" style="margin-top:14px">
<p style="margin-top:0"><b>문자로 보내기</b> — 아래 내용을 복사해 붙여 넣으시면 됩니다.</p>
<textarea id="pick5txt" readonly rows="{len(picks) * 3 + 2}"
style="width:100%;font-size:.9rem;line-height:1.5;padding:10px;border:1px solid #ccc;
border-radius:8px;font-family:inherit">{h(txt)}</textarea>
<p style="margin-bottom:0"><button class="btn" type="button"
onclick="var t=document.getElementById('pick5txt');t.select();
(navigator.clipboard?navigator.clipboard.writeText(t.value):document.execCommand('copy'));
this.textContent='복사됐습니다'">복사하기</button></p>
</div>
"""


# ── 비교표 ───────────────────────────────────────────────────────────────────
def cmp_table(items: list[dict], tid: str, key: str) -> str:
    """탭별 비교표. 열은 8개만 — 차·트림 / 연식 / 주행 / 차값 / 그 탭의 순위 기준 /
    장비 / 안전 / 등급. 차 이름이 곧 링크다(별도 '보기' 열 없음)."""
    if key == "sat":
        key_th = "<th class='num key'>만족요소<br>(12중)</th>"
    else:
        key_th = f"<th class='num key'>{HOLD_YEARS}년 총지출<br>(만원)</th>"
    head = (f"<tr><th>차 · 트림</th><th>연식</th><th class='num'>주행(km)</th>"
            f"<th class='num'>차값(만)</th>{key_th}"
            f"<th class='num'>장비<br>(24중)</th><th class='num'>안전<br>(4중)</th>"
            f"<th>등급</th></tr>")
    body = []
    for i in items:
        e = i["ev"]
        me = ' class="me"' if i["id"] == MOTHER_PICK else ""
        tag = ' <span style="color:#8a6d1f">★어머님</span>' if i["id"] == MOTHER_PICK else ""
        if key == "sat":
            key_td = f'<td class="num" data-v="{e["sat"]}"><b>{e["sat"]}</b></td>'
        else:
            key_td = (f'<td class="num" data-v="{e["total_hold"]}">'
                      f'<b>{won(e["total_hold"])}</b></td>')
        adas = i["adas_n"] or 0
        body.append(
            f'<tr{me} data-fuel="{h(i["fuel"])}" data-adas="{adas}" '
            f'data-km="{i["km"]}" data-equip="{i["equip_n"] or 0}">'
            f'<td><a class="cname" href="{h(i["url"])}" target="_blank" '
            f'rel="noopener nofollow"><b>{h(i["maker"])} {h(i["model"])}</b></a>{tag}<br>'
            f'<span class="sub">{h(i["trim"])}</span></td>'
            f'<td data-v="{h(i["year_month"]).replace("-", "")}">{h(i["year_month"])}</td>'
            f'<td class="num" data-v="{i["km"]}">{i["km"]:,}</td>'
            f'<td class="num" data-v="{i["price"]}">{i["price"]:,}</td>'
            f'{key_td}'
            f'<td class="num" data-v="{i["equip_n"] or 0}">{i["equip_n"] or 0}</td>'
            f'<td class="num" data-v="{adas}">{"<b>" if adas >= 4 else ""}{adas}'
            f'{"</b>" if adas >= 4 else ""}</td>'
            f'<td><span class="badge {GRADE_STYLE[e["grade"]][0]}">{e["grade"]}</span></td>'
            f'</tr>')
    return (f'<div class="wrap"><table class="cmp" id="{tid}"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def controls(n: int, fuels: list[str] | None) -> str:
    fuel_sel = ""
    if fuels and len(fuels) > 1:
        opts = "".join(f'<option value="{h(f)}">{h(f)}</option>' for f in fuels)
        fuel_sel = f'<select id="f{n}"><option value="">연료 전체</option>{opts}</select>'
    return (f'<div class="ctl noprint">'
            f'<input id="q{n}" type="search" placeholder="차명·트림 검색 (예: 그랜저, 시그니처)">'
            f'{fuel_sel}'
            f'<select id="a{n}"><option value="">안전장치 전체</option>'
            f'<option value="4">4가지 전부</option><option value="3">3가지 이상</option>'
            f'<option value="2">2가지 이상</option></select>'
            f'<select id="k{n}"><option value="">주행거리 전체</option>'
            f'<option value="40000">4만km 이하</option><option value="50000">5만km 이하</option>'
            f'<option value="60000">6만km 이하</option><option value="70000">7만km 이하</option>'
            f'</select>'
            f'<select id="e{n}"><option value="">장비 전체</option>'
            f'<option value="22">22가지 이상</option><option value="20">20가지 이상</option>'
            f'<option value="18">18가지 이상</option></select>'
            f'<span id="c{n}" style="align-self:center;font-size:.9rem;color:#555"></span>'
            f'</div>')


def build(rows, meta, stats) -> str:
    items = []
    for r in rows:
        r = dict(r)
        r["ev"] = evaluate(r, stats)
        items.append(r)

    main = [i for i in items
            if (i["year"] or 0) >= MAIN_YEAR and (i["km"] or 0) <= MAIN_KM]
    hyb = [i for i in main if i["fuel"] == "하이브리드"]
    mom = next((i for i in items if i["id"] == MOTHER_PICK), None)
    picks = pick_top5(main)

    tabs = [
        ("t1", "p1", 1, "풀옵션", "옵션·안전 다 갖춘 차", False,
         "value", rank_full(main),
         f"장비를 <b>{FULL_EQUIP}가지 이상</b>({{}}가지 중) 갖추고 <b>첨단 안전장치 "
         f"{FULL_ADAS}가지를 전부</b> 가진 차만 모았습니다. 어머님이 선호하시는 "
         f"'풀옵션'에 가장 가까운 목록입니다. 옵션은 이미 최상위라 그 안에서 "
         f"<b>{HOLD_YEARS}년 총지출이 적은 순</b>으로 줄였습니다.".format(24),
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 · 장비 {FULL_EQUIP}+ · 안전 {FULL_ADAS}종"),
        ("t2", "p2", 2, "가성비", "돈이 가장 덜 나가는 차", False,
         "value", rank_value(main),
         f"차값이 싼 차가 아니라 <b>차값 + 유지비를 {HOLD_YEARS}년 합쳐서</b> 가장 적게 "
         f"나가는 차입니다. 차값이 300만원 싸도 유지비가 매년 50만원 더 들면 "
         f"{HOLD_YEARS}년이면 오히려 200만원 손해입니다.",
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 · 전체 연료"),
        ("t3", "p3", 3, "가심비", "만족을 사는 차", False,
         "sat", rank_satisfaction(main),
         "매일 손에 닿는 장비와 안전장치가 가장 많은 차입니다. 만족 요소가 같다면 "
         "총지출이 적은 차를 앞에 뒀습니다.",
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 · 전체 연료"),
        ("t4", "p4", 4, "하이브리드 가성비", "하이브리드 중 돈이 덜 드는 차", True,
         "value", rank_value(hyb),
         "하이브리드만 모아 <b>같은 가성비 기준</b>으로 줄였습니다. 하이브리드는 원래 "
         "기름값이 적게 들어 유지비 항목에서 크게 유리합니다.",
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 · 하이브리드만"),
        ("t5", "p5", 5, "하이브리드 가심비", "하이브리드 중 만족이 큰 차", True,
         "sat", rank_satisfaction(hyb),
         "하이브리드만 모아 <b>같은 가심비 기준</b>으로 줄였습니다. 조용함과 낮은 기름값에 "
         "장비까지 갖춘 차입니다.",
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 · 하이브리드만"),
        ("t6", "p6", 6, "전체 비교", "조건 통과 전부", False,
         "value", sorted(main, key=lambda i: i["ev"]["total_hold"]),
         "하한선을 두지 않은 전체 목록입니다. 위 필터로 주행거리·장비·안전장치를 "
         "직접 좁혀 보실 수 있습니다.",
         f"{MAIN_YEAR}년+ · {MAIN_KM//10000}만km 이하 전부"),
    ]

    radios = "".join(f'<input type="radio" name="tab" id="{t[0]}"'
                     f'{" checked" if n == 0 else ""}>' for n, t in enumerate(tabs))
    def _label(t):
        cls = ' class="hyb"' if t[5] else ''
        return f'<label for="{t[0]}"{cls}>{t[3]}<small>{t[4]}</small></label>'

    labels = "".join(_label(t) for t in tabs)

    panels = []
    for tid, pid, num, name, _sub, is_hyb, mode, ranked, intro, scope in tabs:
        top = pick_diverse(ranked)
        fuels = sorted({i["fuel"] for i in ranked}) if not is_hyb else None
        note = ""
        if is_hyb:
            note = (f'<div class="box tipbox" style="margin-top:0"><p style="margin:0">'
                    f'<b>이 조건에서 하이브리드는 {len(hyb)}대입니다.</b> '
                    f'풀옵션(장비 {FULL_EQUIP}가지+·안전 {FULL_ADAS}종) 조건까지 만족하는 '
                    f'하이브리드는 그중 '
                    f'{sum(1 for i in hyb if is_full_option(i))}대뿐입니다 — '
                    f'하이브리드와 풀옵션은 이 예산에서 거의 겹치지 않습니다.'
                    f'</p></div>')
        mom_here = (mom is not None and mom in ranked)
        mom_note = ""
        if mom is not None and is_hyb and not mom_here:
            mom_note = ('<p style="font-size:.93rem;color:#8a5a12">'
                        '어머님이 보내주신 아이오닉은 이 탭의 하한선(안전장치·장비)에 걸려 '
                        '순위 목록에는 없습니다. 위 전용 칸과 아래 전체 비교 탭에서 보실 '
                        '수 있습니다.</p>')
        panels.append(f"""
<div class="panel" id="{pid}">
<h3 style="margin-top:0">{name}</h3>
<p style="font-size:.9rem;color:#666;margin-top:-.4em">대상: <b>{scope}</b> ·
{len(ranked)}대</p>
{note}
<p class="lead">{rich(intro)}</p>
{mom_note}
{''.join(card(r, n, mode) for n, r in enumerate(top, 1))}
<h3>{name} 기준 전체 {len(ranked)}대</h3>
<p style="font-size:.93rem;color:#555"><b>차 이름을 누르면 K카 매물 페이지가 새 창으로
열립니다.</b> 표 머리글을 누르면 그 항목으로 다시 정렬됩니다.</p>
{controls(num, fuels)}
{cmp_table(ranked, f'tbl{num}', mode)}
</div>""")

    # 어머님 매물 전용 칸 ---------------------------------------------------
    mom_html = ""
    NIRO_CNT = ((stats.get("models") or {}).get("니로", {}) or {}).get("count", 0)
    KONA_CNT = ((stats.get("models") or {}).get("코나", {}) or {}).get("count", 0)
    if mom is not None:
        peers = [i for i in items
                 if i["model"] == mom["model"] and abs((i["year"] or 0) - (mom["year"] or 0)) <= 1]
        def _peer_row(p):
            is_mom = p["id"] == mom["id"]
            cls = ' class="me"' if is_mom else ''
            tag = " ★어머님 매물" if is_mom else ""
            return (f'<tr{cls}>'
                    f'<td><a class="cname" href="{h(p["url"])}" target="_blank" '
                    f'rel="noopener nofollow">{h(p["trim"])}</a>{tag}</td>'
                    f'<td>{h(p["year_month"])}</td><td class="num">{p["km"]:,}</td>'
                    f'<td class="num">{p["price"]:,}</td><td>{h(p["accident"])}</td>'
                    f'<td class="num">{p["equip_n"] or 0}</td>'
                    f'<td class="num">{p["adas_n"] or 0}</td></tr>')

        peer_rows = "".join(_peer_row(p)
                            for p in sorted(peers, key=lambda x: -x["price"]))
        mom_html = f"""
<h2>어머님이 보내주신 매물</h2>
<div class="mombox">
<p style="margin-top:0;color:#8a5a12"><b>먼저 알려드릴 것</b> — 이 차는
<b>{mom['year']}년식 · {mom['km']:,}km</b>라서 새로 좁힌 조건
(<b>{MAIN_YEAR}년 이후 · {MAIN_KM:,}km 이하</b>)을 <b>두 가지 모두 넘습니다.</b>
그래서 아래 탭 목록에는 없고 이 칸에서만 보실 수 있습니다.
(수집 시점 기준 <b>아직 판매 중</b>입니다.)
조건을 올리면 더 새롭고 덜 달린 차를 볼 수 있지만,
<b>같은 예산에서는 트림이 낮아지는 절충이 생깁니다</b>(아래 표 참고).</p>
<p style="margin-top:0"><b>결론부터</b> — 하이브리드로는 <b>좋은 선택</b>입니다.
연 유지비가 {won(mom['ev']['running'])}만원으로 이 목록에서 가장 낮은 수준이고
무사고입니다. 다만 <b>확인하고 가셔야 할 것이 두 가지</b> 있습니다.</p>
<p><b>1. 같은 차의 윗급 트림이 더 싸게 있습니다.</b> 아이오닉 트림은 아래에서
<b>I → N → Q</b> 순서인데, 어머님 매물은 <b>N 트림 {mom['price']:,}만원</b>입니다.
같은 세대에 <b>Q 트림(윗급)이 1,610만원</b>으로 60만원 더 싸게 있습니다.
주행거리는 그쪽이 7,000km 더 많습니다. 두 대를 나란히 보시고 결정하세요.</p>
<p><b>2. 자동 긴급제동이 옵션 목록에 없습니다.</b> 후측방경보·차선이탈경보·
스마트크루즈는 있는데, 사고를 가장 많이 줄여 주는 자동 긴급제동이 빠져 있습니다.
차에서 직접 확인해 보시고, 없다면 이 기능이 있는 차와 꼭 비교해 보세요.</p>
<p style="font-size:.93rem;color:#666"><b>참고 — 아이오닉은 드문 차입니다.</b>
K카 직영 재고 전체에서 아이오닉(전기차 제외)은 <b>{mom['ev']['stock']}대</b>,
그중 이 세대(‘{h(mom['model'])}’)는 <b>{mom['ev']['gen_stock']}대</b>뿐입니다.
부품을 주문해야 할 수 있고 동네 정비소가 안 만져 봤을 수 있습니다.
오래 타실 계획이면 치명적이지는 않지만 알고 계시는 게 좋습니다.
(같은 하이브리드인 니로는 {NIRO_CNT}대, 코나는 {KONA_CNT}대입니다.)</p>
<h3>같은 아이오닉끼리 비교 (같은 세대, 연식 ±1년)</h3>
<div class="wrap"><table class="simple"><thead><tr><th>트림</th><th>연식</th>
<th class="num">주행(km)</th><th class="num">차값(만)</th><th>사고</th>
<th class="num">장비</th><th class="num">안전</th></tr></thead>
<tbody>{peer_rows}</tbody></table></div>
</div>
{card(mom, None, 'value', mom=True)}
"""

    dist: dict[str, int] = {}
    for i in items:
        dist[i["ev"]["grade"]] = dist.get(i["ev"]["grade"], 0) + 1
    dist_rows = "".join(
        f"<tr><td><span class='badge {GRADE_STYLE[g][0]}'>{g}</span></td>"
        f"<td>{GRADE_STYLE[g][1]}</td><td class='num'>{dist.get(g, 0)}대</td></tr>"
        for g in ("안심", "괜찮음", "따져보기", "주의"))

    rj = meta.get("rejects", {})
    rej_rows = "".join(f"<tr><td>{h(k)}</td><td class='num'>{v:,}대</td></tr>"
                       for k, v in sorted(rj.items(), key=lambda x: -x[1]))

    fuel_guide = "".join(
        f"<h3>{h(name)}</h3><p>{rich(v['good'])}</p>"
        + (("<p><b>확인할 점</b></p><ul class='chk'>"
            + "".join(f"<li>{rich(w)}</li>" for w in v["watch"]) + "</ul>")
           if v["watch"] else "")
        + f"<p style='color:#555;font-size:.92rem'>알맞은 경우: {h(v['suits'])}</p>"
        for name, v in K.FUEL_NOTES.items())

    channels = "".join(
        f"<h3>{h(n)}{' — 이 페이지가 쓰는 곳' if used else ''}</h3><p>{rich(d)}</p>"
        f"<p style='font-size:.88rem;color:#666'>이 정리에서의 상태: <b>{h(st)}</b><br>"
        f"<a href='{h(u)}' target='_blank' rel='noopener nofollow'>{h(u)}</a></p>"
        for n, u, d, st, used in CHANNELS)

    look = "".join(
        f"<h3>{h(n)}</h3><p>{rich(d)}<br><a href='{h(u)}' target='_blank' "
        f"rel='noopener nofollow'>{h(u)}</a></p>" for n, u, d in LOOKUPS)

    chk_html = "".join(
        f"<details {'open' if idx == 1 else ''}><summary>{idx}. {h(t)}</summary>"
        f"<div class='dbody'><ol class='chk'>"
        + "".join(f"<li>{rich(l)}</li>" for l in lines) + "</ol></div></details>"
        for idx, (t, lines) in enumerate(FIELD_CHECKLIST, 1))
    hyb_chk = "".join(f"<li>{rich(x)}</li>" for x in HYBRID_CHECKS)

    c = meta.get("conditions", {})
    pool = meta.get("comparable_pool", 0)
    n_hyb_main = sum(1 for i in hyb if (i["year"] or 0) >= MAIN_YEAR)
    cap_man = GASIMBI_RUN_CAP // 10000

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>어머님을 위한 중고차 고르기 — 가성비 · 가심비 · 하이브리드</title>
<style>{CSS}</style>
</head><body><main>

<h1>어머님을 위한 중고차 고르기</h1>
<p class="lead">K카(kcar.com) 직영 재고를 <b>한 대도 빼지 않고 전부</b> 훑어
조건에 맞는 <b>{len(items)}대</b>를 골랐습니다. <b>바로 아래 추천 5대</b>부터 보시고,
더 보고 싶으시면 기준별 <b>{len(tabs)}개 탭</b>을 눌러 비교해 보세요.</p>

<div class="top">
<p><b>수집 일시</b> {h(meta.get('collected_at'))} · <b>출처</b> K카(kcar.com) 직영 매물</p>
<p>직영 재고 <b>{meta.get('collected', 0):,}대 전체</b>를 받아 <b>{pool:,}대</b>를
시세 기준으로 쓰고, 조건에 맞는 <b>{len(items)}대</b>를 골랐습니다.
그중 <b>하이브리드는 {len(hyb)}대</b>입니다.</p>
<p>조건: <b>5인승 · 현대·기아(제네시스 포함) · 차량가 {c.get('budget', 2200):,}만원 이하 ·
{MAIN_KM:,}km 이하 · 무사고 또는 단순수리</b>.
SUV는 셀토스 크기까지만(투싼·스포티지·싼타페·쏘렌토 제외), 미니밴·카니발·경차·화물·
승합·렌터카는 제외했습니다. <b>연식 {MAIN_YEAR}년 이후</b>이며, 하이브리드 탭도 같은 조건입니다.
표 위 필터로 주행거리(4~7만km)와 장비 개수를 더 좁혀 보실 수 있습니다.</p>
<p style="font-size:.88rem">{h(DISCLAIMER)}</p>
</div>

{pick5_html(picks, meta, main)}

{mom_html}

<div class="box tipbox">
<h3 style="margin-top:0">탭이 무엇이 다른가</h3>
<table class="simple"><thead><tr><th>탭</th><th>보는 숫자</th><th>대상</th></tr></thead><tbody>
<tr><td><b>풀옵션</b></td><td>장비 {FULL_EQUIP}가지 이상 + 안전장치 {FULL_ADAS}가지 전부<br>
<span class="sub">그 안에서 총지출 적은 순</span></td><td>{MAIN_YEAR}년 이후 전체 연료</td></tr>
<tr><td><b>가성비</b></td><td>{HOLD_YEARS}년 총지출 = 차값 + 유지비×{HOLD_YEARS}<br>
<span class="sub">적은 순</span></td><td>{MAIN_YEAR}년 이후 전체 연료</td></tr>
<tr><td><b>가심비</b></td><td>만족 요소 = 체감 장비 8 + 안전장치 4<br>
<span class="sub">많은 순, 같으면 총지출 적은 순</span></td>
<td>{MAIN_YEAR}년 이후 전체 연료</td></tr>
<tr><td><b>하이브리드 가성비</b></td><td>위와 같은 총지출 기준</td>
<td>{HYBRID_YEAR}년 이후 하이브리드</td></tr>
<tr><td><b>하이브리드 가심비</b></td><td>위와 같은 만족 요소 기준</td>
<td>{HYBRID_YEAR}년 이후 하이브리드</td></tr>
<tr><td><b>전체 비교</b></td><td>총지출 순 (하한선 없음)</td><td>{MAIN_YEAR}년 이후 · {MAIN_KM:,}km 이하 전부 {len(main)}대</td></tr>
</tbody></table>
<p>다섯 개 순위 탭은 모두 <b>안전장치 {MIN_ADAS}가지 이상, 장비 {MIN_EQUIP}가지 이상,
경고 없는 차</b>만 올립니다. 가심비 탭은 추가로 <b>연 유지비 {cap_man}만원 이하</b>
(‘값도 적당’ 조건)입니다.</p>
<p><b>감가는 어느 탭에서도 순위에 쓰지 않았습니다.</b> 끝까지 타실 계획이라면
중간 시세는 통장에서 나가는 돈이 아니기 때문입니다. 참고로만 카드에 적어 두었습니다.</p>
</div>

<div class="box warnbox">
<h3 style="margin-top:0">이 정리로 알 수 없는 것</h3>
<p>K카 규칙(robots.txt)이 각 차의 상세 페이지 자동 조회를 막고 있어
<b>상세 페이지는 한 건도 열지 않았습니다.</b> 그래서 <b>보험 수리 이력(침수·전손 포함),
소유자 변경 횟수, K카가 표시하는 정확한 총 구매비용, 남은 보증 기간</b>은 없습니다.
아래 '계약 전에 꼭 조회할 3곳'과 현장에서 직접 확인하셔야 합니다.
<b>시승과 진단서 확인은 어떤 경우에도 생략하면 안 됩니다.</b></p>
</div>

<h2>기준을 골라 비교하세요</h2>
<div class="tabs">
{radios}
<div class="tabbar">{labels}</div>
<div class="panels">{''.join(panels)}</div>
</div>

<h2>"최근 연식이면 옵션이 많다"가 이 예산에서는 반대입니다</h2>
<p class="lead">최신 연식일수록 최신 시스템이 많다는 건 <b>신차 기준</b>으로는 맞습니다.
그런데 <b>예산을 {c.get('budget', 2500):,}만원으로 고정</b>하면 이야기가 뒤집힙니다.
직영 재고에서 실제로 계산한 결과입니다.</p>
<div class="box warnbox">
<table class="simple"><thead><tr><th>연식</th><th class="num">대수</th>
<th class="num">장비 중앙값</th><th class="num">안전 4종 비율</th>
<th class="num">차값 중앙값</th></tr></thead><tbody>
<tr><td>2019년</td><td class="num">186</td><td class="num">18.0/24</td>
<td class="num">41%</td><td class="num">1,590만</td></tr>
<tr><td><b>2020년</b></td><td class="num">142</td>
<td class="num"><b style="color:#1c5c38">19.0/24</b></td>
<td class="num"><b style="color:#1c5c38">48%</b></td><td class="num">1,855만</td></tr>
<tr><td>2021년</td><td class="num">146</td><td class="num">18.0/24</td>
<td class="num">47%</td><td class="num">1,965만</td></tr>
<tr><td>2022년</td><td class="num">124</td><td class="num">18.0/24</td>
<td class="num">45%</td><td class="num">2,050만</td></tr>
<tr><td>2023년</td><td class="num">42</td>
<td class="num"><b style="color:#932018">15.0/24</b></td>
<td class="num">35%</td><td class="num">2,125만</td></tr>
<tr><td>2025년</td><td class="num">4</td>
<td class="num"><b style="color:#932018">12.5/24</b></td>
<td class="num"><b style="color:#932018">0%</b></td><td class="num">2,385만</td></tr>
</tbody></table>
<p><b>왜 이런가</b> — 예산이 정해져 있으면 <b>연식이 최신일수록 하위 트림(이른바 '깡통')만
살 수 있습니다.</b> 2025년식 2,385만원짜리는 신차 가격대의 최하 트림이고,
2020년식 1,855만원이면 같은 돈으로 <b>상위 트림</b>을 살 수 있습니다.</p>
<p><b>그래서 '최신 시스템·풀옵션'을 원하시면 연식보다 트림을 보셔야 합니다.</b>
어머님이 원하시는 것에 가장 가까운 건 <b>맨 앞의 '풀옵션' 탭</b>입니다
(장비 {FULL_EQUIP}가지 이상 + 안전장치 {FULL_ADAS}가지 전부).</p>
</div>
<div class="box tipbox">
<p style="margin-top:0"><b>한 가지 더 — 풀옵션과 하이브리드는 거의 겹치지 않습니다.</b>
이 예산에서 풀옵션 조건을 만족하는 차는 대부분 중대형 세단(그랜저·K5·K8)이고,
하이브리드는 대체로 중·하위 트림입니다. 둘 중 무엇을 앞에 둘지 정하셔야 합니다.</p>
<p><b>하이브리드를 우선하시면</b> 조용함과 낮은 기름값을 얻고 옵션은 조금 양보하게 됩니다.
<b>풀옵션을 우선하시면</b> 옵션은 다 갖추지만 기름값이 더 듭니다.
두 탭을 나란히 눌러 보시고 결정하세요.</p>
</div>

<h2>하이브리드를 보실 때 꼭 확인할 것</h2>
<p class="lead">어머님이 하이브리드에 좋은 경험이 있으시다면 그 판단이 맞습니다.
<b>시내와 정체 구간에서는 하이브리드가 가장 편하고 기름값도 가장 적게 듭니다.</b>
다만 일반 차와 다른 점이 있어 볼 것이 조금 다릅니다.</p>
<div class="box tipbox"><ul class="chk">{hyb_chk}</ul></div>
<p style="font-size:.93rem;color:#555">이 목록의 하이브리드 {len(hyb)}대의 연 유지비는
평균적으로 가솔린차보다 낮습니다. 하이브리드 탭의 '연 유지비' 열을 다른 탭과 비교해 보세요.</p>

<h2>표에 나오는 말 풀이</h2>
<div class="box" style="font-size:.95rem">
<p style="margin:.3em 0"><b>{HOLD_YEARS}년 총지출</b> — 차값 + (자동차세 + 기름값) ×
{HOLD_YEARS}년. 기름값은 1년 {ANNUAL_KM:,}km 기준입니다. <b>감가는 넣지 않았습니다.</b></p>
<p style="margin:.3em 0"><b>만족 요소</b> — 체감 장비 8가지(통풍시트·전동시트·무선충전·
어라운드뷰·헤드업디스플레이·선루프·스마트크루즈·뒷좌석 열선) + 안전장치 4가지
= 최대 12가지 중 몇 개인지입니다. 전 차량에 다 있는 항목은 구분이 안 되므로 세지 않았습니다.</p>
<p style="margin:.3em 0"><b>트림 등급</b> — <b>1/7</b>은 그 세대 7개 트림 중 가장 위
등급이라는 뜻입니다. 숫자가 작을수록 좋은 트림입니다.</p>
<p style="margin:.3em 0"><b>안전장치</b> — 자동긴급제동·차선이탈경보·후측방경보·
스마트크루즈 4가지 중 몇 개인지. <b>4가 최고</b>입니다.</p>
</div>

<h2>왜 감가를 빼고 유지비를 보는가</h2>
<p class="lead">감가는 <b>팔 때만 생기는 손해</b>입니다. 끝까지 타실 거라면
중간에 시세가 얼마인지는 통장에서 나가는 돈이 아닙니다.
반대로 세금·기름값은 <b>타는 동안 실제로 나갑니다.</b></p>
<div class="box warnbox">
<p style="margin-top:0">직영 재고에서 배기량별로 {HOLD_YEARS}년 유지비를 계산했습니다.
끝까지 타실 거라면 이 표가 차값보다 중요합니다.</p>
<table class="simple"><thead><tr><th>배기량</th>
<th class="num">연 유지비</th><th class="num">{HOLD_YEARS}년 누적</th></tr></thead><tbody>
<tr><td>1,600cc 이하</td><td class="num">162만원</td>
<td class="num"><b style="color:#1c5c38">1,622만원</b></td></tr>
<tr><td>1,600~2,000cc</td><td class="num">212만원</td><td class="num">2,119만원</td></tr>
<tr><td>2,000~2,600cc</td><td class="num">237만원</td><td class="num">2,374만원</td></tr>
<tr><td>2,600cc 초과</td><td class="num">280만원</td>
<td class="num"><b style="color:#932018">2,799만원</b></td></tr>
</tbody></table>
<p><b>1,600cc와 2,600cc 초과의 {HOLD_YEARS}년 차이는 1,177만원</b>으로 차값 차이보다
큰 경우가 많습니다. <b>트림은 높이고 배기량은 낮추는 조합</b>이 가장 유리하며,
하이브리드는 배기량이 작고 기름값이 적어 이 기준에서 가장 좋습니다.</p>
</div>
<div class="box tipbox">
<p style="margin-top:0"><b>'많이 떨어진 비싼 차'는 어떨까</b> — 재고 {pool:,}대에서
같은 세대 인접 연식 시세를 비교하면, 차령이 오래되면 감가액은 줄어듭니다
(3년차 218만원 → 10년차 40만원). 그런데 <b>지금 시세가 높은 차는 이미 많이 떨어진
뒤에도 계속 큰 금액으로 떨어집니다</b>(차령 3~6년: 1,500~2,500만원대 연 4.4%,
2,500~4,000만원대 연 9.0%, 4,000만원 이상 연 10.3%).
<b>끝까지 타실 거라면 감가는 무시하고 위 유지비 표만 보시면 됩니다.</b></p>
</div>

<h2>어디서 사는 게 좋은가</h2>
<p class="lead">같은 차라도 파는 곳에 따라 진단 기준·보증·환불 조건이 크게 다릅니다.</p>
<div class="box">{channels}</div>
<div class="box tipbox">
<p style="margin-top:0"><b>안전을 가장 앞에 두신다면</b> 값을 조금 더 쓰셔도
<b>제조사 인증중고차(현대·기아 공식)</b>가 가장 확실합니다. 그다음이
<b>K카 같은 직영</b>, 마지막이 <b>딜러 매물 플랫폼</b>(엔카·KB차차차)입니다.</p>
<p><b>이 페이지의 차는 전부 K카 직영 매물입니다.</b> 엔카는 사이트 규칙이 매물 데이터의
자동 조회를 금지해 수집하지 않았고, 현대 인증중고차는 규칙상 허용되지만 사이트가
자동 조회를 거부해 받지 못했습니다. 두 곳은 위 링크로 직접 보시는 것이 맞습니다.</p>
</div>

<h2>연료는 이렇게 고르세요</h2>
<div class="box">{fuel_guide}</div>

<h2>보러 가실 때 쓰는 체크리스트</h2>
<p class="lead">순서대로 하시면 됩니다. 인쇄하시거나 휴대폰으로 열어두고 하나씩
확인하세요. <b>아래를 다 지키면 대부분의 나쁜 차는 걸러집니다.</b>
하이브리드는 위의 '하이브리드를 보실 때 꼭 확인할 것'을 함께 보세요.</p>
<p class="noprint"><button class="btn" onclick="window.print()">이 페이지 인쇄하기</button>
<a class="btn alt" href="#red">'이런 차는 사지 마세요'부터 보기</a></p>
{chk_html}

<h2 id="red">이런 차는 사지 마세요</h2>
<p class="lead">아래 중 <b>하나라도</b> 해당되면 값이 아무리 싸도 넘어가세요.</p>
<div class="box warnbox"><ul class="chk">
{''.join(f'<li>{rich(x)}</li>' for x in RED_FLAGS)}
</ul></div>

<h2>계약 전에 꼭 조회할 3곳</h2>
<p class="lead">차대번호만 있으면 집에서 조회할 수 있습니다.</p>
<div class="box">{look}</div>

<h2>전체 {meta.get('collected', 0):,}대에서 어떻게 {len(items)}대가 남았나</h2>
<table class="simple"><thead><tr><th>빠진 이유</th><th class="num">대수</th></tr></thead>
<tbody>{rej_rows}
<tr><td><b>조건 통과</b></td><td class="num"><b>{len(items):,}대</b></td></tr>
</tbody></table>

<h2>등급 표시</h2>
<p class="lead">점수가 아니라 <b>확인할 점이 몇 가지인지</b>로 나눴습니다.</p>
<table class="simple" id="t-grade"><thead><tr><th>등급</th><th>뜻</th>
<th class="num">대수</th></tr></thead><tbody>{dist_rows}</tbody></table>
<p class="noprint" style="margin-top:20px">
<a class="btn alt" href="all.html">시세·점수까지 보는 분석용 표</a>
<a class="btn alt" href="report.md">분석 리포트 원문</a></p>

<footer>
<p><b>출처</b> K카(kcar.com) 직영 매물 목록. 직영 재고 {meta.get('collected', 0):,}대 전체
수집, 수집 {h(meta.get('collected_at'))}. 사진은 싣지 않았고 각 매물의 K카 페이지로
연결만 합니다. K카 규칙에 따라 상세 페이지는 조회하지 않았고, 요청은 순차·1.8초
간격으로 보냈습니다. 하이브리드 탭만 연식 하한을 {HYBRID_YEAR}년으로 낮췄습니다
({MAIN_YEAR}년 이후 하이브리드가 {n_hyb_main}대뿐이기 때문입니다).</p>
<p><b>근거</b> 엔진이 어느 차에 쓰였고 리콜이 있었는지는 공개된 엔진 자료(위키피디아
Hyundai Theta / R engine)와 미국 집단소송 합의 공지에서 확인했습니다.
차종별 물량·연식별 시세·감가는 위 재고 전체에서 직접 계산했습니다.
자동차세·기름값은 <b>대략값</b>이며 실제 고지액과 주행 습관에 따라 달라집니다
(아이오닉은 전용 해치백으로 공기저항이 작아 같은 1.6 하이브리드보다 연비를 높게 잡았습니다).
보험료와 수리비는 사람·차마다 달라 넣지 않았습니다. 그 밖의 점검 항목은 널리 알려진
정비 상식으로, <b>특정 차량에 결함이 있다는 뜻이 아닙니다.</b></p>
<p>{h(DISCLAIMER)}</p>
</footer>
</main>
<script>{CMP_JS}</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/listings.csv")
    ap.add_argument("--out", default="docs/index.html")
    args = ap.parse_args()
    rows, meta, stats = load(args.csv)
    missing = K.missing_fuel_economy()
    if missing:
        print(f"경고: 연비 표에 빠진 엔진 {missing} — 기름값이 0으로 계산된다")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(build(rows, meta, stats))
    items = [dict(r, ev=evaluate(dict(r), stats)) for r in rows]
    main_i = [i for i in items
              if (i["year"] or 0) >= MAIN_YEAR and (i["km"] or 0) <= MAIN_KM]
    hyb_i = [i for i in main_i if i["fuel"] == "하이브리드"]
    print(f"{args.out} 생성 — CSV {len(rows)}대 / 탭 대상({MAIN_YEAR}년+·{MAIN_KM//10000}만km) {len(main_i)}대 / "
          f"풀옵션 {len(rank_full(main_i))} / 가성비 {len(rank_value(main_i))} / "
          f"가심비 {len(rank_satisfaction(main_i))} / "
          f"하이브리드 가성비 {len(rank_value(hyb_i))} / "
          f"하이브리드 가심비 {len(rank_satisfaction(hyb_i))} / "
          f"추천 5대 {[(i['pick_label'], i['id']) for i in pick_top5(main_i)]}")


if __name__ == "__main__":
    main()
