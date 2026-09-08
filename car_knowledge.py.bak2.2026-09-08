#!/usr/bin/env python3
"""차종·엔진·변속기 지식 베이스와 판정 규칙.

`build_guide.py` 가 이 모듈을 써서 매물별 확인사항을 만든다. LLM 없이 동작한다.

정보 등급을 반드시 구분한다.
- FACT   : 출처로 확인한 사실 (엔진 적용 차종·연식, 리콜 존재 등)
- COMMON : 정비 상식으로 널리 알려진 것. 특정 매물에 결함이 있다고 단정하지 않고
           "확인할 것"으로만 제시한다.
- CALC   : 이 스크립트가 계산한 추정치 (세금·연료비 등)

확인한 출처
- 위키피디아 Hyundai Theta engine: 2.4 GDI(G4KJ) 적용 차종·연식
  (그랜저/아제라 2011-2019, 쏘나타 2009-2019, 투싼 TL 2015-2020, 카덴자(K7) 2011-2019,
  옵티마(K5) 2010-2019, 스포티지 2010-2021, 쏘렌토 UM 2014-2020), 2.0 T-GDI(G4KH) 적용,
  결함 내용("크랭크샤프트 주변 금속 이물로 오일 흐름 문제, 베어링 조기 마모")과
  2015·2017·2020년 리콜 존재.
- 위키피디아 Hyundai R engine: R2.0(D4HA) 싼타페·투싼·쏘렌토·스포티지,
  R2.2(D4HB) 그랜저·팰리세이드·싼타페·카니발·쏘렌토. 이 문서에는 리콜 언급 없음
  → EGR·화재 관련 통설은 단정하지 않고 리콜 조회로 넘긴다.
- 미국 집단소송 합의(hbsslaw.com, 2021년 최종승인): 세타2 GDI 대상 차량에
  평생보증·KSDS(노크센서 감지 소프트웨어) 제공. 한국 적용 범위는 차대번호로 확인해야 한다.
"""
from __future__ import annotations

# ── 변속기 분류 (기어 단수는 단정하지 않는다. 판단에 필요한 구분만 한다) ──────
TX_AUTO = "일반 자동변속기"
TX_DCT_DRY = "건식 DCT"
TX_DCT_HEV = "하이브리드 DCT"
TX_IVT = "무단변속기(IVT)"

TX_EXPLAIN = {
    TX_AUTO: "가장 흔하고 무난한 자동변속기입니다. 정체 구간에서 부드럽습니다.",
    TX_DCT_DRY: "연비를 위해 수동변속기 구조를 자동으로 만든 방식입니다. "
                "가다 서다 하는 길에서 울컥거리거나 미세하게 떨리는 경우가 보고됩니다.",
    TX_DCT_HEV: "하이브리드용 변속기입니다. 전기모터가 저속을 담당해 "
                "일반 건식 DCT보다 저속 거동이 부드러운 편입니다.",
    TX_IVT: "기어 단이 없이 연속으로 변하는 방식입니다. 조용하고 부드럽습니다.",
}

# ── 엔진 분류 ────────────────────────────────────────────────────────────────
# key: 내부 코드 / name: 표시명 / theta2: 세타2 GDI 계열 여부
ENGINES = {
    "kappa_14_mpi": dict(name="1.4 자연흡기 가솔린", nature="자연흡기", theta2=False),
    "kappa_10_t": dict(name="1.0 터보 가솔린", nature="터보", theta2=False),
    "gamma_16_gdi": dict(name="1.6 가솔린 직분사(GDI)", nature="자연흡기", theta2=False),
    "gamma_16_t": dict(name="1.6 터보 가솔린", nature="터보", theta2=False),
    "gamma_14_t": dict(name="1.4 터보 가솔린", nature="터보", theta2=False),
    "smartstream_16": dict(name="1.6 가솔린", nature="자연흡기", theta2=False),
    "smartstream_20": dict(name="2.0 가솔린", nature="자연흡기", theta2=False),
    "nu_20": dict(name="2.0 자연흡기 가솔린", nature="자연흡기", theta2=False),
    "nu_20_lpi": dict(name="2.0 LPG", nature="자연흡기", theta2=False),
    "theta2_24_gdi": dict(name="2.4 가솔린 직분사(세타2 GDI)", nature="자연흡기", theta2=True),
    "theta2_20_t": dict(name="2.0 터보 가솔린(세타2 T-GDI)", nature="터보", theta2=True),
    "lambda_30_33": dict(name="3.0~3.3 가솔린", nature="자연흡기", theta2=False),
    "u2_16_dsl": dict(name="1.6 디젤", nature="디젤", theta2=False),
    "u_17_dsl": dict(name="1.7 디젤", nature="디젤", theta2=False),
    "r_20_dsl": dict(name="2.0 디젤", nature="디젤", theta2=False),
    "r_22_dsl": dict(name="2.2 디젤", nature="디젤", theta2=False),
    "s2_30_dsl": dict(name="3.0 디젤", nature="디젤", theta2=False),
    "hev_kappa_16": dict(name="1.6 하이브리드", nature="하이브리드", theta2=False),
    "hev_nu_20": dict(name="2.0 하이브리드", nature="하이브리드", theta2=False),
}

