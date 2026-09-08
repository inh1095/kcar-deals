#!/usr/bin/env python3
"""data/listings.csv + data/market_stats.json → docs/index.html (어머님용 고르기 안내)

점수로 줄 세우지 않는다. 매물마다 엔진·변속기·연료·주행거리·차급·재고량을 따져
'무엇을 확인해야 하는지'를 문장으로 만들고, 확인할 점이 적은 순서로 보여준다.

    python3.11 build_guide.py

판단 근거는 넷뿐이다 (커뮤니티 글에 의존하지 않는다)
1. 확인된 사실   — 엔진별 리콜 이력 (출처 명시)
2. 구조적 사실   — 터보·건식클러치가 붙으면 부품이 늘고 소모품이 생긴다
3. 전체 재고 통계 — K카 직영 재고 전체에서 뽑은 차종별 물량과 연식별 시세
4. 계산값       — 자동차세, 연간 유류비

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

TOP_PICKS = 3
SECTION_N = 3
LIST_N = 40

# 재고량 기준 (K카 직영 전체 재고에서의 차종 물량)
COMMON_STRONG = 100      # 이 이상이면 아주 흔한 차
COMMON_OK = 30
RARE = 15                # 이 미만이면 드문 차

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
def load(csv_path="data/listings.csv"):
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    d = os.path.dirname(csv_path) or "."
    meta = _json(os.path.join(d, "meta.json"))
    stats = _json(os.path.join(d, "market_stats.json"))
    for r in rows:
        for k in ("km", "price", "year", "cc", "seats", "group_n", "total_cost_est",
                  "group_median_km"):
            r[k] = int(float(r[k])) if r.get(k) not in ("", None) else None
        for k in ("price_gap", "km_gap", "group_median_price"):
            r[k] = float(r[k]) if r.get(k) not in ("", None) else None
        r["opt"] = [o for o in (r.get("options") or "").split("|") if o]
    return rows, meta, stats


def _json(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


# ── 매물 평가 ────────────────────────────────────────────────────────────────
def evaluate(r: dict, stats: dict) -> dict:
    """경고·주의·좋은 점과 확인 항목을 만든다. 숫자 점수는 만들지 않는다."""
    pt = K.identify_powertrain(r["model"], r["trim"], r["fuel"], r["cc"])
    eng = K.ENGINES[pt["engine"]]
    size = K.size_of(r["model"])
    sn = K.SIZE_NOTES[size]
    fuel_note = K.FUEL_NOTES.get(r["fuel"], K.FUEL_NOTES["가솔린"])

    warn: list[str] = []
    caution: list[str] = []
    good: list[str] = []
    checks: list[str] = []

    # 1) 엔진 — 확인된 리콜 이력 + 구조적 복잡도 -----------------------------
    if eng["theta2"]:
        warn.append("엔진이 세타2 GDI 계열입니다 (리콜·보증 확인 필수)")
        checks.append(K.THETA2_NOTICE)
    if eng["nature"] == "자연흡기" and pt["tx"] in (K.TX_AUTO, K.TX_IVT) and not eng["theta2"]:
        good.append("터보도 DCT도 없습니다. 붙어 있는 부품이 가장 적어 "
                    "고장 날 수 있는 곳 자체가 적습니다")
    if eng["nature"] == "터보":
        caution.append("터보 엔진입니다")
        checks.append("터보는 터보차저·인터쿨러·배기 밸브가 추가로 붙습니다. "
                      "부품이 늘어난 만큼 손볼 곳도 늘어납니다. 시동 직후 '쉬익' 하는 큰 소리나 "
                      "흰 연기가 나는지 보고, 시동 걸고 바로 세게 밟지 않는 습관이 필요합니다.")
    if "GDI" in eng["name"] or "직분사" in eng["name"]:
        checks.append("직분사(GDI) 엔진은 엔진오일이 조금씩 줄어드는 경우가 보고됩니다. "
                      "오일 게이지를 뽑아 양과 색을 보고, 오일을 보충한 이력이 있는지 물어보세요.")

    # 2) 변속기 -------------------------------------------------------------
    if pt["tx"] == K.TX_DCT_DRY:
        caution.append("변속기가 건식 DCT입니다")
        checks.append("건식 DCT는 수동변속기의 클러치를 자동으로 여닫는 구조입니다. "
                      "클러치가 소모품이라 갈아야 할 때가 오고, 가다 서다 하는 길에서 "
                      "울컥거림이 보고됩니다. **시승할 때 반드시 막히는 길이나 오르막에서 "
                      "시속 10~30km로 천천히 가보세요.** 울컥거림이 거슬리면 그 차는 "
                      "피하시는 게 낫습니다. 시내 위주로 다니신다면 특히 중요합니다.")
    else:
        good.append(f"변속기가 {pt['tx']}입니다 — {K.TX_EXPLAIN[pt['tx']]}")

    # 3) 연료 ---------------------------------------------------------------
    if r["fuel"] == "디젤":
        caution.append("디젤입니다")
    elif r["fuel"] == "하이브리드":
        caution.append("하이브리드 배터리 보증을 확인해야 합니다")
        good.append("기름값이 가장 적게 들고 저속에서 매우 조용합니다")
    elif r["fuel"] == "LPG":
        caution.append("LPG 연료통 검사 기간을 확인해야 합니다")
        good.append("연료비가 가솔린의 절반 수준입니다")
    checks += fuel_note["watch"]

    # 4) 사고 ---------------------------------------------------------------
    if r["accident"] == "무사고":
        good.append("K카 진단 기준 무사고입니다")
    else:
        caution.append("K카 진단 기준 '단순수리' 이력이 있습니다")
        checks.append("'단순수리'는 문·펜더처럼 볼트로 붙는 겉판을 교환했다는 뜻이 대부분이고, "
                      "차의 뼈대(프레임)를 건드린 것과는 다릅니다. 하지만 **어디를 얼마나 "
                      "수리했는지는 진단서에 나와 있으니 반드시 종이로 받아 보세요.** "
                      "뼈대 수리나 여러 곳 동시 수리가 적혀 있으면 값이 싸도 피하세요.")

    # 5) 주행거리·연식 ------------------------------------------------------
    if r["km"] >= 115000:
        warn.append(f"주행거리가 {r['km']:,}km로 많습니다")
    elif r["km"] >= 100000:
        caution.append(f"주행거리 {r['km']:,}km — 10만km 정비 시점입니다")
    if r["km"] < 80000:
        good.append(f"주행거리가 {r['km']:,}km로 짧습니다")
    if r["accident"] != "무사고" and r["km"] >= 110000:
        warn.append("수리 이력과 많은 주행거리가 겹칩니다")
    checks += K.mileage_notes(r["km"])
    checks += K.age_notes(r["year"])

    # 6) 시세 위치 (전체 재고 기준) ------------------------------------------
    # 비교군이 정확한 트림까지 맞지 않으면 시세차를 주장하지 않는다.
    # 트림이 섞인 그룹의 중앙값은 하위 트림 매물을 실제보다 싸 보이게, 상위 트림 매물을
    # 비싸 보이게 만든다(예: 쏘나타 DN8 최하 트림과 최상 트림은 1천만원 이상 차이).
    basis = r.get("group_basis") or ""
    exact_trim = basis.endswith("트림")
    pg = r["price_gap"]
    if pg is not None and not exact_trim:
        caution.append("비교할 수 있는 같은 트림 차가 적어 시세차를 신뢰할 수 없습니다")
        checks.append(f"이 차와 트림이 똑같은 차가 K카 재고에 3대도 없어, "
                      f"{basis}(으)로 넓혀서 비교했습니다. 이 그룹에는 옵션이 더 좋은 "
                      f"윗급 트림이 섞여 있어 <b>실제보다 싸 보일 수 있습니다.</b> "
                      f"이 차의 시세차는 참고만 하시고, 값이 적정한지는 "
                      f"K카 페이지에서 같은 트림끼리 직접 비교해 보세요.")
        pg = None                      # 이 아래 가격 판단에서 제외
    elif pg is not None and r["group_n"] < 5:
        caution.append(f"같은 트림 비교 대상이 {r['group_n']}대뿐이라 시세가 정확하지 않을 수 있습니다")
    if r["price_gap"] is None:
        caution.append(f"비교할 차가 {r['group_n']}대뿐이라 시세를 알기 어렵습니다")
    if pg is None:
        pass
    elif pg >= 0.10:
        good.append(f"같은 차·같은 연식 {r['group_n']}대와 비교해 {pg:.0%} 저렴합니다")
    elif pg <= -0.10:
        warn.append(f"같은 차·같은 연식 {r['group_n']}대와 비교해 {abs(pg):.0%} 비쌉니다")
    elif pg <= -0.03:
        caution.append(f"같은 차·같은 연식 {r['group_n']}대와 비교해 "
                       f"{abs(pg):.0%} 비싼 편입니다")
        checks.append(f"이 차는 같은 차·같은 연식 {r['group_n']}대의 중앙값보다 "
                      f"{abs(pg):.0%} 비쌉니다. 주행거리가 짧거나 옵션이 좋아서 비싼 것인지 "
                      f"따져 보시고, 그런 이유가 없다면 값을 깎아 달라고 하거나 "
                      f"다른 매물을 보세요.")

    # 7) 흔한 차인가 (전체 재고에서 직접 측정) -------------------------------
    mstat = (stats.get("models") or {}).get(r["model_group"] or "", {})
    cnt = mstat.get("count", 0)
    rank, nmodels = mstat.get("rank"), stats.get("model_count", 0)
    if cnt >= COMMON_STRONG:
        good.append(f"K카 직영 재고에 {cnt}대나 있는 아주 흔한 차입니다 "
                    f"(차종 {nmodels}종 중 {rank}위) — 부품 구하기 쉽고, 정비소마다 "
                    f"고쳐 본 경험이 있고, 나중에 팔 때도 잘 팔립니다")
    elif cnt >= COMMON_OK:
        good.append(f"재고 {cnt}대로 흔한 편입니다 (차종 {nmodels}종 중 {rank}위) — "
                    f"부품·정비에 무리가 없습니다")
    elif cnt < RARE:
        caution.append(f"재고가 {cnt}대뿐인 드문 차입니다")
        checks.append(f"이 차는 K카 직영 재고 전체에서 {cnt}대뿐입니다(차종 {nmodels}종 중 "
                      f"{rank}위). 드문 차는 (1) 특정 부품을 주문해야 할 수 있고, "
                      f"(2) 동네 정비소가 안 만져 봤을 수 있고, (3) 나중에 팔 때 "
                      f"사려는 사람이 적어 값을 깎이기 쉽습니다. "
                      f"같은 값에 흔한 차가 있으면 흔한 차가 유리합니다.")

    # 8) 옵션 ---------------------------------------------------------------
    if "후방카메라" in r["opt"]:
        good.append("후방카메라가 있습니다")
    else:
        caution.append("후방카메라가 확인되지 않습니다")
        checks.append("후방카메라가 목록에 없습니다. 주차할 때 크게 도움이 되니 실제로 있는지 "
                      "차에서 직접 확인하시고, 없으면 설치 비용(20~40만원)을 감안하세요.")
    if "후방센서" in r["opt"]:
        good.append("후방 감지센서(삐 소리)가 있습니다")
    if "열선시트" in r["opt"]:
        good.append("열선시트(엉덩이 따뜻해지는 기능)가 있습니다")
    if "스마트키" in r["opt"]:
        good.append("스마트키가 있어 열쇠를 꺼내지 않아도 됩니다")
    if "후측방경보" in r["opt"]:
        good.append("후측방 경보가 있어 차선 바꿀 때 사각지대를 알려줍니다")

    # 9) 크기 ---------------------------------------------------------------
    if sn["park_level"] == "어려움":
        caution.append("차가 커서 주차가 부담될 수 있습니다")
    elif sn["park_level"] == "쉬움":
        good.append("차가 작아 주차가 편합니다")
    if size in (K.SIZE_SMALL_SUV, K.SIZE_MID_SUV):
        good.append("시트가 적당히 높아 타고 내리기 편합니다")

    # 10) 세금·연료비 -------------------------------------------------------
    tax = K.car_tax(r["cc"], r["year"])
    fuel_cost = K.annual_fuel_cost(pt["engine"], r["fuel"])
    if r["cc"] and r["cc"] >= 2300:
        caution.append("배기량이 커서 자동차세와 기름값이 많이 듭니다")

    # 등급 ------------------------------------------------------------------
    if len(warn) >= 2:
        grade = "주의"
    elif len(warn) == 1 or len(caution) >= 5:
        grade = "따져보기"
    elif len(caution) >= 3:
        grade = "괜찮음"
    else:
        grade = "안심"

    # 내부 정렬용 (화면에 숫자로 노출되지 않는다) ----------------------------
    order = (len(warn) * 10 + len(caution)) - len(good) * 0.5
    # 가격은 주의 항목보다 무겁게 본다. 시세보다 10% 싸면 주의 1개보다 큰 이점이다.
    order -= (pg or 0) * 12   # pg 는 트림이 정확히 맞을 때만 값이 있다
    if eng["nature"] == "자연흡기" and pt["tx"] in (K.TX_AUTO, K.TX_IVT):
        order -= 2
    if size in (K.SIZE_SMALL_SUV, K.SIZE_MID_SUV):
        order -= 1
    order -= min(cnt, 200) / 100        # 흔한 차를 살짝 우대

    gen = (stats.get("generations") or {}).get(r["model"] or "", {})
    return dict(pt=pt, eng=eng, size=size, size_note=sn, fuel_note=fuel_note,
                warn=warn, caution=caution, good=good,
                checks=[c for c in checks if c], grade=grade,
                tax=tax, fuel_cost=fuel_cost, stock=cnt, rank=rank, gen=gen,
                order=order)


# ── 추천 고르기 ──────────────────────────────────────────────────────────────
def pick(items, pred, n=SECTION_N, exclude=(), one_per_model=True):
    """추천은 경고가 있는 매물을 넣지 않고, 같은 차종을 반복하지 않는다."""
    ex = {i["id"] for i in exclude}
    seen: set[str] = set()
    out = []
    for i in items:
        if i["id"] in ex or i["ev"]["warn"] or not pred(i):
            continue
        key = i["model_group"] or i["model"]
        if one_per_model and key in seen:
            continue
        seen.add(key)
        out.append(i)
        if len(out) >= n:
            break
    return out


def categories(items):
    # 가장 먼저 권하는 자리이므로 시세보다 비싼 차는 넣지 않는다.
    top = pick(items, lambda i: i["ev"]["grade"] in ("안심", "괜찮음")
               and (i["group_basis"] or "").endswith("트림")
               and (i["price_gap"] is None or i["price_gap"] >= 0), n=TOP_PICKS)
    return top, [
        ("조용하고 기름값이 가장 적게 드는 차",
         "시내와 정체 구간이 많으시면 하이브리드가 가장 편합니다. 저속에서 전기로만 "
         "움직여 소리가 거의 없고, 기름값은 일반 가솔린차의 절반에 가깝습니다.",
         pick(items, lambda i: i["fuel"] == "하이브리드", exclude=top)),
        ("타고 내리기가 가장 편한 차",
         "무릎이나 허리가 불편하시면 시트 높이가 중요합니다. 세단은 낮아 앉을 때 허리를 "
         "굽히게 되고, 큰 SUV는 올라타야 합니다. 그 중간인 소형·준중형 SUV가 가장 편합니다.",
         pick(items, lambda i: i["ev"]["size"] in (K.SIZE_SMALL_SUV, K.SIZE_MID_SUV)
              and i["accident"] == "무사고" and i["fuel"] != "디젤", exclude=top)),
        ("주차가 가장 편한 차",
         "좁은 골목이나 아파트 주차장을 자주 쓰시면 차 크기가 곧 스트레스입니다. "
         "작고 후방카메라가 있는 차를 골랐습니다.",
         pick(items, lambda i: i["ev"]["size_note"]["park_level"] == "쉬움"
              and "후방카메라" in i["opt"], exclude=top)),
        ("정비·부품이 가장 편한 흔한 차",
         "많이 팔린 차는 어느 정비소에 가도 고쳐 본 경험이 있고, 부품이 재고로 있어 "
         "수리가 빠르고 값도 쌉니다. 나중에 파실 때도 사려는 사람이 많습니다. "
         "K카 직영 재고 전체에서 물량이 많은 차종을 골랐습니다.",
         pick(items, lambda i: i["ev"]["stock"] >= COMMON_STRONG, exclude=top)),
        ("짐을 넉넉히 싣는 차 (5인승)",
         "5인승 안에서 트렁크와 뒷좌석이 가장 넉넉한 SUV입니다. 차가 커지는 만큼 "
         "주차는 조금 더 신경 쓰셔야 합니다.",
         pick(items, lambda i: i["ev"]["size"] in (K.SIZE_MID_SUV, K.SIZE_LARGE_SUV),
              exclude=top)),
        ("돈을 가장 아끼는 차",
         "차값이 낮고 세금·기름값도 적게 드는 차입니다. 대신 주행거리가 길 수 있으니 "
         "확인 항목을 특히 잘 보세요.",
         pick(sorted(items, key=lambda i: i["price"] + (i["ev"]["tax"] or 0) / 10000),
              lambda i: True, exclude=top)),
    ]


# ── 현장 체크리스트 ──────────────────────────────────────────────────────────
FIELD_CHECKLIST = [
    ("가기 전에 집에서 (5분)", [
        "매물 번호로 K카 페이지를 열어 가격·주행거리·연식이 이 표와 같은지 본다. "
        "다르면 이미 팔렸거나 값이 바뀐 것이다.",
        "자동차리콜센터(car.go.kr)에서 차대번호로 <b>리콜 대상인지, 조치가 끝났는지</b> 조회한다. "
        "무료다.",
        "보험개발원 카히스토리(carhistory.or.kr)에서 <b>보험 수리 이력</b>을 조회한다. "
        "약 2,200원이지만 침수·전손 여부까지 나오므로 꼭 본다.",
        "방문 전에 전화로 '차가 아직 있는지, 진단서와 정비이력을 종이로 볼 수 있는지' 확인한다.",
        "가능하면 <b>아침 첫 방문</b>으로 예약한다. 시동을 한 번도 걸지 않은 차를 봐야 한다.",
    ]),
    ("차 밖에서 (10분)", [
        "밝은 낮에, 비 오지 않을 때 본다. 어두우면 판금·도색 흔적이 안 보인다.",
        "차 앞에 쪼그려 앉아 옆에서 차체 선을 따라 본다. 물결처럼 울렁이면 판금한 자리다.",
        "문·보닛·트렁크 틈이 좌우 대칭인지 손가락을 넣어 본다. 한쪽이 넓으면 사고 흔적이다.",
        "문틈·보닛 안쪽의 <b>고무 몰딩을 살짝 들어</b> 도색이 겹쳐 있는지 본다.",
        "볼트 머리의 페인트가 벗겨졌거나 공구 자국이 있는지 본다. 뗐다 붙인 흔적이다.",
        "타이어 4개의 상표가 다 같은지, 옆면 4자리 숫자(제조 주차)를 본다. "
        "예: '2419'는 2019년 24주 생산. 5년 넘었으면 교체 비용을 감안한다.",
        "타이어 홈에 100원짜리 동전을 거꾸로 꽂아 이순신 장군 감투가 보이면 교체 시기다.",
        "타이어 4개의 닳은 정도가 한쪽만 심하지 않은지 본다. 한쪽만 닳으면 정렬·하부 문제다.",
        "차 밑을 들여다보고 바닥에 기름이나 물이 떨어진 자리가 있는지 본다.",
        "앞유리에 금이 갔는지, 와이퍼가 지나간 자리가 뿌옇게 긁혔는지 본다.",
    ]),
    ("차 안에서 (10분)", [
        "문을 다 닫고 <b>냄새를 맡는다.</b> 곰팡이·흙 냄새가 나면 물이 샜거나 침수 의심이다.",
        "안전벨트를 끝까지 쭉 뽑아 아래쪽에 흙물 자국이나 곰팡이가 있는지 본다. "
        "침수차를 잡는 가장 쉬운 방법이다.",
        "트렁크 바닥 매트를 들어내고 스페어타이어 자리에 녹이나 흙이 있는지 본다.",
        "운전석에 앉아 <b>어머님이 편한 자세가 나오는지</b> 본다. 페달까지 발이 편히 닿고, "
        "핸들 위로 계기판이 잘 보이고, 앞유리 시야가 답답하지 않아야 한다.",
        "시트를 최대한 올렸을 때 천장에 머리가 닿지 않는지 본다.",
        "타고 내리기를 <b>세 번 반복해 본다.</b> 매일 하실 동작이다.",
        "브레이크·가속 페달의 고무 닳은 정도를 본다. 주행거리에 비해 많이 닳았으면 "
        "주행거리를 의심한다.",
        "에어컨을 가장 세게, 히터도 가장 뜨겁게 켜 본다. 바람이 바로 나오는지, "
        "곰팡이 냄새가 나는지 본다.",
        "창문·사이드미러 접힘·와이퍼·경음기·모든 등화·후방카메라·내비게이션을 하나씩 눌러 본다.",
        "시동을 켠 상태에서 계기판에 <b>경고등이 남아 있는지</b> 본다. 엔진 모양, 배터리, "
        "브레이크, 에어백 경고등이 켜져 있으면 그 자리에서 이유를 물어야 한다.",
    ]),
    ("시동과 엔진룸 (10분)", [
        "<b>시동을 한 번도 걸지 않은 차를 본다.</b> 미리 시동을 걸어 따뜻하게 해 둔 차는 "
        "냉간 시 증상을 감춘다. 보닛을 손등으로 만져 따뜻하면 이미 걸었던 차다.",
        "시동 거는 순간 소리를 듣는다. '딱딱딱' 하는 금속성 소리, 심한 떨림, "
        "'끼익' 하는 벨트 소리가 있으면 원인을 물어본다.",
        "보닛을 열고 엔진오일 게이지를 뽑아 <b>양이 정상 범위인지, 색이 새까맣지 않은지</b> 본다.",
        "냉각수 통의 물이 적정선인지, 색이 탁하거나 기름이 떠 있지 않은지 본다.",
        "엔진 주변에 젖어 번쩍이는 곳(누유)이나 하얗게 말라붙은 자국(냉각수 누수)이 있는지 본다.",
        "배터리 위 제조일 스티커를 본다. 3년 넘었으면 곧 교체다(10~20만원).",
        "시동을 켠 채 배기구 뒤에 손을 대 본다. 물방울은 정상이고, 검은 그을음이나 "
        "파란 연기는 문제다.",
        "엔진룸이 유난히 반짝반짝 세척돼 있으면 오히려 의심한다. 누유 흔적을 지운 경우가 있다.",
    ]),
    ("반드시 시승 (15분 이상)", [
        "<b>시승 없이 계약하지 않는다.</b> K카는 시승이 가능하다. 안 된다고 하면 다른 차를 본다.",
        "가다 서다 하는 <b>정체 구간</b>을 꼭 지나본다. 시속 10~30km에서 울컥거림이나 "
        "떨림이 있는지 본다. (건식 DCT 차는 이 구간이 핵심이다)",
        "오르막에서 가속해 본다. 힘이 없거나 변속이 늦으면 원인을 물어본다.",
        "시속 60~80km에서 핸들에서 손을 살짝 떼 본다. 한쪽으로 쏠리면 정렬이나 사고 이력이다.",
        "빈 곳에서 브레이크를 세게 밟아 본다. 핸들이 떨리거나 '끼익' 소리가 나면 "
        "디스크·패드 교체가 필요하다.",
        "창문을 닫고 라디오를 끄고 <b>소리에만 집중해</b> 달린다. 바람소리 외에 "
        "'웅~' 하는 소리가 커지면 베어링, '덜덜' 소리는 하부 부싱이다.",
        "정차 중 기어를 D와 R로 번갈아 넣어 본다. '쿵' 하는 충격이 크면 변속기·마운트 문제다.",
        "후진으로 주차를 한 번 해 본다. 후방 시야와 카메라 화질을 직접 확인한다.",
        "시승이 끝난 뒤 다시 차 밑을 보고 새로 떨어진 액체가 없는지 본다.",
    ]),
    ("서류와 계약 (10분)", [
        "<b>K카 진단서(성능·상태점검기록부)를 종이로 받아</b> 수리 부위 표시를 직접 본다. "
        "'교환'과 '판금'이 어디에 몇 군데 표시됐는지 센다.",
        "자동차등록증의 차대번호가 차 앞유리 밑 번호와 같은지 대조한다.",
        "등록증의 <b>소유자 변경 횟수</b>를 본다. 3회 이상이면 이유를 물어본다.",
        "'용도' 항목이 자가용인지 본다. 영업용·대여용(렌터카) 이력이 있으면 값이 더 싸야 한다.",
        "등록증의 <b>승차정원이 5인</b>인지 확인한다(이 목록은 5인승만 골랐다).",
        "정비 이력을 받아 <b>10만km 정비(변속기오일·점화플러그·냉각수)를 했는지</b> 확인한다.",
        "총 구매비용을 <b>종이로 다시 받는다.</b> 차값 외에 이전비·매도비·탁송비가 얼마인지 "
        "항목별로 적힌 견적을 받는다. 말로 들은 금액과 다른 경우가 있다.",
        "K카 보증(기본·연장) 범위와 기간을 문서로 확인한다. 엔진·변속기 포함 여부가 핵심이다.",
        "환불·교환 조건을 확인한다. K카는 일정 기간 책임 환불 제도를 운영한다.",
        "계약서에 서명하기 전 <b>하루 자고 결정하셔도 된다.</b> "
        "그 자리에서 결정하라고 재촉하는 곳은 피한다.",
    ]),
]

RED_FLAGS = [
    "정비소에 가서 점검해 보자고 했을 때 <b>거절하거나 미루는</b> 경우",
    "진단서·정비이력을 종이로 못 준다고 하는 경우",
    "차가 이미 시동이 걸려 따뜻해져 있고, 식힌 뒤 다시 걸어보자고 하면 거절하는 경우",
    "안전벨트 아래쪽이나 트렁크 안쪽에 <b>흙물 자국·곰팡이</b>가 있는 경우 (침수 의심)",
    "계기판에 <b>경고등이 켜져 있는데</b> '원래 그렇다', '곧 꺼진다'고 넘어가는 경우",
    "실내에서 <b>방향제 냄새가 유독 강한</b> 경우 (냄새를 덮는 경우가 있다)",
    "같은 차·같은 연식보다 값이 <b>유난히 싼데</b> 그 이유를 설명하지 못하는 경우",
    "주행거리가 아주 짧다는데 <b>페달 고무·핸들·시트가 많이 닳아 있는</b> 경우",
    "계약을 <b>오늘 안 하면 안 된다</b>고 재촉하는 경우",
]

LOOKUPS = [
    ("자동차리콜센터", "https://www.car.go.kr/",
     "차대번호로 이 차가 리콜 대상인지, 조치가 끝났는지 조회합니다. 무료입니다. "
     "국토교통부·한국교통안전공단이 운영합니다."),
    ("보험개발원 카히스토리", "https://www.carhistory.or.kr/",
     "보험으로 처리한 수리 이력, 침수·전손 여부, 소유자 변경 횟수를 조회합니다. "
     "약 2,200원이며, 이 돈은 반드시 쓰실 만합니다."),
    ("자동차민원 대국민포털", "https://www.ecar.go.kr/",
     "자동차 등록 원부를 확인할 수 있습니다. 용도(자가용/영업용) 이력을 봅니다."),
]


# ── HTML ─────────────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f7f6f3;color:#1b1b1b;
font-family:system-ui,-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
font-size:19px;line-height:1.8;letter-spacing:-.01em}
main{max-width:820px;margin:0 auto;padding:24px 18px 80px}
h1{font-size:1.85rem;line-height:1.35;margin:.4em 0 .2em}
h2{font-size:1.4rem;margin:2.4em 0 .5em;padding-bottom:.35em;border-bottom:3px solid #2f6f4f}
h3{font-size:1.12rem;margin:1.6em 0 .4em}
p{margin:.7em 0}
.lead{font-size:1.06rem;color:#333}
.top{background:#2f6f4f;color:#fff;padding:18px 20px;border-radius:12px;margin:16px 0}
.top b{color:#ffe9a8}
.top p{margin:.4em 0;font-size:.98rem;line-height:1.7}
.box{background:#fff;border:1px solid #e0ddd6;border-radius:12px;padding:18px 20px;margin:16px 0}
.warnbox{background:#fff7f5;border:1px solid #e8bfb4;border-left:6px solid #c0392b}
.tipbox{background:#f4faf6;border:1px solid #bcdcc7;border-left:6px solid #2f6f4f}
.card{background:#fff;border:1px solid #ddd9d1;border-radius:14px;padding:20px;margin:18px 0;
box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card h3{margin-top:0;font-size:1.22rem;line-height:1.4}
.rank{display:inline-block;background:#2f6f4f;color:#fff;border-radius:999px;
width:1.9em;height:1.9em;line-height:1.9em;text-align:center;font-size:.95rem;
font-weight:700;margin-right:.4em}
.badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.85rem;
font-weight:700;margin-left:.3em;white-space:nowrap}
.g-a{background:#dff2e4;color:#1c5c38}
.g-b{background:#e6f0fb;color:#1c4a7a}
.g-c{background:#fdf1dc;color:#8a5a12}
.g-d{background:#fbe3e0;color:#932018}
.spec{display:flex;flex-wrap:wrap;gap:6px 0;margin:12px 0;padding:10px 0;list-style:none;
border-top:1px solid #eee;border-bottom:1px solid #eee}
.spec li{flex:1 1 50%;font-size:.94rem;color:#333}
.spec b{color:#000}
.pros,.cons{margin:.5em 0;padding-left:1.3em}
.pros li{color:#1c5c38;margin:.25em 0}
.cons li{color:#8a3b12;margin:.25em 0}
.money{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.money div{flex:1 1 150px;background:#faf9f6;border:1px solid #e5e2da;border-radius:10px;
padding:10px 12px}
.money span{display:block;font-size:.8rem;color:#666}
.money strong{font-size:1.08rem}
.dep{display:flex;gap:4px;flex-wrap:wrap;margin:8px 0;font-size:.86rem}
.dep div{background:#f2f1ee;border:1px solid #e2e0d8;border-radius:8px;padding:5px 9px}
.dep b{display:block;font-size:.78rem;color:#666;font-weight:400}
.dep .me{background:#e8f3ec;border-color:#8fbfa2}
details{margin:10px 0;border:1px solid #e0ddd6;border-radius:10px;background:#fff}
details[open]{background:#fffdf8}
summary{cursor:pointer;padding:12px 16px;font-weight:700;font-size:1rem;
background:#f2f1ee;border-radius:10px}
details[open] summary{border-radius:10px 10px 0 0;border-bottom:1px solid #e0ddd6}
.dbody{padding:6px 18px 16px}
ol.chk,ul.chk{padding-left:1.4em;margin:.6em 0}
ol.chk li,ul.chk li{margin:.55em 0;line-height:1.7}
a{color:#1a5fa8}
.btn{display:inline-block;background:#2f6f4f;color:#fff !important;text-decoration:none;
padding:11px 20px;border-radius:10px;font-weight:700;margin:6px 6px 6px 0;font-size:1rem;
border:none;cursor:pointer;font-family:inherit}
.btn.alt{background:#fff;color:#2f6f4f !important;border:2px solid #2f6f4f}
footer{margin-top:50px;padding-top:18px;border-top:1px solid #ccc;font-size:.85rem;color:#555}
table.simple{border-collapse:collapse;width:100%;font-size:.92rem;margin:10px 0}
table.simple th,table.simple td{padding:8px 6px;border-bottom:1px solid #e5e2da;text-align:left}
table.simple th{background:#f2f1ee}
table.simple td.num{text-align:right}
@media print{
 body{background:#fff;font-size:12pt}
 .noprint{display:none !important}
 details{border:none}details summary{display:none}
 details .dbody{padding:0}
 h2{page-break-after:avoid}.card{page-break-inside:avoid}
 ol.chk li,ul.chk li{margin:.35em 0}
}
@media(max-width:600px){
 body{font-size:18px}
 h1{font-size:1.5rem}h2{font-size:1.22rem}
 .spec li{flex:1 1 100%}
 main{padding:16px 14px 60px}
}
"""


