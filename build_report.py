#!/usr/bin/env python3
"""data/listings.csv → docs/report.md + docs/all.html (분석용 전체 표).

LLM 없이 단독 실행된다. "왜 좋은지"·"가서 확인할 것" 문구도 전부 규칙 기반이다.

    python3.11 build_report.py --csv data/listings.csv --outdir docs

사이트 규칙: 사진 없음, 외부 스크립트·폰트 없음(단일 HTML, 인라인 CSS/JS),
noindex,nofollow, 상단에 수집 일시·출처·면책, 정렬 가능한 표, 모바일 반응형.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import statistics
from collections import defaultdict

TOP_N = 15
SEG_N = 5
DISCLAIMER = ("개인 검토용 비공식 분석입니다. 가격·매물 상태는 수시로 변동하며, "
              "구매 판단은 반드시 매물 페이지에서 직접 확인하세요. 상업적 이용 금지.")


# ── 로드 ─────────────────────────────────────────────────────────────────────
def load(csv_path: str) -> tuple[list[dict], dict]:
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(line for line in fh if not line.startswith("#")))
    meta_path = os.path.join(os.path.dirname(csv_path) or ".", "meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    for r in rows:
        for k in ("km", "price", "year", "group_n", "group_median_km", "total_cost_est"):
            r[k] = int(float(r[k])) if r.get(k) not in ("", None) else None
        for k in ("score", "price_gap", "km_gap", "group_median_price"):
            r[k] = float(r[k]) if r.get(k) not in ("", None) else None
        r["opt_list"] = [o for o in (r.get("options") or "").split("|") if o]
    return rows, meta


# ── 규칙 기반 코멘트 ─────────────────────────────────────────────────────────
def why_good(r: dict) -> str:
    bits = []
    if r["price_gap"] is not None and r["price_gap"] > 0.02:
        gap_won = r["group_median_price"] - r["price"]
        bits.append(f"{r.get('group_basis','비교군')} {r['group_n']}대 중앙값 "
                    f"{r['group_median_price']:,.0f}만원보다 "
                    f"{gap_won:,.0f}만원({r['price_gap']:.0%}) 저렴")
    elif r["price_gap"] is None:
        bits.append(f"비교군 부족({r['group_n']}대)이라 시세 비교 없이 절대값 기준 "
                    f"{r['price']:,}만원")
    if r["km_gap"] is not None and r["km_gap"] > 0.05:
        bits.append(f"주행거리도 비교군 중앙값 {r['group_median_km']:,}km보다 "
                    f"{r['group_median_km'] - r['km']:,}km 적음")
    elif r["km"] is not None and r["km"] <= 70000:
        bits.append(f"주행 {r['km']:,}km로 절대적으로 짧음")
    if r["accident"] == "무사고":
        bits.append("K카 진단 무사고")
    key_opts = [o for o in ("후방카메라", "열선시트", "통풍시트", "스마트키", "내비", "크루즈")
                if o in r["opt_list"]]
    if len(key_opts) >= 4:
        bits.append("출퇴근 편의 옵션 " + "·".join(key_opts[:6]) + " 확보")
    if r["fuel"] == "하이브리드":
        bits.append("하이브리드로 출퇴근 유지비 유리")
    if not bits:
        bits.append(f"조건 내 {r['price']:,}만원 / {r['km']:,}km")
    return "왜 좋은지: " + ". ".join(bits) + "."


def what_to_check(r: dict) -> str:
    bits = []
    if r["accident"] == "단순수리":
        bits.append("K카 진단 '단순수리' — 교환·판금 부위가 어디인지(외판 1~2곳인지 프레임 포함인지) "
                    "진단서에서 직접 확인")
    bits.append("소유자 변경 횟수와 보험이력(내 차 피해·타 차 가해, 침수·전손)은 이 분석에 포함되지 "
                "않았으니 매물 페이지에서 확인")
    if r["km"] is not None and r["km"] >= 100000:
        bits.append(f"{r['km']:,}km — 타이어·브레이크 패드 마모, 미션오일·타이밍벨트 교체 이력")
    if r["fuel"] == "디젤":
        bits.append("디젤: DPF 상태와 매연 저감장치 이력(단거리 출퇴근이면 DPF 재생 불리)")
    if r["fuel"] == "LPG":
        bits.append("LPG: 봄베(연료탱크) 검사 유효기간과 트렁크 공간 잠식 정도")
    if r["fuel"] == "하이브리드":
        bits.append("하이브리드: 구동 배터리 잔존 성능과 보증 잔여 기간")
    if r["price_gap"] is not None and r["price_gap"] >= 0.25:
        bits.append(f"시세보다 {r['price_gap']:.0%} 싼 이유가 옵션 차이·색상·판금 때문인지 확인"
                    "(과도하게 싼 데는 이유가 있다)")
    if r.get("group_note"):
        bits.append(f"시세 그룹 주의: {r['group_note']}")
    if "통풍시트" not in r["opt_list"]:
        bits.append("통풍시트 미확인 — 여름 출퇴근 고려 시 실물 확인")
    bits.append(f"총 구매비용은 K카 표시값이 아니라 추정({r['total_cost_est']:,}만원)이므로 "
                "이전비·매도비 실제 견적 확인")
    return "가서 확인할 것: " + ". ".join(bits) + "."


# ── 집계 ─────────────────────────────────────────────────────────────────────
def group_table(rows: list[dict]) -> list[dict]:
    """그룹(세대+연식±1년)별 시세표. 3대 이상 그룹만."""
    buckets = defaultdict(list)
    for r in rows:
        buckets[r["group_key"]].append(r)
    out = []
    for key, items in buckets.items():
        if len(items) < 3:
            continue
        prices = [i["price"] for i in items]
        kms = [i["km"] for i in items]
        out.append({
            "group": key, "n": len(items),
            "median_price": statistics.median(prices),
            "min_price": min(prices), "max_price": max(prices),
            "median_km": int(statistics.median(kms)),
            "note": next((i["group_note"] for i in items if i["group_note"]), ""),
        })
    return sorted(out, key=lambda x: (-x["n"], x["group"]))


def top(rows: list[dict], n: int, pred=None) -> list[dict]:
    pool = [r for r in rows if pred(r)] if pred else list(rows)
    return sorted(pool, key=lambda r: (-r["score"], r["price"]))[:n]


# ── Markdown ─────────────────────────────────────────────────────────────────
def md_top_table(items: list[dict]) -> list[str]:
    out = ["| # | 차명 | 트림 | 연식 | 주행 | 차량가 | 총비용(추정) | 사고 | 점수 | 링크 |",
           "|---:|---|---|---|---:|---:|---:|---|---:|---|"]
    for i, r in enumerate(items, 1):
        out.append(f"| {i} | {r['maker']} {r['model']} | {r['trim'] or '-'} | {r['year_month']} "
                   f"| {r['km']:,}km | {r['price']:,}만 | {r['total_cost_est']:,}만 "
                   f"| {r['accident']} | {r['score']:.1f} | [매물]({r['url']}) |")
    return out


def build_md(rows: list[dict], meta: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# K카 국산 중고차 꿀매물 리스트")
    A("")
    A(f"- 수집 일시: **{meta.get('collected_at', '?')}**")
    A(f"- 출처: **K카(kcar.com)** 직영(내차사기) 매물 목록. 다른 중고차 사이트는 쓰지 않았다.")
    A(f"- 수집 매물 **{meta.get('collected', len(rows)):,}대** → 조건 통과 **{meta.get('passed', len(rows)):,}대**")
    A(f"- {DISCLAIMER}")
    A("")
    A("## 준수 범위")
    A("")
    A("`kcar.com/robots.txt`는 목록 페이지(`/bc/search`)를 Allow, **상세 페이지"
      "(`/bc/detail/carInfoDtl?`, `/car/info/`)를 Disallow**한다. 그래서 상세 페이지는 "
      "한 건도 요청하지 않고 목록 데이터만 사용했다(요청 간 1.8초, 순차, 차단 없음). "
      "그 결과 아래 필드는 **수집하지 않았고 분석에 반영되지 않았다**: "
      "총 구매비용(K카 표시값), 보험 이력, 소유자 변경 횟수, 매물 등록일, 보증. "
      "표의 총비용은 `차량가 + 취득세 7% + 매도·이전대행 3만원` **추정치**다. "
      "사진은 게시하지 않으며, 각 매물의 K카 페이지 링크만 제공한다.")
    A("")
    A("## 조건")
    A("")
    c = meta.get("conditions", {})
    A(f"현대·기아(제네시스 포함) / 세단·해치백·SUV·미니밴 / 경차·화물·승합·렌터카 제외 / "
      f"차량가 {c.get('budget', 1300):,}만원 이하(총 {c.get('total_budget', 1400):,}만원 이하) / "
      f"{c.get('year', 2017)}년식 이상 / {c.get('km', 120000):,}km 이하 / "
      f"연료 {', '.join(c.get('fuel', []))} (디젤은 감점) / 무사고 또는 단순수리 / 전국")
    A("")
    rj = meta.get("rejects", {})
    if rj:
        A("제외 내역: " + ", ".join(f"{k} {v:,}대" for k, v in
                                 sorted(rj.items(), key=lambda x: -x[1])))
        A("")
    A("## 점수 산식")
    A("")
    A("가격 이점 30 + 주행거리 이점 20 + 사고이력(무사고 20/단순수리 10) + 편의옵션 "
      "(후방카메라·열선시트·스마트키·내비 각 2.5) + 연료(하이브리드 +5, 가솔린·LPG 0, 디젤 −5). "
      "가격 이점은 그룹 중앙값 대비 20% 저렴하면 만점, 주행거리는 30% 덜 탔으면 만점으로 정규화.")
    A("")
    A("**소유자 변경 1회 이하 10점**과 **등록 7일 이내 +3점**은 상세 페이지에서만 알 수 있어 "
      "전 매물 0점 처리했다. 모든 매물에 동일한 상수 오프셋이라 **순위에는 영향이 없다**"
      f"(실질 만점 {meta.get('max_attainable_score', 85):.0f}점).")
    A("")

    A(f"## 종합 TOP {TOP_N}")
    A("")
    overall = top(rows, TOP_N)
    L += md_top_table(overall)
    A("")
    for i, r in enumerate(overall, 1):
        A(f"**{i}. {r['maker']} {r['model']} {r['trim']}** — {r['year_month']} · "
          f"{r['km']:,}km · {r['price']:,}만원 · {r['accident']} · {r['location']} · "
          f"점수 {r['score']:.1f} · [매물 페이지]({r['url']})")
        A("")
        A(f"- {why_good(r)}")
        A(f"- {what_to_check(r)}")
        A("")

    for title, pred in (("세단", lambda r: r["body_type"] == "세단"),
                        ("SUV", lambda r: r["body_type"] == "SUV"),
                        ("하이브리드", lambda r: r["fuel"] == "하이브리드")):
        seg = top(rows, SEG_N, pred)
        A(f"## {title} TOP {SEG_N}")
        A("")
        if not seg:
            A(f"조건을 통과한 {title} 매물이 없다.")
            A("")
            continue
        L += md_top_table(seg)
        A("")
        for i, r in enumerate(seg, 1):
            A(f"**{i}. {r['maker']} {r['model']} {r['trim']}** — 점수 {r['score']:.1f} · "
              f"[매물 페이지]({r['url']})")
            A("")
            A(f"- {why_good(r)}")
            A(f"- {what_to_check(r)}")
            A("")

    A("## 비교군별 시세 (같은 세대·연료·배기량·트림 + 연식 ±1년, 3대 이상)")
    A("")
    A("| 그룹 | 대수 | 가격 중앙값 | 가격 범위 | 주행 중앙값 | 비고 |")
    A("|---|---:|---:|---|---:|---|")
    for g in group_table(rows):
        A(f"| {g['group']} | {g['n']} | {g['median_price']:,.0f}만 | "
          f"{g['min_price']:,}~{g['max_price']:,}만 | {g['median_km']:,}km | {g['note'] or '-'} |")
    A("")
    A("## 전체 조건 통과 매물")
    A("")
    A(f"{len(rows):,}대 전체 표는 [사이트](https://inh1095.github.io/kcar-deals/)에서 "
      "정렬·검색할 수 있다. 원본 데이터는 `data/listings.csv`.")
    A("")
    return "\n".join(L)


# ── HTML ─────────────────────────────────────────────────────────────────────
CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;margin:0;color:#1a1a1a;
background:#fafafa;line-height:1.6}
main{max-width:1180px;margin:0 auto;padding:20px 16px 64px}
h1{font-size:1.6rem;margin:.2em 0}
h2{font-size:1.15rem;margin:2em 0 .6em;padding-bottom:.3em;border-bottom:2px solid #e2e2e2}
.meta{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:12px 14px;margin:12px 0}
.meta b{color:#0b5}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.9rem;margin:0;padding:0;list-style:none}
.note{font-size:.82rem;color:#666;background:#fff;border-left:3px solid #bbb;
padding:10px 12px;border-radius:0 6px 6px 0;margin:10px 0}
.stat{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.stat div{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:10px 14px;flex:1 1 140px}
.stat span{display:block;font-size:.75rem;color:#777}
.stat strong{font-size:1.25rem}
.wrap{overflow-x:auto;background:#fff;border:1px solid #e2e2e2;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:.86rem;min-width:760px}
th,td{padding:7px 9px;text-align:left;border-bottom:1px solid #eee;white-space:nowrap}
th{background:#f2f4f6;position:sticky;top:0;cursor:pointer;user-select:none;font-weight:600}
th:hover{background:#e8ebee}
th.num,td.num{text-align:right}
tbody tr:hover{background:#f6fbff}
a{color:#0a58ca}
.sc{font-weight:700}
.badge{display:inline-block;font-size:.72rem;padding:1px 6px;border-radius:10px;background:#eef}
.b-none{background:#e6f7ec;color:#0a6b32}
.b-minor{background:#fff4e0;color:#8a5200}
.card{background:#fff;border:1px solid #e2e2e2;border-radius:8px;padding:12px 14px;margin:10px 0}
.card h3{margin:0 0 .3em;font-size:1rem}
.card p{margin:.35em 0;font-size:.86rem}
.card .why{color:#0a6b32}
.card .chk{color:#8a3b00}
.ctl{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.ctl input,.ctl select{padding:7px 9px;border:1px solid #ccc;border-radius:6px;font-size:.86rem}
.ctl input{flex:1 1 220px}
footer{margin-top:40px;font-size:.8rem;color:#666;border-top:1px solid #ddd;padding-top:14px}
@media(max-width:640px){h1{font-size:1.3rem}main{padding:14px 10px 48px}
table{font-size:.8rem}.stat strong{font-size:1.1rem}}
"""