# ── 차급 (승하차·주차 판단용) ────────────────────────────────────────────────
SIZE_SMALL_SUV = "소형 SUV"
SIZE_MID_SUV = "준중형 SUV"
SIZE_LARGE_SUV = "중형 이상 SUV"
SIZE_SUBCOMPACT = "소형 승용"
SIZE_COMPACT = "준중형 승용"
SIZE_MID_SEDAN = "중형 세단"
SIZE_LARGE_SEDAN = "준대형 이상 세단"
SIZE_VAN = "미니밴"

# 모델(세대)명 → 차급. 부분 문자열로 맞춘다(긴 것부터 검사).
SIZE_BY_MODEL = [
    ("스토닉", SIZE_SMALL_SUV), ("코나", SIZE_SMALL_SUV), ("베뉴", SIZE_SMALL_SUV),
    ("니로", SIZE_MID_SUV), ("투싼", SIZE_MID_SUV), ("스포티지", SIZE_MID_SUV),
    ("싼타페", SIZE_LARGE_SUV), ("쏘렌토", SIZE_LARGE_SUV), ("모하비", SIZE_LARGE_SUV),
    ("카니발", SIZE_VAN), ("카렌스", SIZE_VAN),
    ("쏘울", SIZE_COMPACT), ("아반떼", SIZE_COMPACT), ("i30", SIZE_COMPACT),
    ("벨로스터", SIZE_COMPACT), ("프라이드", SIZE_SUBCOMPACT), ("엑센트", SIZE_SUBCOMPACT),
    ("아이오닉", SIZE_COMPACT), ("K3", SIZE_COMPACT),
    ("쏘나타", SIZE_MID_SEDAN), ("K5", SIZE_MID_SEDAN),
    ("그랜저", SIZE_LARGE_SEDAN), ("K7", SIZE_LARGE_SEDAN), ("G80", SIZE_LARGE_SEDAN),
]