def h(v) -> str:
    return html.escape(str(v if v not in (None, "") else "-"))


def rich(s: str) -> str:
    """<b> 와 **강조** 만 허용한다. 그 밖의 태그는 이스케이프한다."""
    out = html.escape(s).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    parts = out.split("**")
    if len(parts) > 1:
        out = parts[0] + "".join(
            (f"<b>{p}</b>" if i % 2 else p) for i, p in enumerate(parts[1:], 1))
    return out


def dep_strip(r: dict) -> str:
    """같은 세대의 연식별 시세. 감가가 눈에 보이게 한다."""
    ys = (r["ev"]["gen"] or {}).get("median_price_by_year") or {}
    if len(ys) < 2:
        return ""
    cells = "".join(
        f'<div class="{"me" if int(y) == r["year"] else ""}"><b>{h(y)}년식</b>'
        f'{int(p):,}만</div>' for y, p in sorted(ys.items()))
    return (f'<p style="font-size:.88rem;color:#555;margin-bottom:2px">'
            f'같은 세대 연식별 시세(K카 직영 재고 중앙값) — 초록이 이 차의 연식</p>'
            f'<div class="dep">{cells}</div>')


def card(r: dict, rank: int | None = None) -> str:
    ev = r["ev"]
    cls, gtext = GRADE_STYLE[ev["grade"]]
    rk = f'<span class="rank">{rank}</span>' if rank else ""
    money = []
    if ev["tax"]:
        money.append(f'<div><span>연간 자동차세(대략)</span><strong>{ev["tax"]:,}원</strong></div>')
    if ev["fuel_cost"]:
        money.append(f'<div><span>연간 기름값(1년 1.2만km)</span>'
                     f'<strong>{ev["fuel_cost"]:,}원</strong></div>')
    money.append(f'<div><span>차값 + 이전비 추정</span>'
                 f'<strong>{r["total_cost_est"]:,}만원</strong></div>')
    pros = "".join(f"<li>{rich(g)}</li>" for g in ev["good"][:8])
    cons = "".join(f"<li>{rich(c)}</li>" for c in ev["warn"] + ev["caution"])
    checks = "".join(f"<li>{rich(c)}</li>" for c in ev["checks"])
    gap = (f'같은 차·같은 연식 {r["group_n"]}대의 중앙값 {r["group_median_price"]:,.0f}만원 '
           f'대비 <b>{r["price_gap"]:+.0%}</b>'
           if r["price_gap"] is not None else
           f'비교 가능한 차가 {r["group_n"]}대뿐이라 시세 비교 어려움')
    return f"""
<div class="card">
<h3>{rk}{h(r['maker'])} {h(r['model'])} {h(r['trim'])}
<span class="badge {cls}">{ev['grade']} · {gtext}</span></h3>
<p class="lead">{rich(K.character_of(r['model']))}</p>
<ul class="spec">
<li><b>{h(r['year_month'])}</b> 연식</li>
<li>주행 <b>{r['km']:,}km</b></li>
<li>차값 <b>{r['price']:,}만원</b></li>
<li>{h(r['accident'])}</li>
<li>{h(ev['eng']['name'])}</li>
<li>{h(ev['pt']['tx'])}</li>
<li>{h(ev['size'])} · 주차 {h(ev['size_note']['park_level'])} · {h(r['seats'])}인승</li>
<li>{h(r['location'])}</li>
</ul>
<div class="money">{''.join(money)}</div>
<p style="font-size:.93rem;color:#444">{gap}</p>
{dep_strip(r)}
<p><b>좋은 점</b></p><ul class="pros">{pros or '<li>-</li>'}</ul>
<p><b>걸리는 점</b></p><ul class="cons">{cons or '<li>특별히 걸리는 점이 없습니다</li>'}</ul>
<details><summary>이 차를 보러 가면 꼭 확인할 것 ({len(ev['checks'])}가지)</summary>
<div class="dbody"><ul class="chk">{checks}</ul></div></details>
<p class="noprint"><a class="btn" href="{h(r['url'])}" target="_blank"
rel="noopener nofollow">K카에서 이 차 보기</a>
<span style="font-size:.85rem;color:#666">매물번호 {h(r['id'])}</span></p>
</div>"""