JS = """
function sortable(t){
  t.querySelectorAll('th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var tb=t.tBodies[0], rows=Array.prototype.slice.call(tb.rows);
      var dir=th.dataset.dir==='asc'?-1:1;
      t.querySelectorAll('th').forEach(function(o){delete o.dataset.dir});
      th.dataset.dir=dir===1?'asc':'desc';
      rows.sort(function(a,b){
        var x=a.cells[i], y=b.cells[i];
        var nx=x.dataset.v, ny=y.dataset.v;
        if(nx!==undefined&&ny!==undefined){return (parseFloat(nx)-parseFloat(ny))*dir}
        return x.textContent.localeCompare(y.textContent,'ko')*dir;
      });
      rows.forEach(function(r){tb.appendChild(r)});
    });
  });
}
document.querySelectorAll('table').forEach(sortable);
var q=document.getElementById('q'), fb=document.getElementById('fb'), ff=document.getElementById('ff');
function filter(){
  var s=(q.value||'').trim().toLowerCase(), b=fb.value, f=ff.value;
  var n=0;
  document.querySelectorAll('#all tbody tr').forEach(function(tr){
    var okS=!s||tr.textContent.toLowerCase().indexOf(s)>=0;
    var okB=!b||tr.dataset.body===b;
    var okF=!f||tr.dataset.fuel===f;
    var show=okS&&okB&&okF;
    tr.style.display=show?'':'none';
    if(show)n++;
  });
  document.getElementById('cnt').textContent=n;
}
[q,fb,ff].forEach(function(e){e.addEventListener('input',filter)});
"""