# 차급별 어머님 관점 설명 (승하차 / 주차)
SIZE_NOTES = {
    SIZE_SMALL_SUV: dict(
        board="시트 높이가 승용차보다 살짝 높아 허리를 굽히지 않고 앉을 수 있습니다. "
              "타고 내리기가 가장 편한 편입니다.",
        park="차가 작아 좁은 골목·주차장에서 부담이 적습니다.", park_level="쉬움"),
    SIZE_MID_SUV: dict(
        board="시트가 높아 타고 내리기 편합니다. 다만 차 높이가 있어 "
              "지하주차장 높이 제한을 한 번 보셔야 합니다.",
        park="보통 크기입니다. 주차선 안에 무리 없이 들어갑니다.", park_level="보통"),
    SIZE_LARGE_SUV: dict(
        board="시트가 상당히 높습니다. 무릎이 불편하시면 올라타기가 버거울 수 있습니다.",
        park="차가 큽니다. 좁은 주차장에서는 신경을 많이 쓰셔야 합니다.", park_level="어려움"),
    SIZE_VAN: dict(
        board="문이 옆으로 미끄러지는 슬라이딩 도어라 좁은 곳에서 타고 내리기 좋습니다.",
        park="차가 매우 큽니다. 아파트 주차장에서 특히 부담이 됩니다.", park_level="어려움"),
    SIZE_SUBCOMPACT: dict(
        board="시트가 낮고 차가 작습니다. 타고 내릴 때 허리를 많이 굽히게 됩니다. "
              "무릎이 불편하시면 직접 앉아보고 결정하셔야 합니다.",
        park="가장 작아서 주차가 제일 편합니다. 좁은 골목도 부담이 없습니다.",
        park_level="쉬움"),
    SIZE_COMPACT: dict(
        board="시트가 낮아 앉을 때 허리를 굽히게 됩니다. 무릎·허리가 불편하시면 "
              "직접 앉아보고 결정하셔야 합니다.",
        park="작아서 주차가 편합니다.", park_level="쉬움"),
    SIZE_MID_SEDAN: dict(
        board="시트가 낮습니다. 타고 내릴 때 허리를 굽히게 됩니다.",
        park="보통 크기입니다.", park_level="보통"),
    SIZE_LARGE_SEDAN: dict(
        board="시트가 낮고 문이 큽니다. 좁은 주차장에서 문을 다 열기 어려울 수 있습니다.",
        park="차가 길어 주차선을 넘기기 쉽습니다. 후방카메라가 꼭 있어야 합니다.",
        park_level="어려움"),
}

# ── 모델별 성격 한 줄 (COMMON: 일반적으로 알려진 특성) ───────────────────────
MODEL_CHARACTER = {
    "스토닉": "기아의 작은 SUV입니다. 복잡한 장치가 적어 잔고장 걱정이 상대적으로 적고, "
              "값이 싸서 같은 돈으로 주행거리가 짧은 차를 고를 수 있습니다.",
    "코나": "스토닉과 비슷한 크기의 현대 소형 SUV입니다. 옵션이 더 좋은 편입니다.",
    "베뉴": "현대의 가장 작은 SUV입니다. 혼자 또는 둘이 타고 근거리를 다니기에 알맞습니다.",
    "니로": "기아의 하이브리드 전용 SUV입니다. 기름값이 가장 적게 들고 조용합니다.",
    "투싼": "현대의 준중형 SUV입니다. 실내가 넉넉하고 시야가 좋습니다.",
    "스포티지": "기아의 준중형 SUV입니다. 투싼과 형제차입니다.",
    "싼타페": "중형 SUV입니다. 짐과 사람을 많이 실을 수 있지만 차가 큽니다.",
    "쏘렌토": "싼타페와 같은 급의 기아 중형 SUV입니다.",
    "모하비": "큰 정통 SUV입니다. 세금과 기름값이 많이 듭니다.",
    "카니발": "9~11인승 미니밴입니다. 짐과 손님이 많을 때 가장 편하지만 차가 매우 큽니다.",
    "카렌스": "작은 미니밴입니다. LPG라 연료비가 저렴합니다.",
    "쏘울": "박스형 소형차입니다. 천장이 높아 실내가 답답하지 않습니다.",
    "아반떼": "가장 많이 팔린 준중형 세단입니다. 정비소마다 부품이 흔하고 수리비가 싸며, "
              "나중에 팔 때도 잘 팔립니다.",
    "i30": "아반떼와 같은 뼈대의 해치백입니다. 뒤가 트렁크 대신 문으로 열립니다.",
    "벨로스터": "문 개수가 특이한 준중형 해치백입니다. 뒷좌석이 좁습니다.",
    "프라이드": "소형차입니다. 값이 가장 싸고 유지비도 적게 듭니다.",
    "엑센트": "소형 세단입니다. 값이 싸고 운전이 쉽습니다.",
    "아이오닉": "하이브리드 전용 준중형차입니다. 연비가 매우 좋습니다.",
    "K3": "기아의 준중형 세단입니다. 아반떼와 경쟁하는 차입니다.",
    "쏘나타": "가장 대중적인 중형 세단입니다. 부품과 정비소가 흔합니다.",
    "K5": "쏘나타와 같은 급의 기아 중형 세단입니다.",
    "그랜저": "준대형 세단입니다. 승차감이 편안하고 조용하지만 차가 크고 "
              "세금·기름값이 많이 듭니다.",
    "K7": "그랜저와 같은 급의 기아 준대형 세단입니다.",
    "G80": "제네시스 대형 세단입니다. 가장 조용하고 편안하지만 세금·기름값·수리비가 "
           "가장 많이 듭니다.",
}