def build(rows, meta, stats) -> str:
    items = []
    for r in rows:
        r = dict(r)
        r["ev"] = evaluate(r, stats)
        items.append(r)
    items.sort(key=lambda x: x["ev"]["order"])

    top, cats = categories(items)
    top_html = "".join(card(r, i) for i, r in enumerate(top, 1))
    cat_html = []
    for title, intro, picks in cats:
        if not picks:
            continue
        cat_html.append(f"<h2>{h(title)}</h2><p class='lead'>{rich(intro)}</p>"
                        + "".join(card(r) for r in picks))

    chk_html = []
    for i, (title, lines) in enumerate(FIELD_CHECKLIST, 1):
        body = "".join(f"<li>{rich(l)}</li>" for l in lines)
        chk_html.append(f"<details {'open' if i == 1 else ''}><summary>{i}. {h(title)}</summary>"
                        f"<div class='dbody'><ol class='chk'>{body}</ol></div></details>")

    red = "".join(f"<li>{rich(x)}</li>" for x in RED_FLAGS)
    look = "".join(
        f"<h3>{h(n)}</h3><p>{rich(d)}<br><a href='{h(u)}' target='_blank' "
        f"rel='noopener nofollow'>{h(u)}</a></p>" for n, u, d in LOOKUPS)

    dist = {}
    for i in items:
        dist[i["ev"]["grade"]] = dist.get(i["ev"]["grade"], 0) + 1
    dist_rows = "".join(
        f"<tr><td><span class='badge {GRADE_STYLE[g][0]}'>{g}</span></td>"
        f"<td>{GRADE_STYLE[g][1]}</td><td class='num'>{dist.get(g,0)}대</td></tr>"
        for g in ("안심", "괜찮음", "따져보기", "주의"))

    rj = meta.get("rejects", {})
    rej_rows = "".join(
        f"<tr><td>{h(k)}</td><td class='num'>{v:,}대</td></tr>"
        for k, v in sorted(rj.items(), key=lambda x: -x[1]))

    shown = {t["id"] for t in top} | {p["id"] for _, _, ps in cats for p in ps}
    rest = [i for i in items if i["id"] not in shown][:LIST_N]
    rest_rows = "".join(
        f"<tr><td>{h(i['maker'])} {h(i['model'])}<br>"
        f"<span style='font-size:.85rem;color:#666'>{h(i['trim'])}</span></td>"
        f"<td>{h(i['year_month'])}</td><td class='num'>{i['km']:,}</td>"
        f"<td class='num'>{i['price']:,}</td>"
        f"<td>{h(i['fuel'])}</td><td>{h(i['accident'])}</td>"
        f"<td><span class='badge {GRADE_STYLE[i['ev']['grade']][0]}'>"
        f"{i['ev']['grade']}</span></td>"
        f"<td><a href='{h(i['url'])}' target='_blank' rel='noopener nofollow'>보기</a></td></tr>"
        for i in rest)

    fuel_guide = "".join(
        f"<h3>{h(name)}</h3><p>{rich(v['good'])}</p>"
        + (("<p><b>확인할 점</b></p><ul class='chk'>"
            + "".join(f"<li>{rich(w)}</li>" for w in v["watch"]) + "</ul>") if v["watch"] else "")
        + f"<p style='color:#555;font-size:.92rem'>알맞은 경우: {h(v['suits'])}</p>"
        for name, v in K.FUEL_NOTES.items())

    c = meta.get("conditions", {})
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>어머님을 위한 중고차 고르기 — K카 직영 전체 재고 검토</title>
<style>{CSS}</style>
</head><body><main>

