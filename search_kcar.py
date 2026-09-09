#!/usr/bin/env python3
"""K카(kcar.com) 직영 중고차 **전체 재고**를 수집해 시세를 만들고, 조건에 맞는 후보를 고른다.

LLM 없이 단독 실행된다.

    python3.11 search_kcar.py --budget 1300 --year 2017 --km 120000 --seats 5 \
        --fuel gasoline,hybrid,lpg,diesel --out data/listings.csv

왜 전체 재고를 받는가
    예산 이하 매물만 받아 중앙값을 내면 "예산 이하 차들끼리의 중앙값"이 되어 시세가
    실제보다 낮게 잡힌다. 같은 차·같은 연식의 **전체 시세**와 비교해야 싸게 사는지
    알 수 있으므로, 직영 재고 전체를 받아 시세 기준으로 쓰고 조건 필터는 그 다음에 건다.

준수 사항 (어기지 않는다)
- robots.txt 허용 범위만 조회한다. 상세 페이지(/bc/detail/carInfoDtl?, /car/info/)는
  Disallow 이므로 **한 건도 요청하지 않는다**. 상세에서만 얻는 필드는 null로 둔다.
- 순차 요청만 한다(동시 요청 없음). 요청 간 --sleep 초(기본 1.8) 대기.
- 403/429/캡차가 보이면 우회하지 않고 즉시 중단한다.
- 원본 응답은 data/raw/ 에만 저장한다(커밋 대상 아님).
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

# ── 점수 가중치 (여기만 고치면 된다) ────────────────────────────────────────
W_PRICE_GAP = 30.0        # 시세 대비 가격 이점
W_KM_GAP = 20.0           # 시세 대비 주행거리 이점
W_ACCIDENT = {"무사고": 20.0, "단순수리": 10.0}      # 그 외 0
W_OWNER_FEW = 10.0        # 소유자 변경 1회 이하 (상세 미조회 → 판정 불가, 전 매물 0)
W_OPTION_EACH = 2.5       # 후방카메라·열선시트·스마트키·내비 각각
W_FUEL = {"하이브리드": 5.0, "가솔린": 0.0, "LPG": 0.0, "디젤": -5.0}
W_NEW_LISTING = 3.0       # 등록 7일 이내 (상세 미조회 → 판정 불가, 전 매물 0)

PRICE_GAP_FULL = 0.20     # 그룹 중앙값보다 20% 저렴하면 가격 항목 만점
KM_GAP_FULL = 0.30        # 그룹 중앙값보다 30% 덜 탔으면 주행거리 항목 만점
SCORE_OPTIONS = ["후방카메라", "열선시트", "스마트키", "내비"]
MIN_GROUP_SIZE = 3        # 그룹 매물 수가 이보다 적으면 시세 비교 불가
TRIM_SPLIT_SPREAD = 0.40  # 그룹 가격 산포((최고-최저)/중앙값)가 이보다 크면 트림 계열로 세분

# ── 수집 대상 ────────────────────────────────────────────────────────────────
WWW = "https://www.kcar.com"
API = "https://api.kcar.com"
LIST_PATH = "/bc/search/list/drct"        # K카 직영(내차사기)
LIST_PAGE = "/bc/search"                  # robots 허용 여부를 확인할 공개 목록 페이지
DETAIL_URL = WWW + "/bc/detail/carInfoDtl?i_sCarCd={}"   # 링크 전용. 절대 요청하지 않는다
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# 프런트 번들(/_nuxt/*.js)에 하드코딩된 파라미터 직렬화 키. 인증·접근제어가 아니라
# 요청 본문 인코딩 포맷이며, 브라우저가 보내는 요청을 그대로 재현하기 위한 것이다.
ENC_KEY = b"SKFJ2424DasfaJRI"
ENC_IV = b"sfq241sf3dscs321"

KST = timezone(timedelta(hours=9))

# ── 조건 ─────────────────────────────────────────────────────────────────────
ALLOWED_MAKERS = {"현대", "기아", "제네시스"}
FUEL_ALIASES = {
    "gasoline": "가솔린", "가솔린": "가솔린",
    "hybrid": "하이브리드", "하이브리드": "하이브리드",
    "lpg": "LPG", "LPG": "LPG",
    "diesel": "디젤", "디젤": "디젤",
}
FUEL_FROM_KCAR = {"가솔린": "가솔린", "디젤": "디젤", "LPG": "LPG",
                  "가솔린+전기": "하이브리드", "LPG+전기": "하이브리드",
                  "디젤+전기": "하이브리드"}
# carctgrNm(크기 기준 분류) → 차종. None 이면 제외 대상.
BODY_FROM_CTGR = {"SUV": "SUV", "RV": "미니밴",
                  "소형차": "세단", "준중형차": "세단", "중형차": "세단",
                  "준대형차": "세단", "대형차": "세단",
                  "경차": None, "경승합차": None, "승합차": None,
                  "화물차": None, "스포츠카": None}
HATCHBACK_HINTS = ["i30", "벨로스터", "K3 GT", "프라이드", "아이오닉", "씨드", "i20", "해치"]
KEICAR_HINTS = ["모닝", "레이", "캐스퍼", "스파크", "마티즈", "다마스", "라보"]
ACCIDENT_OK = {"무사고", "단순수리"}
# SUV 크기 상한: 셀토스(전장 4,375mm)급까지만 허용한다. 세단은 크기 제한이 없다
# (준대형 세단은 낮고 길어 주차 부담이 SUV보다 작다는 판단).
# 참고 전장: 베뉴 4,040 / 스토닉 4,140 / 코나 4,165~4,350 / 니로 4,355 / 셀토스 4,375
#          || 투싼 4,630 / 스포티지 4,660 / 쏘렌토 4,810 / 싼타페 4,785
SMALL_SUV_ALLOW = {"스토닉", "코나", "베뉴", "셀토스", "니로"}
# 준중형 SUV까지(기본): 쏘렌토(4,810mm)는 너무 크다는 사용자 판단 → 그 아래급인 투싼·스포티지까지 허용.
COMPACT_SUV_ALLOW = SMALL_SUV_ALLOW | {"투싼", "스포티지"}
SUV_ALLOW_BY_MAX = {"small": SMALL_SUV_ALLOW, "compact": COMPACT_SUV_ALLOW, "none": None}
SUV_REJECT_LABEL = {"small": "SUV가 셀토스보다 큼", "compact": "SUV가 투싼·스포티지보다 큼"}
OPTION_PATTERNS = {
    # 주차·후방 시야
    "후방카메라": ["카메라 : 후방"],
    "전방카메라": ["카메라 : 전방"],
    "어라운드뷰": ["어라운드"],
    "후방센서": ["감지센서 : 후방"],
    "전방센서": ["감지센서 : 전방"],
    # 첨단 안전(ADAS)
    "자동긴급제동": ["자동긴급제동"],
    "후측방경보": ["후측방"],
    "차선이탈경보": ["LDWS", "차선이탈"],
    "스마트크루즈": ["스마트 크루즈"],
    "헤드업디스플레이": ["헤드업"],
    # 기본 안전
    "타이어공기압경고": ["TPMS", "타이어공기압"],
    "차체자세제어": ["차체자세"],
    "경사로밀림방지": ["경사로밀림"],
    "전자식파킹브레이크": ["전자식파킹"],
    # 편의
    "통풍시트": ["통풍시트"],
    "열선시트": ["열선시트"],
    "뒷좌석열선": ["열선시트 : 뒷좌석"],
    "스마트키": ["스마트키"],
    "내비": ["내비게이션"],
    "크루즈": ["크루즈컨트롤"],
    "선루프": ["선루프", "썬루프"],
    "전동시트": ["전동시트"],
    "하이패스": ["하이패스"],
    "무선충전": ["무선충전"],
}

# 첨단 안전장치 — 있으면 사고 자체를 줄여 주는 것들. 안전 판단의 핵심 축이다.
ADAS_OPTIONS = ["자동긴급제동", "차선이탈경보", "후측방경보", "스마트크루즈"]
# 주차·저속 사고를 줄여 주는 것들
PARKING_AIDS = ["후방카메라", "후방센서", "전방센서", "어라운드뷰", "전방카메라"]
AIRBAG_KINDS = ["운전석", "조수석", "사이드", "커튼", "무릎", "동승석"]

# 총 구매비용 추정: 상세 페이지(Disallow)에 있는 K카 표시값을 쓸 수 없어 추정만 한다.
ACQUISITION_TAX_RATE = 0.07   # 승용 중고차 취득세
TRANSFER_FEE_MANWON = 3.0     # 매도비·이전대행 추정


class Blocked(RuntimeError):
    """403/429/캡차 등 차단 신호. 우회하지 않고 즉시 중단한다."""


# ── robots.txt ───────────────────────────────────────────────────────────────
def fetch_robots(session) -> dict[str, list[str]]:
    r = session.get(WWW + "/robots.txt", timeout=30)
    if r.status_code in (403, 429):
        raise Blocked(f"robots.txt 조회가 차단됨 (HTTP {r.status_code})")
    r.raise_for_status()
    rules: dict[str, list[str]] = {"allow": [], "disallow": []}
    star = False
    for line in r.text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            star = value == "*"
        elif star and field in ("allow", "disallow") and value:
            rules[field].append(value)
    return rules


def robots_allows(rules: dict[str, list[str]], path: str) -> bool:
    """가장 긴 일치 규칙이 이긴다(동률이면 Allow 우선)."""
    best_len, verdict = -1, True
    for kind in ("allow", "disallow"):
        for rule in rules[kind]:
            if path.startswith(rule) and len(rule) >= best_len:
                if len(rule) == best_len and kind == "disallow" and verdict:
                    continue
                best_len, verdict = len(rule), kind == "allow"
    return verdict


# ── API 호출 ─────────────────────────────────────────────────────────────────
def enc_param(param: dict) -> dict:
    """{"enc": base64(AES-128-CBC(JSON))}. falsy 값은 빼고 보낸다(프런트와 동일)."""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    clean = {k: v for k, v in param.items() if v}
    raw = json.dumps(clean, ensure_ascii=False, separators=(",", ":")).encode()
    ct = AES.new(ENC_KEY, AES.MODE_CBC, ENC_IV).encrypt(pad(raw, AES.block_size))
    return {"enc": base64.b64encode(ct).decode()}


def make_session():
    import requests

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Origin": WWW,
        "Referer": WWW + LIST_PAGE,
    })
    return s


def post_list(session, param: dict) -> dict:
    r = session.post(API + LIST_PATH, json=enc_param(param), timeout=40)
    if r.status_code in (403, 429, 503):
        raise Blocked(f"차단 신호 HTTP {r.status_code} — 우회하지 않고 중단한다.")
    body_head = r.text[:2000].lower()
    if any(w in body_head for w in ("captcha", "보안문자", "비정상적인 접근")):
        raise Blocked("캡차/차단 페이지가 반환됨 — 우회하지 않고 중단한다.")
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"API success=false: {payload.get('message')}")
    return payload["data"]


def collect(args) -> tuple[list[dict], int, str]:
    """직영 재고 **전체**를 페이지네이션해 원본 행을 모은다.

    서버측 필터를 걸지 않는다(시세 기준으로 쓰기 위해). 반환: (rows, totalCnt, 수집일시).
    """
    raw_dir = args.raw_dir
    os.makedirs(raw_dir, exist_ok=True)

    if args.use_cache:
        files = sorted(f for f in os.listdir(raw_dir) if re.fullmatch(r"page_\d+\.json", f))
        if not files:
            sys.exit(f"--use-cache 인데 {raw_dir}/page_*.json 이 없다.")
        rows, total = [], 0
        for f in files:
            d = json.load(open(os.path.join(raw_dir, f), encoding="utf-8"))
            rows += d["rows"]
            total = d.get("totalCnt", total)
        meta = os.path.join(raw_dir, "collected_at.txt")
        ts = open(meta, encoding="utf-8").read().strip() if os.path.exists(meta) else "(캐시)"
        print(f"[cache] {len(files)}페이지 {len(rows)}행 재사용 (수집일시 {ts})")
        return rows, total, ts

    session = make_session()
    rules = fetch_robots(session)
    if not robots_allows(rules, LIST_PAGE):
        sys.exit(f"중단: robots.txt 가 {LIST_PAGE} 를 허용하지 않는다.")
    blocked_detail = [d for d in rules["disallow"] if "detail" in d or "car/info" in d]
    print(f"[robots] {LIST_PAGE} 허용 확인. 상세 페이지 Disallow: {blocked_detail} → 조회하지 않음")
    time.sleep(args.sleep)

    collected_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    rows: list[dict] = []
    total, page = 0, 1
    t0 = time.time()
    while page <= args.max_pages:
        data = post_list(session, {"limit": args.limit, "pageno": page})
        total = data.get("totalCnt", 0)
        page_rows = data.get("rows") or []
        with open(os.path.join(raw_dir, f"page_{page:03d}.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        rows += page_rows
        pages = data.get("totalPageCnt", page)
        if page == 1 or page % 10 == 0 or page >= pages:
            print(f"[fetch] {page}/{pages} 페이지, 누적 {len(rows):,}/{total:,}대 "
                  f"({time.time()-t0:.0f}초)", flush=True)
        if not page_rows or page >= pages:
            break
        page += 1
        time.sleep(args.sleep)

    with open(os.path.join(raw_dir, "collected_at.txt"), "w", encoding="utf-8") as fh:
        fh.write(collected_at + "\n")
    return rows, total, collected_at


# ── 정규화 ───────────────────────────────────────────────────────────────────
def to_int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def body_type(row: dict) -> str | None:
    name = row.get("carWhlNm") or ""
    if any(h in name for h in KEICAR_HINTS) or row.get("carctgrNm") == "경차":
        return None
    body = BODY_FROM_CTGR.get(row.get("carctgrNm") or "", "세단")
    if body == "세단" and any(h in name for h in HATCHBACK_HINTS):
        return "해치백"
    return body


def options_of(row: dict) -> list[str]:
    raw = row.get("optnNm") or ""
    return [label for label, pats in OPTION_PATTERNS.items() if any(p in raw for p in pats)]


def airbag_count(row: dict) -> int:
    """'에어백 : 운전석' 처럼 종류별로 표기되므로 종류 수를 센다."""
    raw = row.get("optnNm") or ""
    return sum(1 for kind in AIRBAG_KINDS if f"에어백 : {kind}" in raw)


def normalize(row: dict) -> dict:
    car_cd = row.get("carCd")
    mfg = str(row.get("mfgDt") or "")
    price = to_int(row.get("prc"))
    return {
        "id": car_cd,
        "url": DETAIL_URL.format(car_cd),
        "maker": row.get("mnuftrNm"),
        "model": row.get("modelNm") or row.get("modelGrpNm"),
        "model_group": row.get("modelGrpNm"),
        "full_name": row.get("carWhlNm"),
        "trim": " ".join(x for x in [row.get("grdNm"), row.get("grdDtlNm")]
                         if x and x != "세부등급 없음").strip(),
        "grade_name": row.get("grdNm") or "",        # 트림 비교의 기준
        "trim_series": (row.get("grdNm") or "").split(" ")[0],
        "year_month": f"{mfg[:4]}-{mfg[4:6]}" if len(mfg) >= 6 else None,
        "year": to_int(mfg[:4]),
        "model_year": row.get("prdcnYr"),
        "km": to_int(row.get("milg")),
        "price": price,
        "total_cost": None,          # K카 표시 총 구매비용: 상세 페이지 Disallow → 미수집
        "total_cost_est": (round(price * (1 + ACQUISITION_TAX_RATE) + TRANSFER_FEE_MANWON)
                           if price is not None else None),
        "fuel": FUEL_FROM_KCAR.get(row.get("fuelNm") or ""),
        "fuel_raw": row.get("fuelNm"),
        "transmission": row.get("trnsmsnNm"),
        "cc": to_int(row.get("engdispmnt")),
        "seats": to_int(row.get("pasngrCnt")),
        "body_type": body_type(row),
        "category_raw": row.get("carctgrNm"),
        "accident": (row.get("acdtHistCnts") or "").strip(),
        "insurance_history": None,   # 상세 페이지 Disallow → 미수집
        "owner_changes": None,       # 상세 페이지 Disallow → 미수집
        "options": "|".join(options_of(row)),
        "airbags": airbag_count(row),
        "adas": "|".join(o for o in options_of(row) if o in ADAS_OPTIONS),
        "adas_n": sum(1 for o in options_of(row) if o in ADAS_OPTIONS),
        "parking_aid_n": sum(1 for o in options_of(row) if o in PARKING_AIDS),
        "location": " ".join(x for x in [row.get("cntrNm"), row.get("cntrRgnNm")] if x),
        "listed_date": None,         # 상세 페이지 Disallow → 미수집
        "warranty": None,            # 상세 페이지 Disallow → 미수집
        "photo": row.get("msizeImgPath") or row.get("lsizeImgPath"),
        # useNm 은 '이력'이 아니라 K카의 추천 용도 태그다(연료와 100% 일치). 판정에 쓰지 않는다.
        "use_tag": row.get("useNm") or "",
        "rent_reg": row.get("rentRegYn"),
        "reg_type": row.get("regType"),
        "seller_note": row.get("simcDesc"),
    }


def is_rental(item: dict) -> bool:
    """렌터카 판정. rentRegYn 은 전 매물 'N' 이라 무용하므로 차명 표기를 함께 본다."""
    return ((item["rent_reg"] or "N").upper() == "Y"
            or (item["reg_type"] or "SELL") != "SELL"
            or "렌터카" in (item["full_name"] or ""))


def reject_reason(item: dict, args) -> str | None:
    if item["maker"] not in ALLOWED_MAKERS:
        return "제조사"
    if item["body_type"] is None:
        return "차종제외(경차/화물/승합)"
    if item["body_type"] == "미니밴":
        return "미니밴 제외"
    suv_allow = SUV_ALLOW_BY_MAX[args.suv_max]
    if item["body_type"] == "SUV" and suv_allow is not None \
            and (item["model_group"] or "") not in suv_allow:
        return SUV_REJECT_LABEL[args.suv_max]
    if item["seats"] != args.seats:
        return f"{args.seats}인승 아님"
    if item["fuel"] is None or item["fuel"] not in args.fuel_set:
        return "연료"
    if item["accident"] not in ACCIDENT_OK:
        return "사고이력"
    if is_rental(item):
        return "렌터카"
    if item["price"] is None or item["price"] > args.budget:
        return "예산초과"
    if item["total_cost_est"] is not None and item["total_cost_est"] > args.total_budget:
        return "총비용초과"
    if item["year"] is None or item["year"] < args.year:
        return "연식"
    if item["km"] is None or item["km"] > args.km:
        return "주행거리"
    return None


# ── 시세 비교 (전체 재고를 기준으로) ────────────────────────────────────────
def comparable_pool(market: list[dict]) -> list[dict]:
    """시세 기준이 될 비교군. 사고차·렌터카는 값이 따로 형성되므로 뺀다."""
    return [m for m in market
            if m["price"] and m["km"] is not None and m["year"]
            and m["accident"] in ACCIDENT_OK and not is_rental(m)]


def _cc_bucket(item: dict) -> int:
    """배기량 200cc 단위 버킷. 1.6과 2.0을 같은 그룹에 넣지 않기 위한 것."""
    return round((item["cc"] or 0) / 200)


def peer_group(item: dict, pool: list[dict]) -> tuple[list[dict], str]:
    """가장 정확한 비교군을 고른다(넓은 쪽으로 단계적 후퇴).

    같은 세대·같은 좌석수·연식 ±1년을 바닥으로 두고, 그 안에서
    연료 → 배기량 → 트림까지 좁힌 뒤 3대 이상 남는 가장 좁은 그룹을 쓴다.

    이렇게 하는 이유: 트림 차이가 가격을 크게 가른다. 예를 들어 쏘나타 DN8은
    최하 트림과 최상 트림이 1,170만원 대 2,220만원이라, 세대만 묶어 중앙값을 내면
    최하 트림 매물이 실제보다 훨씬 싸 보인다. 반대로 스토닉은 1.4 가솔린과
    1.6 디젤이 섞이면 연료 때문에 왜곡된다.
    """
    base = [p for p in pool
            if p["model"] == item["model"] and p["seats"] == item["seats"]
            and abs((p["year"] or 0) - (item["year"] or 0)) <= 1]
    same_fuel = [p for p in base if p["fuel"] == item["fuel"]]
    same_cc = [p for p in same_fuel if _cc_bucket(p) == _cc_bucket(item)]
    # grdNm 에는 엔진·구동방식(예 '2.0 가솔린', '디젤 1.7 2WD')이, grdDtlNm 에는
    # 트림 등급(예 '스마트', '인스퍼레이션')이 들어 있다. 가격을 가르는 것은 둘 다이므로
    # 엔진 단계와 트림 단계를 따로 둔다.
    same_engine = [p for p in same_cc if p["grade_name"] == item["grade_name"]]
    same_trim = [p for p in same_engine if p["trim"] == item["trim"]]
    for cand, label in ((same_trim, "같은 세대·연료·배기량·트림"),
                        (same_engine, "같은 세대·연료·엔진(트림 등급 섞임)"),
                        (same_cc, "같은 세대·연료·배기량(트림 섞임)"),
                        (same_fuel, "같은 세대·연료(배기량·트림 섞임)"),
                        (base, "같은 세대만(연료·트림 섞임)")):
        if len(cand) >= MIN_GROUP_SIZE:
            return cand, label
    return base, "비교불가"


def add_market_gaps(items: list[dict], pool: list[dict]) -> None:
    for it in items:
        group, basis = peer_group(it, pool)
        it["group_basis"] = basis
        it["group_n"] = len(group)
        it["group_key"] = f"{it['model']} {it['year']}±1 / {basis}"
        if basis == "비교불가" or len(group) < MIN_GROUP_SIZE:
            it.update(group_median_price=None, group_median_km=None,
                      price_gap=None, km_gap=None,
                      group_note=f"비교불가(그룹 {len(group)}대<{MIN_GROUP_SIZE})")
            continue
        prices = [g["price"] for g in group]
        mp = statistics.median(prices)
        mk = statistics.median([g["km"] for g in group])
        spread = (max(prices) - min(prices)) / mp if mp else 0
        it["group_median_price"] = round(mp, 1)
        it["group_median_km"] = int(mk)
        it["price_gap"] = round((mp - it["price"]) / mp, 4) if mp else None
        it["km_gap"] = round((mk - it["km"]) / mk, 4) if mk else None
        # 트림까지 좁히지 못했고 산포가 크면 시세차를 그대로 믿지 말라고 표시한다.
        it["group_note"] = ("" if basis.endswith("트림") or spread <= TRIM_SPLIT_SPREAD
                            else f"비교군 가격 산포 {spread:.0%} — 시세차를 그대로 믿지 말 것")


def add_trim_rank(items: list[dict], pool: list[dict]) -> None:
    """세대 안에서 이 차의 트림이 몇 번째 등급인지 매긴다.

    '다시 팔지 않고 오래 탄다'면 감가보다 **같은 돈으로 얼마나 좋은 트림을 사는가**가
    중요하다. 같은 세대의 트림별 시세 중앙값 순서를 트림 등급의 대리 지표로 쓴다.
    (연식·주행거리가 섞여 있어 정확한 등급표는 아니고 시장이 보는 순서다.)
    """
    by_gen: dict[str, dict[str, list[int]]] = {}
    for p in pool:
        if p["model"] and p["trim"]:
            by_gen.setdefault(p["model"], {}).setdefault(p["trim"], []).append(p["price"])
    for it in items:
        trims = by_gen.get(it["model"], {})
        med = {t: statistics.median(v) for t, v in trims.items() if len(v) >= 2}
        it["equip_n"] = len([o for o in (it["options"] or "").split("|") if o])
        it["equip_total"] = len(OPTION_PATTERNS)
        if len(med) < 2 or it["trim"] not in med:
            it["trim_rank"], it["trim_total"] = None, len(med)
            continue
        order = sorted(med, key=lambda t: -med[t])
        it["trim_rank"] = order.index(it["trim"]) + 1
        it["trim_total"] = len(order)


# ── 시장 통계 (웹검색 대신 전체 재고에서 직접 뽑는 관점) ────────────────────
def market_stats(market: list[dict], pool: list[dict]) -> dict:
    """모델별 재고 수와 연식별 시세. 재고가 많은 차 = 부품·정비·재판매가 쉬운 차."""
    # 차종(model_group) 재고는 **순수 전기차를 제외하고** 센다.
    # 예: '아이오닉' 으로 묶으면 아이오닉 5·6(E-GMP 전기차, 부품이 전혀 다름)이 섞여
    # 아이오닉 하이브리드가 실제보다 흔한 차로 보인다(65대 vs 실제 하이브리드 10대).
    non_ev = [m for m in pool if (m["fuel_raw"] or "") != "전기"]
    by_model: dict[str, list[dict]] = {}
    for m in non_ev:
        if m["model_group"]:
            by_model.setdefault(m["model_group"], []).append(m)
    total = len(non_ev)
    stats = {}
    for name, cars in by_model.items():
        years = {}
        for c in cars:
            years.setdefault(c["year"], []).append(c["price"])
        stats[name] = {
            "count": len(cars),
            "share": round(len(cars) / total, 5),
            "median_price_by_year": {str(y): round(statistics.median(p), 1)
                                     for y, p in sorted(years.items()) if len(p) >= 2},
        }
    ranked = sorted(stats, key=lambda k: -stats[k]["count"])
    for i, name in enumerate(ranked, 1):
        stats[name]["rank"] = i

    # 세대(model)별 연식 시세 — 감가를 보여줄 때는 세대를 섞으면 안 된다.
    # (예: '그랜저'로 묶으면 HG·IG·GN7 이 섞여 곡선이 왜곡된다)
    gens: dict[str, dict] = {}
    for m in pool:
        if not m["model"] or not m["year"]:
            continue
        g = gens.setdefault(m["model"], {"count": 0, "by_year": {}, "by_seats": {}})
        g["count"] += 1
        g["by_year"].setdefault(m["year"], []).append(m["price"])
        g["by_seats"][str(m["seats"])] = g["by_seats"].get(str(m["seats"]), 0) + 1
    for name, g in gens.items():
        g["median_price_by_year"] = {str(y): round(statistics.median(p), 1)
                                     for y, p in sorted(g["by_year"].items()) if len(p) >= 2}
        g["year_counts"] = {str(y): len(p) for y, p in sorted(g["by_year"].items())}
        del g["by_year"]

    return {"total_comparable": total, "total_comparable_all": len(pool),
            "total_collected": len(market),
            "models": stats, "model_count": len(stats),
            "generations": gens, "generation_count": len(gens)}


# ── 점수 (분석용 표에서만 쓴다. 안내 페이지는 점수를 쓰지 않는다) ───────────
def score_items(items: list[dict]) -> None:
    for it in items:
        parts: dict[str, float] = {}
        pg, kg = it.get("price_gap"), it.get("km_gap")
        parts["price_gap"] = (min(max(pg, 0.0) / PRICE_GAP_FULL, 1.0) * W_PRICE_GAP
                              if pg is not None else 0.0)
        parts["km_gap"] = (min(max(kg, 0.0) / KM_GAP_FULL, 1.0) * W_KM_GAP
                           if kg is not None else 0.0)
        parts["accident"] = W_ACCIDENT.get(it["accident"], 0.0)
        # 소유자 변경·등록일은 상세 페이지(robots Disallow) 전용 필드라 판정 불가.
        # 전 매물에 동일하게 0점이므로 순위에는 영향이 없다(일정 오프셋).
        parts["owner"] = 0.0
        opts = set((it["options"] or "").split("|"))
        parts["options"] = W_OPTION_EACH * len([o for o in SCORE_OPTIONS if o in opts])
        parts["fuel"] = W_FUEL.get(it["fuel"], 0.0)
        parts["new_listing"] = 0.0
        it["score_parts"] = parts
        it["score"] = round(min(max(sum(parts.values()), 0.0), 100.0), 1)


CSV_FIELDS = ["id", "url", "maker", "model", "model_group", "full_name", "trim", "trim_series",
              "grade_name", "year_month", "year", "model_year", "km", "price", "total_cost",
              "total_cost_est", "fuel", "fuel_raw", "transmission", "cc", "seats",
              "body_type", "category_raw", "accident", "insurance_history", "owner_changes",
              "options", "airbags", "adas", "adas_n", "parking_aid_n",
              "equip_n", "equip_total", "trim_rank", "trim_total",
              "location", "listed_date", "warranty", "photo",
              "use_tag", "rent_reg", "reg_type", "group_key", "group_n",
              "group_median_price", "group_median_km", "price_gap", "km_gap",
              "group_basis", "group_note", "score"]


def write_csv(items: list[dict], path: str, collected_at: str, total_cnt: int,
              pool_cnt: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# 출처 K카(kcar.com) 직영 매물 목록 API. 수집 {collected_at}. "
                 f"직영 재고 전체 {total_cnt}대 수집(시세 비교군 {pool_cnt}대) 중 "
                 f"조건 통과 {len(items)}대. 개인 검토용 비공식 분석, 상업적 이용 금지. "
                 f"total_cost/insurance_history/owner_changes/listed_date/warranty 는 "
                 f"상세 페이지가 robots.txt Disallow 라 미수집(null).\n")
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for it in sorted(items, key=lambda x: -x["score"]):
            w.writerow(it)


def main() -> None:
    ap = argparse.ArgumentParser(description="K카 직영 전체 재고 수집·시세 비교·후보 선별")
    ap.add_argument("--budget", type=int, default=2200, help="차량가 상한(만원)")
    ap.add_argument("--total-budget", type=int, default=2400,
                    help="총 구매비용 상한(만원, 추정치 기준)")
    ap.add_argument("--year", type=int, default=2020, help="연식 하한")
    ap.add_argument("--km", type=int, default=100000, help="주행거리 상한")
    ap.add_argument("--seats", type=int, default=5, help="좌석 수 (기본 5인승)")
    ap.add_argument("--suv-max", choices=("small", "compact", "none"), default="compact",
                    help="SUV 크기 상한: small=셀토스급, compact=투싼·스포티지급(기본), "
                         "none=제한 없음(싼타페·쏘렌토 포함)")
    ap.add_argument("--no-suv-limit", dest="suv_max", action="store_const", const="none",
                    help="(구 옵션) --suv-max none 과 같다")
    ap.add_argument("--fuel", default="gasoline,hybrid,lpg,diesel",
                    help="허용 연료 (gasoline,hybrid,lpg,diesel)")
    ap.add_argument("--out", default="data/listings.csv")
    ap.add_argument("--limit", type=int, default=100, help="페이지당 건수")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=1.8, help="요청 간 대기(초)")
    ap.add_argument("--raw-dir", default="data/raw/market")
    ap.add_argument("--use-cache", action="store_true",
                    help="네트워크 요청 없이 원본 캐시로 재계산")
    args = ap.parse_args()
    args.fuel_set = {FUEL_ALIASES[f.strip()] for f in args.fuel.split(",") if f.strip()}

    try:
        rows, total_cnt, collected_at = collect(args)
    except Blocked as e:
        sys.exit(f"중단(차단 감지): {e}")

    # 전체 재고 정규화 (중복 제거)
    seen, market = set(), []
    for row in rows:
        cd = row.get("carCd")
        if not cd or cd in seen:
            continue
        seen.add(cd)
        market.append(normalize(row))

    pool = comparable_pool(market)

    # 조건 필터
    items, rejects = [], {}
    for it in market:
        why = reject_reason(it, args)
        if why:
            rejects[why] = rejects.get(why, 0) + 1
        else:
            items.append(it)

    add_market_gaps(items, pool)
    add_trim_rank(items, pool)
    score_items(items)
    write_csv(items, args.out, collected_at, len(market), len(pool))

    stats = market_stats(market, pool)
    outdir = os.path.dirname(args.out) or "."
    with open(os.path.join(outdir, "market_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)

    meta = {
        "collected_at": collected_at,
        "source": "K카(kcar.com) 직영 매물 목록 API (전체 재고)",
        "collected": len(market),
        "api_total": total_cnt,
        "comparable_pool": len(pool),
        "passed": len(items),
        "rejects": rejects,
        "conditions": {"budget": args.budget, "total_budget": args.total_budget,
                       "year": args.year, "km": args.km, "seats": args.seats,
                       "fuel": sorted(args.fuel_set),
                       "exclude": ["경차", "화물", "승합", "미니밴", "렌터카", "사고"]},
        "weights": {"price_gap": W_PRICE_GAP, "km_gap": W_KM_GAP,
                    "accident": W_ACCIDENT, "owner_few": W_OWNER_FEW,
                    "option_each": W_OPTION_EACH, "fuel": W_FUEL,
                    "new_listing": W_NEW_LISTING},
        "unavailable_fields": ["total_cost", "insurance_history", "owner_changes",
                               "listed_date", "warranty"],
        "unscored_items": ["소유자 변경 1회 이하(10점)", "등록 7일 이내(+3점)"],
        "max_attainable_score": (W_PRICE_GAP + W_KM_GAP + max(W_ACCIDENT.values())
                                 + W_OPTION_EACH * len(SCORE_OPTIONS)
                                 + max(W_FUEL.values())),
    }
    with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f"\n직영 재고 {len(market):,}대 수집(API 총 {total_cnt:,}) "
          f"→ 시세 비교군 {len(pool):,}대 → 조건 통과 {len(items):,}대")
    for why, n in sorted(rejects.items(), key=lambda x: -x[1]):
        print(f"  제외 {n:5,d}  {why}")
    ncmp = sum(1 for i in items if i["price_gap"] is None)
    print(f"  시세 비교 불가(그룹<{MIN_GROUP_SIZE}): {ncmp}대")
    print(f"CSV: {args.out} / 시장통계: {outdir}/market_stats.json")


if __name__ == "__main__":
    main()