# ── 연료 정보 ────────────────────────────────────────────────────────────────
FUEL_NOTES = {
    "가솔린": dict(
        good="시동이 조용하고 겨울에도 문제가 적습니다. 짧은 거리를 자주 다니기에 가장 알맞습니다.",
        watch=[], suits="단거리·시내 위주"),
    "디젤": dict(
        good="장거리 연비가 좋고 힘이 좋습니다.",
        watch=["짧은 거리만 자주 다니면 배기가스를 태우는 장치(DPF)가 막혀 수리비가 크게 "
               "듭니다. 편도 10km 이내 출퇴근 위주라면 디젤은 권하지 않습니다.",
               "시동을 걸 때 소리와 떨림이 가솔린보다 큽니다.",
               "요소수나 배기 관련 경고등이 뜬 이력이 있는지 확인하세요."],
        suits="장거리·고속도로 위주"),
    "LPG": dict(
        good="연료비가 가솔린의 절반 수준으로 가장 저렴합니다.",
        watch=["연료통(봄베) 검사 유효기간이 남아 있는지 반드시 확인하세요. "
               "기간이 지나면 재검사 비용이 듭니다.",
               "연료통이 트렁크를 차지해 짐 공간이 줄어듭니다.",
               "충전소가 주유소보다 적습니다. 집·직장 근처에 있는지 미리 확인하세요."],
        suits="주행거리가 많고 충전소가 가까운 경우"),
    "하이브리드": dict(
        good="기름값이 가장 적게 들고, 저속에서 전기로만 움직여 매우 조용합니다. "
             "정체 구간에서 특히 유리합니다.",
        watch=["큰 배터리가 따로 있습니다. 보증이 얼마나 남았는지 차대번호로 꼭 확인하세요. "
               "보증이 끝난 뒤 배터리를 교체하면 비용이 큽니다.",
               "12V 보조배터리도 따로 있어 수명이 다하면 시동이 안 걸릴 수 있습니다."],
        suits="시내·정체 구간이 많은 경우"),
}

# ── 자동차세 (CALC) ──────────────────────────────────────────────────────────
# 지방세법 승용자동차 영업용 외 기준: cc당 세액 + 지방교육세 30%
# 차령 경감: 3년차부터 매년 5%, 최대 50%
VAN_FLAT_TAX = 65000     # 기타 승합자동차 정액 자동차세(원/년)


def is_van_registered(model: str, trim: str) -> bool:
    """승합자동차로 등록됐을 가능성이 높은 경우.

    카니발 9인승·11인승은 승합자동차로 등록돼 자동차세가 배기량과 무관한
    정액이다(승용 기준으로 계산하면 크게 과대평가된다). 7인승은 승용이다.
    실제 분류는 자동차등록증의 '차종'에서 확인해야 한다.
    """
    t = f"{model} {trim}"
    if "카니발" not in model:
        return False
    return any(k in t for k in ("9인승", "11인승"))


def car_tax(cc: int | None, year: int | None, this_year: int = 2026,
            van: bool = False) -> int | None:
    """연간 자동차세 대략값(원). 정확한 고지액은 지자체 고지서를 따른다."""
    if not year:
        return None
    age = this_year - year + 1                  # 차령(년차)
    cut = min(max(age - 2, 0) * 5, 50) / 100    # 3년차부터 5%씩, 최대 50%
    if van:                                     # 승합: 배기량과 무관한 정액
        return int(round(VAN_FLAT_TAX * 1.3 * (1 - cut), -2))
    if not cc:
        return None
    rate = 80 if cc <= 1000 else 140 if cc <= 1600 else 200
    base = int(cc * rate * 1.3)                 # 지방교육세 30%
    return int(round(base * (1 - cut), -2))


# ── 연비·연료비 (CALC, 대략값) ───────────────────────────────────────────────
FUEL_PRICE = {"가솔린": 1700, "디젤": 1550, "LPG": 1100, "하이브리드": 1700}  # 원/L
ANNUAL_KM = 12000