<h1>어머님을 위한 중고차 고르기</h1>
<p class="lead">K카(kcar.com) 직영 재고를 <b>한 대도 빼지 않고 전부</b> 훑어
조건에 맞는 차를 고르고, 차마다 <b>무엇을 확인해야 하는지</b>를 정리했습니다.
점수로 줄 세우지 않았습니다. 차마다 성격과 걸리는 점이 다르기 때문입니다.</p>

<div class="top">
<p><b>수집 일시</b> {h(meta.get('collected_at'))} · <b>출처</b> K카(kcar.com) 직영 매물</p>
<p>직영 재고 <b>{meta.get('collected', 0):,}대 전체</b>를 받아
그중 <b>{meta.get('comparable_pool', 0):,}대</b>를 시세 기준으로 쓰고,
조건에 맞는 <b>{meta.get('passed', len(rows)):,}대</b>를 골랐습니다.</p>
<p><b>5인승만</b> 골랐습니다. 7·9·11인승(카니발 등)과 미니밴, 경차, 화물·승합,
렌터카 이력, 사고 이력 차는 모두 뺐습니다.</p>
<p style="font-size:.88rem">{h(DISCLAIMER)}</p>
</div>

<div class="box tipbox">
<h3 style="margin-top:0">제가 무엇을 근거로 판단했는지</h3>
<p>중고차 이야기는 인터넷에 많지만 근거가 불확실한 것이 섞여 있습니다.
그래서 <b>확인할 수 있는 것만</b> 근거로 삼았습니다.</p>
<ol class="chk">
<li><b>확인된 리콜 이력</b> — 공개된 엔진 자료와 미국 집단소송 합의 공지에서 확인된
부분만 씁니다. 예: 세타2 GDI 엔진은 크랭크샤프트 주변 금속 이물로 베어링이 일찍 닳는
문제가 확인되어 리콜이 있었습니다.</li>
<li><b>구조적 사실</b> — 터보가 붙으면 터보차저·인터쿨러가 늘고, 건식 DCT는 클러치가
소모품입니다. 이건 의견이 아니라 구조입니다. 부품이 적은 차가 고장 날 곳도 적습니다.</li>
<li><b>K카 직영 재고 전체 통계</b> — 재고 {meta.get('collected', 0):,}대에서
차종별 물량과 연식별 시세를 직접 계산했습니다. 물량이 많은 차종은 부품이 흔하고
정비소가 익숙하며 나중에 팔기도 쉽습니다. 커뮤니티 글보다 실제 유통 물량이 확실한 근거입니다.</li>
<li><b>계산값</b> — 자동차세와 연간 기름값은 배기량·연식·연료로 직접 계산했습니다.</li>
</ol>
<p><b>여기 없는 것</b> — 특정 차종의 '고질병' 이야기는 단정하지 않았습니다.
대신 그 차종에서 <b>점검이 필요한 부분</b>으로만 적었습니다.
"이 차에 그 고장이 있다"는 뜻이 아닙니다.</p>
</div>

