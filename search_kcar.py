#!/usr/bin/env python3
"""K카(kcar.com) 직영 중고차 매물 수집 + 시세 비교 + 꿀매물 점수 계산.

LLM 없이 단독 실행된다.

    python3.11 search_kcar.py --budget 1300 --year 2017 --km 120000 \
        --fuel gasoline,hybrid,lpg,diesel --out data/listings.csv

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
import urllib.parse
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
TRIM_SPLIT_SPREAD = 0.40  # 그룹 가격 산포((최고-최저)/중앙값)가 이보다 크면 트림 계열로 세분.
                          # 실측 분포 p50=23% p75=31% p90=35% 기준으로 p90 바로 위에 두어
                          # 명백한 트림 혼재(예: 스토닉 1.0터보/1.4가솔린/1.6디젤)만 걸린다.

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

# ── 조건 (지시서 1절) ────────────────────────────────────────────────────────
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
# carctgrNm(크기 기준 분류) → 지시서의 차종. None 이면 제외 대상.
BODY_FROM_CTGR = {"SUV": "SUV", "RV": "미니밴",
                  "소형차": "세단", "준중형차": "세단", "중형차": "세단",
                  "준대형차": "세단", "대형차": "세단",
                  "경차": None, "경승합차": None, "승합차": None,
                  "화물차": None, "스포츠카": None}
HATCHBACK_HINTS = ["i30", "벨로스터", "K3 GT", "프라이드", "아이오닉", "씨드", "i20", "해치"]
KEICAR_HINTS = ["모닝", "레이", "캐스퍼", "스파크", "마티즈", "다마스", "라보"]
ACCIDENT_OK = {"무사고", "단순수리"}
OPTION_PATTERNS = {
    "후방카메라": ["카메라 : 후방"],
    "통풍시트": ["통풍시트"],
    "열선시트": ["열선시트"],
    "스마트키": ["스마트키"],
    "내비": ["내비게이션"],
    "크루즈": ["크루즈컨트롤"],
    "선루프": ["선루프", "썬루프"],
}
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
    if r.status_code in (403, 429) or r.status_code == 503:
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
    """목록 API를 페이지네이션해 원본 행을 모은다. 반환: (rows, totalCnt, 수집일시)."""
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
    print(f"[robots] {LIST_PAGE} 허용 확인. 상세 페이지 Disallow 목록: "
          f"{[d for d in rules['disallow'] if 'detail' in d or 'car/info' in d]} → 조회하지 않음")
    time.sleep(args.sleep)

    base = {
        "wr_lt_prc": str(args.budget),
        "wr_gt_mfg_dt": f"{args.year}01",
        "wr_lt_milg": str(args.km),
        "limit": args.limit,
    }
    collected_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    rows: list[dict] = []
    total = 0
    page = 1
    while page <= args.max_pages:
        data = post_list(session, {**base, "pageno": page})
        total = data.get("totalCnt", 0)
        page_rows = data.get("rows") or []
        with open(os.path.join(raw_dir, f"page_{page:02d}.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        rows += page_rows
        print(f"[fetch] page {page}/{data.get('totalPageCnt', '?')} rows={len(page_rows)} "
              f"total={total}", flush=True)
        if not page_rows or len(rows) >= total or page >= data.get("totalPageCnt", page):
            break
        page += 1
        time.sleep(args.sleep)

    with open(os.path.join(raw_dir, "collected_at.txt"), "w", encoding="utf-8") as fh:
        fh.write(collected_at + "\n")
    return rows, total, collected_at


# ── 정규화 / 필터 ────────────────────────────────────────────────────────────
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
    found = []
    for label, pats in OPTION_PATTERNS.items():
        if any(p in raw for p in pats):
            found.append(label)
    return found


def normalize(row: dict) -> dict | None:
    """원본 행 → 정리된 매물 dict. 조건 미달이면 (사유, None) 대신 reject 이유를 담아 반환."""
    car_cd = row.get("carCd")
    mfg = str(row.get("mfgDt") or "")
    price = to_int(row.get("prc"))
    km = to_int(row.get("milg"))
    fuel = FUEL_FROM_KCAR.get(row.get("fuelNm") or "")
    body = body_type(row)
    accident = (row.get("acdtHistCnts") or "").strip()
    use = row.get("useNm") or ""
    item = {
        "id": car_cd,
        "url": DETAIL_URL.format(car_cd),
        "maker": row.get("mnuftrNm"),
        "model": row.get("modelNm") or row.get("modelGrpNm"),
        "model_group": row.get("modelGrpNm"),
        "full_name": row.get("carWhlNm"),
        "trim": " ".join(x for x in [row.get("grdNm"), row.get("grdDtlNm")]
                         if x and x != "세부등급 없음").strip(),
        "trim_series": (row.get("grdNm") or "").split(" ")[0],
        "year_month": f"{mfg[:4]}-{mfg[4:6]}" if len(mfg) >= 6 else None,
        "year": to_int(mfg[:4]),
        "model_year": row.get("prdcnYr"),
        "km": km,
        "price": price,
        "total_cost": None,          # K카 표시 총 구매비용: 상세 페이지 Disallow → 미수집
        "total_cost_est": (round(price * (1 + ACQUISITION_TAX_RATE) + TRANSFER_FEE_MANWON)
                           if price is not None else None),
        "fuel": fuel,
        "fuel_raw": row.get("fuelNm"),
        "transmission": row.get("trnsmsnNm"),
        "cc": to_int(row.get("engdispmnt")),
        "body_type": body,
        "category_raw": row.get("carctgrNm"),
        "accident": accident,
        "insurance_history": None,   # 상세 페이지 Disallow → 미수집
        "owner_changes": None,       # 상세 페이지 Disallow → 미수집
        "options": "|".join(options_of(row)),
        "location": " ".join(x for x in [row.get("cntrNm"), row.get("cntrRgnNm")] if x),
        "listed_date": None,         # 상세 페이지 Disallow → 미수집
        "warranty": None,            # 상세 페이지 Disallow → 미수집
        "photo": row.get("msizeImgPath") or row.get("lsizeImgPath"),
        # useNm 은 '이력'이 아니라 K카의 추천 용도 태그다. 968대 표본에서 연료와 100% 일치
        # (LPG·하이브리드·디젤 전량 '영업용', 가솔린 0건) → 영업용 이력 판정에 쓸 수 없다.
        # 실제 영업용/렌터카 이력은 상세 보험이력(robots Disallow)에서 확인해야 한다.
        "use_tag": use,
        "rent_reg": row.get("rentRegYn"),
        "reg_type": row.get("regType"),
        "seller_note": row.get("simcDesc"),
    }
    return item


def reject_reason(item: dict, args) -> str | None:
    if item["maker"] not in ALLOWED_MAKERS:
        return "제조사"
    if item["body_type"] is None:
        return "차종제외(경차/화물/승합)"
    if item["fuel"] is None or item["fuel"] not in args.fuel_set:
        return "연료"
    if item["accident"] not in ACCIDENT_OK:
        return "사고이력"
    # 렌터카 제외. use_tag 는 추천 태그이므로 쓰지 않고, 등록 플래그와 차명·트림에 박힌
    # 표기('...LPI 렌터카 프레스티지', '(렌터카용)')로 판단한다. simcDesc 는 대부분
    # '렌트이력無' 같은 긍정 문구라 판단 근거로 쓰지 않는다.
    if (item["rent_reg"] or "N").upper() == "Y" or (item["reg_type"] or "SELL") != "SELL":
        return "렌터카/렌트등록"
    if "렌터카" in (item["full_name"] or ""):
        return "렌터카 트림 표기"
    if item["price"] is None or item["price"] > args.budget:
        return "예산초과"
    if item["total_cost_est"] is not None and item["total_cost_est"] > args.total_budget:
        return "총비용초과"
    if item["year"] is None or item["year"] < args.year:
        return "연식"
    if item["km"] is None or item["km"] > args.km:
        return "주행거리"
    return None


# ── 시세 비교 ────────────────────────────────────────────────────────────────
def peers_of(item: dict, pool: list[dict], key: str) -> list[dict]:
    """같은 model(또는 model+트림계열) + 연식 ±1년."""
    return [p for p in pool
            if p[key] == item[key] and p["model"] == item["model"]
            and abs((p["year"] or 0) - (item["year"] or 0)) <= 1]


def add_market_gaps(items: list[dict]) -> None:
    for it in items:
        group = peers_of(it, items, "model")
        note = ""
        if len(group) >= MIN_GROUP_SIZE:
            prices = [g["price"] for g in group]
            spread = (max(prices) - min(prices)) / statistics.median(prices)
            if spread > TRIM_SPLIT_SPREAD:
                sub = peers_of(it, items, "trim_series")
                if len(sub) >= MIN_GROUP_SIZE:
                    group, note = sub, "트림계열 세분(가격 산포 큼)"
                else:
                    note = f"트림 혼재 주의(산포 {spread:.0%})"
        it["group_key"] = f"{it['model']} {it['year']}±1"
        if note.startswith("트림계열"):
            it["group_key"] += f" / {it['trim_series']} 계열"
        it["group_n"] = len(group)
        it["group_note"] = note
        if len(group) < MIN_GROUP_SIZE:
            it["group_median_price"] = None
            it["group_median_km"] = None
            it["price_gap"] = None
            it["km_gap"] = None
            it["group_note"] = f"비교불가(그룹 {len(group)}대<{MIN_GROUP_SIZE})"
            continue
        mp = statistics.median([g["price"] for g in group])
        mk = statistics.median([g["km"] for g in group])
        it["group_median_price"] = round(mp, 1)
        it["group_median_km"] = int(mk)
        it["price_gap"] = round((mp - it["price"]) / mp, 4) if mp else None
        it["km_gap"] = round((mk - it["km"]) / mk, 4) if mk else None


# ── 점수 ─────────────────────────────────────────────────────────────────────
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
              "year_month", "year", "model_year", "km", "price", "total_cost",
              "total_cost_est", "fuel", "fuel_raw", "transmission", "cc", "body_type",
              "category_raw", "accident", "insurance_history", "owner_changes",
              "options", "location", "listed_date", "warranty", "photo",
              "use_tag", "rent_reg", "reg_type", "group_key", "group_n", "group_median_price",
              "group_median_km", "price_gap", "km_gap", "group_note", "score"]


def write_csv(items: list[dict], path: str, collected_at: str, total_cnt: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"# 출처 K카(kcar.com) 직영 매물 목록 API. 수집 {collected_at}. "
                 f"수집 {total_cnt}대 중 조건 통과 {len(items)}대. "
                 f"개인 검토용 비공식 분석, 상업적 이용 금지. "
                 f"total_cost/insurance_history/owner_changes/listed_date/warranty 는 "
                 f"상세 페이지가 robots.txt Disallow 라 미수집(null).\n")
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for it in sorted(items, key=lambda x: -x["score"]):
            w.writerow(it)


def main() -> None:
    ap = argparse.ArgumentParser(description="K카 직영 중고차 꿀매물 수집·점수화")
    ap.add_argument("--budget", type=int, default=1300, help="차량가 상한(만원)")
    ap.add_argument("--total-budget", type=int, default=1400, help="총 구매비용 상한(만원, 추정치 기준)")
    ap.add_argument("--year", type=int, default=2017, help="연식 하한")
    ap.add_argument("--km", type=int, default=120000, help="주행거리 상한")
    ap.add_argument("--fuel", default="gasoline,hybrid,lpg,diesel",
                    help="허용 연료 (gasoline,hybrid,lpg,diesel)")
    ap.add_argument("--out", default="data/listings.csv")
    ap.add_argument("--limit", type=int, default=100, help="페이지당 건수")
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--sleep", type=float, default=1.8, help="요청 간 대기(초)")
    ap.add_argument("--raw-dir", default="data/raw/pages")
    ap.add_argument("--use-cache", action="store_true",
                    help="네트워크 요청 없이 data/raw/pages 의 원본으로 재계산")
    args = ap.parse_args()
    args.fuel_set = {FUEL_ALIASES[f.strip()] for f in args.fuel.split(",") if f.strip()}

    try:
        rows, total_cnt, collected_at = collect(args)
    except Blocked as e:
        sys.exit(f"중단(차단 감지): {e}")

    seen, items, rejects = set(), [], {}
    for row in rows:
        if not row.get("carCd") or row["carCd"] in seen:
            continue
        seen.add(row["carCd"])
        it = normalize(row)
        why = reject_reason(it, args)
        if why:
            rejects[why] = rejects.get(why, 0) + 1
            continue
        items.append(it)

    add_market_gaps(items)
    score_items(items)
    write_csv(items, args.out, collected_at, len(seen))

    meta = {
        "collected_at": collected_at,
        "source": "K카(kcar.com) 직영 매물 목록 API",
        "collected": len(seen),
        "api_total": total_cnt,
        "passed": len(items),
        "rejects": rejects,
        "conditions": {"budget": args.budget, "total_budget": args.total_budget,
                       "year": args.year, "km": args.km,
                       "fuel": sorted(args.fuel_set)},
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
    meta_path = os.path.join(os.path.dirname(args.out) or ".", "meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f"\n수집 {len(seen)}대(API 총 {total_cnt}) → 조건 통과 {len(items)}대")
    for why, n in sorted(rejects.items(), key=lambda x: -x[1]):
        print(f"  제외 {n:4d}  {why}")
    ncmp = sum(1 for i in items if i["price_gap"] is None)
    print(f"  시세 비교 불가(그룹<{MIN_GROUP_SIZE}): {ncmp}대")
    print(f"CSV: {args.out}")
    for i, it in enumerate(sorted(items, key=lambda x: -x["score"])[:10], 1):
        print(f"  {i:2d}. {it['score']:5.1f} {it['maker']} {it['model']} {it['trim']} "
              f"{it['year_month']} {it['km']:,}km {it['price']}만원 {it['accident']}")


if __name__ == "__main__":
    main()