# (엔진코드, 차급) 조합의 대표 복합연비 대략값(km/L). 정확한 공인연비가 아니라
# 차종 간 연료비를 비교하기 위한 근사값이다.
FUEL_ECONOMY = {
    "hev_kappa_16": 19.0, "hev_nu_20": 17.0,
    "u2_16_dsl": 16.0, "r_20_dsl": 13.5, "r_22_dsl": 11.5, "u_17_dsl": 15.0,
    "s2_30_dsl": 9.5,
    "kappa_14_mpi": 12.5, "kappa_10_t": 13.5,
    "gamma_16_gdi": 13.0, "gamma_16_t": 12.0, "gamma_14_t": 13.0,
    "smartstream_16": 15.0, "smartstream_20": 13.0,
    "nu_20": 11.8, "nu_20_lpi": 8.8,
    "theta2_24_gdi": 10.8, "theta2_20_t": 10.5, "lambda_30_33": 9.5,
}


def annual_fuel_cost(engine_key: str, fuel: str, annual_km: int = ANNUAL_KM) -> int | None:
    """연간 유류비 대략값(원)."""
    kmpl = FUEL_ECONOMY.get(engine_key)
    price = FUEL_PRICE.get(fuel)
    if not kmpl or not price:
        return None
    return int(round(annual_km / kmpl * price, -3))


# ── 트림 문자열 → 엔진/변속기 판별 ──────────────────────────────────────────
def identify_powertrain(model: str, trim: str, fuel: str, cc: int | None) -> dict:
    """모델·트림·연료·배기량으로 엔진과 변속기를 판정한다.

    확실하지 않으면 보수적으로 일반 분류를 반환한다(과잉 단정 금지).
    """
    t = f"{model} {trim}"
    m = model

    # 하이브리드 먼저
    if fuel == "하이브리드":
        if any(k in m for k in ("니로", "아이오닉")):
            return dict(engine="hev_kappa_16", tx=TX_DCT_HEV)
        return dict(engine="hev_nu_20", tx=TX_AUTO)

    if fuel == "LPG":
        return dict(engine="nu_20_lpi", tx=TX_AUTO)

    if fuel == "디젤":
        if "3.0" in t:
            return dict(engine="s2_30_dsl", tx=TX_AUTO)
        if "2.2" in t or "카니발" in m or "모하비" in m:
            return dict(engine="r_22_dsl", tx=TX_AUTO)
        if "2.0" in t:
            return dict(engine="r_20_dsl", tx=TX_AUTO)      # R2.0 + 토크컨버터 자동
        if "1.7" in t:
            return dict(engine="u_17_dsl", tx=TX_DCT_DRY)
        # 1.6 디젤(U2)은 건식 DCT 조합이 많다
        return dict(engine="u2_16_dsl", tx=TX_DCT_DRY)

    # 가솔린
    if "카니발" in m or "모하비" in m:                        # 카니발 가솔린 = 3.3
        return dict(engine="lambda_30_33", tx=TX_AUTO)
    if "3.3" in t or "3.0" in t or "G80" in m:
        return dict(engine="lambda_30_33", tx=TX_AUTO)
    # 세타2: 2.4 GDI, 그리고 쏘나타/K5 계열의 2.0 터보
    if "2.4" in t or "HG240" in t:
        return dict(engine="theta2_24_gdi", tx=TX_AUTO)
    if "2.0 터보" in t and any(k in m for k in ("쏘나타", "K5")):
        return dict(engine="theta2_20_t", tx=TX_AUTO)
    if "1.6 터보" in t or "1.6 T-GDI" in t:
        return dict(engine="gamma_16_t", tx=TX_DCT_DRY)
    if "1.4 터보" in t:
        return dict(engine="gamma_14_t", tx=TX_DCT_DRY)
    if "1.0 터보" in t:
        return dict(engine="kappa_10_t", tx=TX_DCT_DRY)
    if "1.4" in t:                                           # 스토닉 1.4, 엑센트 1.4
        return dict(engine="kappa_14_mpi", tx=TX_AUTO)
    if "쏘나타 DN8" in m:
        return dict(engine="smartstream_20", tx=TX_AUTO)
    if "올 뉴 K3" in m or "K3 2세대" in m or "베뉴" in m or "더 뉴 K3" == m:
        return dict(engine="smartstream_16", tx=TX_IVT)
    if "2.0" in t or (cc and 1900 <= cc <= 2100):
        return dict(engine="nu_20", tx=TX_AUTO)
    if "1.6" in t or (cc and 1500 <= cc <= 1700):
        return dict(engine="gamma_16_gdi", tx=TX_AUTO)
    # 판정 실패: 배기량으로만 대략 분류
    if cc and cc >= 2300:
        return dict(engine="lambda_30_33", tx=TX_AUTO)
    return dict(engine="gamma_16_gdi", tx=TX_AUTO)