<div class="box warnbox">
<h3 style="margin-top:0">이 정리로 알 수 없는 것 (중요)</h3>
<p>K카 규칙(robots.txt)이 각 차의 상세 페이지를 자동으로 열지 못하게 하고 있어,
<b>상세 페이지는 한 건도 열지 않았습니다.</b> 그래서 다음 네 가지는 이 페이지에 없습니다.</p>
<ul class="chk">
<li>보험으로 처리한 수리 이력 (침수·전손 여부 포함)</li>
<li>소유자가 몇 번 바뀌었는지</li>
<li>K카가 표시하는 정확한 총 구매비용 (이 페이지 금액은 추정입니다)</li>
<li>남아 있는 보증 기간</li>
</ul>
<p>이 네 가지는 아래 <b>'계약 전에 꼭 조회할 3곳'</b>과 현장에서 직접 확인하셔야 합니다.
<b>시승과 진단서 확인은 어떤 경우에도 생략하면 안 됩니다.</b></p>
</div>

<h2>먼저, 어머님께 맞는 연료부터 고르세요</h2>
<p class="lead">중고차에서 가장 크게 갈리는 것은 브랜드가 아니라 연료입니다.
주로 다니시는 거리에 따라 답이 달라집니다.</p>
<div class="box">{fuel_guide}</div>
<div class="box warnbox">
<p style="margin:0"><b>가장 흔한 실수</b> — 연비가 좋다는 말만 듣고 디젤을 고르는 것입니다.
집 근처 마트, 병원, 가까운 시내만 다니신다면 디젤은 배기가스를 태우는 장치가 막혀
수리비가 크게 나올 수 있습니다. <b>편도 10km 안쪽을 주로 다니시면
가솔린이나 하이브리드를 고르세요.</b></p>
</div>