def h(v) -> str:
    return html.escape(str(v if v not in (None, "") else "-"))


def html_rows(rows: list[dict]) -> str:
    out = []
    for i, r in enumerate(sorted(rows, key=lambda x: -x["score"]), 1):
        acc = ('<span class="badge b-none">무사고</span>' if r["accident"] == "무사고"
               else '<span class="badge b-minor">단순수리</span>')
        pg = f"{r['price_gap']:+.1%}" if r["price_gap"] is not None else "비교불가"
        out.append(
            f'<tr data-body="{h(r["body_type"])}" data-fuel="{h(r["fuel"])}">'
            f'<td class="num" data-v="{i}">{i}</td>'
            f'<td>{h(r["maker"])} {h(r["model"])}</td>'
            f'<td>{h(r["trim"])}</td>'
            f'<td data-v="{h(r["year_month"]).replace("-", "")}">{h(r["year_month"])}</td>'
            f'<td class="num" data-v="{r["km"]}">{r["km"]:,}</td>'
            f'<td class="num" data-v="{r["price"]}">{r["price"]:,}</td>'
            f'<td class="num" data-v="{r["total_cost_est"]}">{r["total_cost_est"]:,}</td>'
            f'<td data-v="{r["price_gap"] if r["price_gap"] is not None else -9}">{pg}</td>'
            f'<td>{h(r["fuel"])}</td><td>{h(r["body_type"])}</td>'
            f'<td data-v="{1 if r["accident"] == "무사고" else 0}">{acc}</td>'
            f'<td>{h(r["location"])}</td>'
            f'<td class="num sc" data-v="{r["score"]}">{r["score"]:.1f}</td>'
            f'<td><a href="{h(r["url"])}" target="_blank" rel="noopener nofollow">K카</a></td>'
            f'</tr>')
    return "\n".join(out)