def size_of(model: str) -> str:
    for key, size in SIZE_BY_MODEL:
        if key in model:
            return size
    return SIZE_COMPACT


def character_of(model: str) -> str:
    for key, text in MODEL_CHARACTER.items():
        if key in model:
            return text
    return "국산 승용차입니다."


# ── 세타2 GDI 안내 (FACT 기반) ───────────────────────────────────────────────
THETA2_NOTICE = (
    "이 차의 엔진은 '세타2 GDI' 계열입니다. 이 엔진은 크랭크샤프트 주변 금속 이물로 "
    "오일 흐름이 막혀 베어링이 일찍 닳는 문제가 확인되어 2015·2017·2020년에 리콜이 "
    "있었고, 미국에서는 집단소송 합의로 해당 차량에 평생보증과 엔진 이상을 미리 감지하는 "
    "소프트웨어(KSDS)가 제공되었습니다. "
    "따라서 이 차를 보실 때는 (1) 차대번호로 리콜 조치가 끝났는지, "
    "(2) 엔진 관련 보증이 남아 있는지, (3) 엔진오일이 줄어든 이력이나 "
    "'딱딱딱' 하는 금속성 소음이 있는지를 반드시 확인하세요. "
    "조치가 완료되고 보증이 남아 있으면 오히려 안심하고 탈 수 있습니다."
)

# ── 주행거리 구간별 정비 안내 (COMMON) ──────────────────────────────────────
def mileage_notes(km: int) -> list[str]:
    out = []
    if km >= 60000:
        out.append("브레이크 패드·타이어는 이 주행거리에서 이미 한 번 교체했을 시기입니다. "
                   "언제 갈았는지 물어보세요.")
    if km >= 80000:
        out.append("엔진 보조 벨트와 각종 고무 호스가 딱딱해지는 시기입니다. "
                   "엔진룸에서 갈라진 벨트나 젖은 흔적이 있는지 보세요.")
    if km >= 100000:
        out.append("변속기 오일, 냉각수, 점화플러그를 교체하는 시기입니다. "
                   "10만km 정비를 받았는지 기록으로 확인하세요. "
                   "안 했다면 인수 후 30~60만원 정도가 더 듭니다.")
        out.append("엔진 마운트(엔진을 받치는 고무)가 주저앉아 정차 중 떨림이 커질 수 있습니다. "
                   "시동을 걸고 기어를 D에 넣은 채 떨림을 느껴보세요.")
    if km >= 115000:
        out.append("12만km에 가까워 조건상 상한선입니다. 값이 싼 대신 "
                   "인수 직후 정비비를 따로 준비하셔야 합니다.")
    return out


def age_notes(year: int, this_year: int = 2026) -> list[str]:
    age = this_year - year
    out = []
    if age >= 8:
        out.append(f"{year}년식으로 약 {age}년 된 차입니다. 주행거리와 별개로 "
                   "고무·플라스틱 부품이 삭기 시작합니다. 특히 에어컨 관련 부품과 "
                   "각종 센서가 이 시기에 고장 나는 경우가 있습니다.")
    if age >= 9:
        out.append("차령이 길어 제조사 일반 보증(보통 3년/6만km)과 엔진 보증"
                   "(보통 5년/10만km)은 이미 끝났을 가능성이 높습니다. "
                   "K카 자체 보증이 어디까지 되는지 확인하세요.")
    return out