<h2>가장 먼저 보실 {len(top)}대</h2>
<p class="lead">확인할 점이 가장 적고, 복잡한 장치가 없어 오래 타기 편한 차들입니다.
같은 차종이 반복되지 않게 골랐습니다.</p>
{top_html}

{''.join(cat_html)}

<h2>보러 가실 때 쓰는 체크리스트</h2>
<p class="lead">순서대로 하시면 됩니다. 이 페이지를 인쇄하시거나 휴대폰으로 열어두고
하나씩 확인하세요. <b>아래를 다 지키면 대부분의 나쁜 차는 걸러집니다.</b></p>
<p class="noprint"><button class="btn" onclick="window.print()">이 페이지 인쇄하기</button>
<a class="btn alt" href="#red">'이런 차는 사지 마세요'부터 보기</a></p>
{''.join(chk_html)}

<h2 id="red">이런 차는 사지 마세요</h2>
<p class="lead">아래 중 <b>하나라도</b> 해당되면, 값이 아무리 싸도 넘어가세요.
중고차는 이 차 아니면 안 되는 경우가 없습니다. 매물은 매주 새로 들어옵니다.</p>
<div class="box warnbox"><ul class="chk">{red}</ul></div>

<h2>계약 전에 꼭 조회할 3곳</h2>
<p class="lead">차대번호(자동차등록증에 적혀 있고, 앞유리 아래에서도 보입니다)만 있으면
집에서 조회할 수 있습니다. 여기서 걸러지는 차가 생각보다 많습니다.</p>
<div class="box">{look}</div>