def html_top_table(items: list[dict], tid: str) -> str:
    head = ("<tr><th class='num'>#</th><th>차명</th><th>트림</th><th>연식</th>"
            "<th class='num'>주행(km)</th><th class='num'>차량가(만)</th>"
            "<th class='num'>총비용추정(만)</th><th>사고</th><th class='num'>점수</th>"
            "<th>링크</th></tr>")
    body = []
    for i, r in enumerate(items, 1):
        acc = ('<span class="badge b-none">무사고</span>' if r["accident"] == "무사고"
               else '<span class="badge b-minor">단순수리</span>')
        body.append(
            f'<tr><td class="num" data-v="{i}">{i}</td>'
            f'<td>{h(r["maker"])} {h(r["model"])}</td><td>{h(r["trim"])}</td>'
            f'<td data-v="{h(r["year_month"]).replace("-", "")}">{h(r["year_month"])}</td>'
            f'<td class="num" data-v="{r["km"]}">{r["km"]:,}</td>'
            f'<td class="num" data-v="{r["price"]}">{r["price"]:,}</td>'
            f'<td class="num" data-v="{r["total_cost_est"]}">{r["total_cost_est"]:,}</td>'
            f'<td data-v="{1 if r["accident"] == "무사고" else 0}">{acc}</td>'
            f'<td class="num sc" data-v="{r["score"]}">{r["score"]:.1f}</td>'
            f'<td><a href="{h(r["url"])}" target="_blank" rel="noopener nofollow">K카</a></td></tr>')
    return (f'<div class="wrap"><table id="{tid}"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def html_cards(items: list[dict]) -> str:
    out = []
    for i, r in enumerate(items, 1):
        out.append(
            f'<div class="card"><h3>{i}. {h(r["maker"])} {h(r["model"])} {h(r["trim"])} '
            f'<a href="{h(r["url"])}" target="_blank" rel="noopener nofollow">매물 페이지</a></h3>'
            f'<p>{h(r["year_month"])} · {r["km"]:,}km · {r["price"]:,}만원 · '
            f'{h(r["accident"])} · {h(r["fuel"])} · {h(r["location"])} · 점수 {r["score"]:.1f}</p>'
            f'<p class="why">{h(why_good(r))}</p>'
            f'<p class="chk">{h(what_to_check(r))}</p></div>')
    return "\n".join(out)


def build_html(rows: list[dict], meta: dict) -> str:
    overall = top(rows, TOP_N)
    c = meta.get("conditions", {})
    seg_html = []
    for title, pred in (("세단", lambda r: r["body_type"] == "세단"),
                        ("SUV", lambda r: r["body_type"] == "SUV"),
                        ("하이브리드", lambda r: r["fuel"] == "하이브리드")):
        seg = top(rows, SEG_N, pred)
        tid = "t-" + ("sedan" if title == "세단" else "suv" if title == "SUV" else "hev")
        seg_html.append(f"<h2>{title} TOP {SEG_N}</h2>" +
                        (html_top_table(seg, tid) + html_cards(seg) if seg
                         else f"<p>조건을 통과한 {title} 매물이 없다.</p>"))
    gt = "".join(
        f"<tr><td>{h(g['group'])}</td><td class='num' data-v='{g['n']}'>{g['n']}</td>"
        f"<td class='num' data-v='{g['median_price']}'>{g['median_price']:,.0f}</td>"
        f"<td>{g['min_price']:,}~{g['max_price']:,}</td>"
        f"<td class='num' data-v='{g['median_km']}'>{g['median_km']:,}</td>"
        f"<td>{h(g['note'])}</td></tr>" for g in group_table(rows))
    bodies = sorted({r["body_type"] for r in rows})
    fuels = sorted({r["fuel"] for r in rows})
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>K카 국산 중고차 꿀매물 분석</title>
<style>{CSS}</style>
</head><body><main>
<h1>K카 국산 중고차 꿀매물 리스트</h1>
<div class="meta"><ul class="kv">
<li>수집 일시 <b>{h(meta.get('collected_at'))}</b></li>
<li>출처 <b>K카(kcar.com)</b> 직영 매물</li>
<li>수집 <b>{meta.get('collected', len(rows)):,}대</b></li>
<li>조건 통과 <b>{meta.get('passed', len(rows)):,}대</b></li>
</ul></div>
<div class="note"><b>면책</b> — {DISCLAIMER} 매물은 시간이 지나면 판매 완료됩니다.
사진은 게시하지 않으며 각 매물의 K카 페이지 링크만 제공합니다.</div>
<div class="note"><b>수집 범위</b> — <code>kcar.com/robots.txt</code>가 상세 페이지를
Disallow하므로 <b>상세 페이지는 조회하지 않았습니다</b>(목록 데이터만, 요청 간 1.8초, 순차).
따라서 <b>총 구매비용(K카 표시값)·보험 이력·소유자 변경 횟수·등록일·보증은 미수집</b>이며
분석에 반영되지 않았습니다. 표의 "총비용추정"은
<code>차량가 + 취득세 7% + 매도·이전대행 3만원</code> 추정치입니다.
점수의 <b>소유자 변경(10점)·신규 등록(+3점)</b>도 판정할 수 없어 전 매물 0점이며,
모든 매물에 동일한 오프셋이라 순위에는 영향이 없습니다(실질 만점
{meta.get('max_attainable_score', 85):.0f}점).</div>
<div class="stat">
<div><span>차량가 상한</span><strong>{c.get('budget', 1300):,}만</strong></div>
<div><span>연식 하한</span><strong>{c.get('year', 2017)}년</strong></div>
<div><span>주행거리 상한</span><strong>{c.get('km', 120000):,}km</strong></div>
<div><span>조건 통과</span><strong>{meta.get('passed', len(rows)):,}대</strong></div>
</div>
<p class="note">조건: 현대·기아(제네시스 포함) / 세단·해치백·SUV·미니밴 /
경차·화물·승합·렌터카 제외 / 차량가 {c.get('budget', 1300):,}만원 이하 /
{c.get('year', 2017)}년식 이상 / {c.get('km', 120000):,}km 이하 /
{', '.join(c.get('fuel', []))} (디젤 감점) / 무사고·단순수리만 / 전국.
점수 = 가격이점 30 + 주행이점 20 + 사고이력 20/10 + 편의옵션 10 + 연료 ±5.</p>

<h2>종합 TOP {TOP_N}</h2>
{html_top_table(overall, 't-top')}
{html_cards(overall)}
{''.join(seg_html)}

<h2>비교군별 시세 (같은 세대·연료·배기량·트림 + 연식 ±1년, 3대 이상)</h2>
<div class="wrap"><table id="t-grp"><thead><tr><th>그룹</th><th class="num">대수</th>
<th class="num">가격 중앙값(만)</th><th>가격 범위(만)</th><th class="num">주행 중앙값(km)</th>
<th>비고</th></tr></thead><tbody>{gt}</tbody></table></div>

<h2>조건 통과 전체 <span id="cnt">{len(rows)}</span>대</h2>
<div class="ctl">
<input id="q" type="search" placeholder="차명·트림·지점 검색">
<select id="fb"><option value="">차종 전체</option>
{''.join(f'<option value="{h(b)}">{h(b)}</option>' for b in bodies)}</select>
<select id="ff"><option value="">연료 전체</option>
{''.join(f'<option value="{h(f)}">{h(f)}</option>' for f in fuels)}</select>
</div>
<p class="note">표 머리글을 누르면 정렬됩니다. "시세차"는 그룹 중앙값 대비 저렴한 비율(+가 저렴).</p>
<div class="wrap"><table id="all"><thead><tr><th class="num">#</th><th>차명</th><th>트림</th>
<th>연식</th><th class="num">주행(km)</th><th class="num">차량가(만)</th>
<th class="num">총비용추정(만)</th><th>시세차</th><th>연료</th><th>차종</th><th>사고</th>
<th>지점</th><th class="num">점수</th><th>링크</th></tr></thead>
<tbody>
{html_rows(rows)}
</tbody></table></div>

<footer>출처 K카(kcar.com). 수집 {h(meta.get('collected_at'))}. {DISCLAIMER}<br>
상세 리포트: <a href="report.md">report.md</a> ·
생성 스크립트: <code>search_kcar.py</code> → <code>build_report.py</code></footer>
</main><script>{JS}</script></body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/listings.csv")
    ap.add_argument("--outdir", default="docs")
    args = ap.parse_args()

    rows, meta = load(args.csv)
    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, "report.md")
    html_path = os.path.join(args.outdir, "all.html")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(build_md(rows, meta))
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(build_html(rows, meta))
    print(f"{md_path} / {html_path} 생성. 조건 통과 {len(rows)}대, "
          f"수집 {meta.get('collected_at')}")


if __name__ == "__main__":
    main()
