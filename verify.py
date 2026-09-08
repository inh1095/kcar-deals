#!/usr/bin/env python3
"""검증 스크립트 (지시서 2-6).

    python3.11 verify.py

1. TOP 15 중 3대를 **개별 재조회**해 CSV 값(가격·주행거리·사고이력·연식)과 대조한다.
   지시서는 "실제 상세 페이지와 대조"를 요구하지만 상세 페이지는 robots.txt Disallow
   이므로 조회하지 않는다. 대신 허용된 목록 API에 `wr_in_car_cd`로 **차량 단건 조회**를
   새로 보내 대조한다(페이지네이션 캐시가 아닌 독립 요청이므로 파싱·수집 오류를 잡아낸다).
   사람이 눈으로 볼 상세 페이지 URL도 함께 출력한다.
2. docs/all.html 의 표 행 수가 CSV와 일치하는지 HTML 파서로 확인하고,
   docs/index.html(어머님용 가이드)의 사이트 규칙을 함께 검사한다.
3. 사이트 규칙(noindex, 사진 없음, 외부 스크립트·폰트 없음)을 검사한다.
4. 시세 그룹 이상치(트림 혼재·비교 불가)를 집계한다.
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
import time
from html.parser import HTMLParser

from search_kcar import (DETAIL_URL, MIN_GROUP_SIZE, make_session, post_list,
                         Blocked, fetch_robots, robots_allows, LIST_PAGE)

CSV_PATH = "data/listings.csv"
HTML_PATH = "docs/all.html"
GUIDE_PATH = "docs/index.html"
SAMPLE = 3
SEED = 20260908


def load_csv() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


class Scan(HTMLParser):
    """표 행 수 + 사이트 규칙 검사."""

    def __init__(self):
        super().__init__()
        self.table_id = None
        self.in_tbody = False
        self.rows: dict[str, int] = {}
        self.imgs = 0
        self.ext_scripts: list[str] = []
        self.ext_links: list[str] = []
        self.robots_meta = None
        self.titles = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.table_id = a.get("id")
            self.rows.setdefault(self.table_id or "?", 0)
        elif tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody and self.table_id:
            self.rows[self.table_id] += 1
        elif tag == "img":
            self.imgs += 1
        elif tag == "script" and a.get("src"):
            self.ext_scripts.append(a["src"])
        elif tag == "link" and a.get("href", "").startswith(("http", "//")):
            self.ext_links.append(a["href"])
        elif tag == "meta" and a.get("name") == "robots":
            self.robots_meta = a.get("content")

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_tbody = False
        elif tag == "table":
            self.table_id = None


def main() -> None:
    rows = load_csv()
    by_id = {r["id"]: r for r in rows}
    top15 = sorted(rows, key=lambda r: (-float(r["score"]), int(r["price"])))[:15]
    ok = True

    print("=" * 78)
    print("1) TOP 15 중 3대 원본 재조회 대조 (상세 페이지는 robots Disallow → 미조회)")
    print("=" * 78)
    session = make_session()
    rules = fetch_robots(session)
    assert robots_allows(rules, LIST_PAGE), "목록 페이지가 Disallow 로 바뀌었다"
    time.sleep(1.8)

    picks = random.Random(SEED).sample(top15, SAMPLE)
    for r in picks:
        try:
            data = post_list(session, {"wr_in_car_cd": r["id"], "limit": 5})
        except Blocked as e:
            print(f"  중단(차단 감지): {e}")
            sys.exit(2)
        live = next((x for x in (data.get("rows") or []) if x.get("carCd") == r["id"]), None)
        print(f"\n  [{r['id']}] {r['maker']} {r['model']} {r['trim']}")
        print(f"    상세 페이지(사람이 직접 확인): {DETAIL_URL.format(r['id'])}")
        if live is None:
            print("    재조회 결과 없음 — 판매 완료됐을 수 있다(수집 시점 이후 변동).")
            continue
        checks = [
            ("차량가(만원)", r["price"], str(live.get("prc"))),
            ("주행거리(km)", r["km"], str(live.get("milg"))),
            ("사고이력", r["accident"], (live.get("acdtHistCnts") or "").strip()),
            ("연식", r["year_month"], f"{str(live.get('mfgDt'))[:4]}-{str(live.get('mfgDt'))[4:6]}"),
            ("차명", r["full_name"], live.get("carWhlNm")),
        ]
        for label, mine, theirs in checks:
            same = str(mine).strip() == str(theirs).strip()
            ok &= same
            print(f"    {'OK  ' if same else 'DIFF'} {label}: CSV={mine!r} / 재조회={theirs!r}")
        time.sleep(1.8)

    print()
    print("=" * 78)
    print("2) docs/all.html (분석용 전체 표) 행 수 대조 + 사이트 규칙 검사")
    print("=" * 78)
    scan = Scan()
    scan.feed(open(HTML_PATH, encoding="utf-8").read())
    n_html = scan.rows.get("all", -1)
    same = n_html == len(rows)
    ok &= same
    print(f"  {'OK  ' if same else 'DIFF'} 전체 표(#all) 행 수: HTML={n_html} / CSV={len(rows)}")
    for tid, n in sorted(scan.rows.items()):
        if tid != "all":
            print(f"       참고: table#{tid} {n}행")
    rules_check = [
        ("noindex,nofollow 메타", scan.robots_meta == "noindex,nofollow", scan.robots_meta),
        ("사진(img 태그) 없음", scan.imgs == 0, f"{scan.imgs}개"),
        ("외부 스크립트 없음", not scan.ext_scripts, scan.ext_scripts),
        ("외부 폰트·CSS 없음", not scan.ext_links, scan.ext_links),
    ]
    for label, passed, detail in rules_check:
        ok &= passed
        print(f"  {'OK  ' if passed else 'FAIL'} {label}: {detail}")
    body = open(HTML_PATH, encoding="utf-8").read()
    for word in ("개인 검토용", "상업적 이용 금지", "kcar.com", "수집 일시"):
        passed = word in body
        ok &= passed
        print(f"  {'OK  ' if passed else 'FAIL'} 필수 문구 '{word}' 포함")
    passed = "img.kcar.com" not in body
    ok &= passed
    print(f"  {'OK  ' if passed else 'FAIL'} 사진 URL(img.kcar.com) 미게시")

    print()
    print("=" * 78)
    print("2-2) docs/index.html (어머님용 가이드) 검사")
    print("=" * 78)
    gscan = Scan()
    gbody = open(GUIDE_PATH, encoding="utf-8").read()
    gscan.feed(gbody)
    guide_rules = [
        ("noindex,nofollow 메타", gscan.robots_meta == "noindex,nofollow", gscan.robots_meta),
        ("사진(img 태그) 없음", gscan.imgs == 0, f"{gscan.imgs}개"),
        ("외부 스크립트 없음", not gscan.ext_scripts, gscan.ext_scripts),
        ("외부 폰트·CSS 없음", not gscan.ext_links, gscan.ext_links),
        ("사진 URL 미게시", "img.kcar.com" not in gbody, "-"),
        ("출처·수집일시 표기", "수집 일시" in gbody and "kcar.com" in gbody, "-"),
        ("면책 문구", "상업적 이용 금지" in gbody, "-"),
        ("미수집 필드 한계 명시", "보험 수리 이력" in gbody, "-"),
        ("리콜 조회 안내", "car.go.kr" in gbody, "-"),
        # 불투명한 종합점수로 줄 세우지 않는다는 것을 본문에서 밝히고 있는지 확인.
        # (순위는 '10년 총지출'과 '만족 요소 개수'처럼 뜻이 분명한 숫자만 쓴다)
        ("점수로 줄 세우지 않음을 명시",
         ("점수가 아니라" in gbody) or ("점수로 줄 세우지" in gbody), "-"),
        ("순위 기준을 숫자로 공개", "10년 총지출" in gbody and "만족 요소" in gbody, "-"),
    ]
    for label, passed, detail in guide_rules:
        ok &= passed
        print(f"  {'OK  ' if passed else 'FAIL'} {label}: {detail}")
    # 태그 균형: html.parser 가 끝까지 파싱했고 body/main 이 닫혔는지
    for tag in ("</main>", "</body>", "</html>"):
        passed = tag in gbody
        ok &= passed
        print(f"  {'OK  ' if passed else 'FAIL'} {tag} 존재")
    # 탭별 비교표: tbl3(전체)는 CSV 전체와 같아야 하고, tbl1/tbl2 는 하한을 통과한 부분집합
    t3 = gscan.rows.get("tbl3", -1)
    passed = t3 == len(rows)
    ok &= passed
    print(f"  {'OK  ' if passed else 'DIFF'} 전체 탭 표(tbl3) 행 수: 가이드={t3} / CSV={len(rows)}")
    for tid in ("tbl1", "tbl2"):
        n = gscan.rows.get(tid, -1)
        sub_ok = 0 < n <= len(rows)
        ok &= sub_ok
        print(f"  {'OK  ' if sub_ok else 'FAIL'} {tid} 행 수 {n} (0 < n <= {len(rows)})")
    for need in ("찐가성비", "가심비", 'id="t1"', 'id="t2"', 'id="t3"', 'class="panel"'):
        p_ok = need in gbody
        ok &= p_ok
        print(f"  {'OK  ' if p_ok else 'FAIL'} 탭 구성 '{need}' 존재")
    print(f"       참고: 가이드 내 표 {dict(gscan.rows)}")

    print()
    print("=" * 78)
    print("3) 시세 그룹 이상치")
    print("=" * 78)
    notes: dict[str, int] = {}
    for r in rows:
        if r.get("group_note"):
            notes[r["group_note"]] = notes.get(r["group_note"], 0) + 1
    if notes:
        for note, n in sorted(notes.items(), key=lambda x: -x[1]):
            print(f"  {n:4d}대  {note}")
    else:
        print("  없음")
    ncmp = sum(1 for r in rows if r["price_gap"] == "")
    print(f"  시세 비교 불가(그룹 {MIN_GROUP_SIZE}대 미만): {ncmp}대 — 절대값만 표시")

    print()
    print("결과:", "전부 통과" if ok else "불일치 항목 있음(위 DIFF/FAIL 확인)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