<h2>전체 {meta.get('collected', 0):,}대에서 어떻게 {meta.get('passed', 0):,}대가 남았나</h2>
<p class="lead">K카 직영 재고를 전부 받아 아래 순서로 걸렀습니다. 조건은
현대·기아(제네시스 포함) / 5인승 / 세단·해치백·SUV /
차량가 {c.get('budget', 1300):,}만원 이하 / {c.get('year', 2017)}년식 이상 /
{c.get('km', 120000):,}km 이하 / 무사고 또는 단순수리입니다.</p>
<table class="simple"><thead><tr><th>빠진 이유</th><th class="num">대수</th></tr></thead>
<tbody>{rej_rows}
<tr><td><b>조건 통과</b></td><td class="num"><b>{meta.get('passed', 0):,}대</b></td></tr>
</tbody></table>

<h2>등급은 이렇게 나눴습니다</h2>
<p class="lead">점수가 아니라 <b>확인할 점이 몇 가지인지</b>로 나눴습니다.
'주의'가 나쁜 차라는 뜻은 아니고, 확인할 것이 많다는 뜻입니다.
확인해서 문제가 없으면 좋은 차일 수 있습니다.</p>
<table class="simple" id="t-grade"><thead><tr><th>등급</th><th>뜻</th>
<th class="num">대수</th></tr></thead><tbody>{dist_rows}</tbody></table>

<h2>나머지 후보 {len(rest)}대</h2>
<p class="lead">위에서 마음에 드는 차가 없을 때 보실 목록입니다.
'연료 고르기'와 '체크리스트'를 그대로 적용하시면 됩니다.</p>
<table class="simple" id="t-rest">
<thead><tr><th>차</th><th>연식</th><th class="num">주행(km)</th><th class="num">차값(만)</th>
<th>연료</th><th>사고</th><th>등급</th><th></th></tr></thead>
<tbody>{rest_rows}</tbody></table>
<p class="noprint" style="margin-top:20px">
<a class="btn alt" href="all.html">전체 {meta.get('passed', 0)}대 표로 보기 (정렬·검색)</a>
<a class="btn alt" href="report.md">분석 리포트 원문</a></p>

<footer>
<p><b>출처</b> K카(kcar.com) 직영 매물 목록. 직영 재고 {meta.get('collected', 0):,}대 전체 수집,
수집 {h(meta.get('collected_at'))}. 사진은 싣지 않았고 각 매물의 K카 페이지로 연결만 합니다.
K카 규칙에 따라 상세 페이지는 조회하지 않았고, 요청은 순차·1.8초 간격으로 보냈습니다.</p>
<p><b>근거</b> 엔진이 어느 차에 쓰였고 리콜이 있었는지는 공개된 엔진 자료(위키피디아
Hyundai Theta / R engine)와 미국 집단소송 합의 공지에서 확인했습니다.
차종별 물량·연식별 시세는 위 재고 전체에서 직접 계산했습니다.
자동차세·기름값은 <b>대략값</b>이며 실제 고지액과 주행 습관에 따라 달라집니다.
연식별 시세는 주행거리·트림이 섞여 있어 완전한 감가 곡선은 아니고 참고용입니다.
그 밖의 점검 항목은 널리 알려진 정비 상식으로, <b>특정 차량에 결함이 있다는 뜻이 아닙니다.</b></p>
<p>{h(DISCLAIMER)}</p>
</footer>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/listings.csv")
    ap.add_argument("--out", default="docs/index.html")
    args = ap.parse_args()
    rows, meta, stats = load(args.csv)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(build(rows, meta, stats))
    print(f"{args.out} 생성 — 후보 {len(rows)}대 / "
          f"시세 기준 재고 {stats.get('total_comparable', 0):,}대")


if __name__ == "__main__":
    main()
