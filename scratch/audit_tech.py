# -*- coding: utf-8 -*-
"""형수의테크공장(hyungsutech) 발행글 전수 자동 점검 (읽기 전용).

- 대상: data/tech_history.json(posted) + data/tech_guide_history.json(posted)
- 원문: https://m.blog.naver.com/hyungsutech/{logno} 비로그인 공개 조회
- 산출: data/audit_tech_result.json, docs/AUDIT_TECH_2026-07-31.md
- 재실행 가능: HTML을 scratch/tech_html/ 에 캐시 (--refresh 로 강제 재수집)

절대 로그인/발행/수정하지 않는다. requests GET만 사용.
"""
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
DATA = os.path.join(BASE, "data")
DOCS = os.path.join(BASE, "docs")
CACHE = os.path.join(BASE, "scratch", "tech_html")
os.makedirs(CACHE, exist_ok=True)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
}
SLEEP = 0.3
TODAY = "2026-07-31"

AFFILIATE_DOMAINS = [
    "smartstore.naver.com", "shopping.naver.com", "search.shopping.naver.com",
    "msearch.shopping.naver.com", "cr.shopping.naver.com", "brand.naver.com",
    "shoppinglive.naver.com", "link.coupang.com", "coupa.ng",
    "linkprice", "lpin.kr", "naver.me",
]

MD_MARKERS = ["**", "##", "[사진", "[구분선]", "TITLE:", "TAGS:"]
TABLE_PIPE_RE = re.compile(r"\|\s*-{2,}\s*\|")

STALE_WORDS = ["올해", "최신", "출시 예정", "출시예정", "곧 출시"]

STOP_TOKENS = {"the", "and", "for", "pro", "max", "vs.", "new"}  # 너무 흔한 토큰 방지(pro/max는 단독으론 제외)


def load_targets():
    targets = []
    with open(os.path.join(DATA, "tech_history.json"), encoding="utf-8") as f:
        tech = json.load(f)
    for e in tech:
        if e.get("status") == "posted" and e.get("post_url"):
            targets.append({
                "source": "tech_history",
                "logno": e["post_url"].rstrip("/").split("/")[-1],
                "title": e.get("title", ""),
                "date": e.get("date", ""),
                "category": e.get("category", ""),
                "fmt": e.get("fmt", ""),
                "topic_key": e.get("topic_key", ""),
                "post_url": e["post_url"],
            })
    with open(os.path.join(DATA, "tech_guide_history.json"), encoding="utf-8") as f:
        guide = json.load(f)
    for e in guide:
        if e.get("status") == "posted" and e.get("post_url"):
            targets.append({
                "source": "tech_guide_history",
                "logno": e["post_url"].rstrip("/").split("/")[-1],
                "title": e.get("title", ""),
                "date": e.get("date", ""),
                "category": e.get("category", ""),
                "fmt": "guide",
                "topic_key": "",
                "post_url": e["post_url"],
            })
    return targets


def fetch(logno, refresh=False):
    path = os.path.join(CACHE, f"{logno}.html")
    if not refresh and os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as f:
            return f.read()
    url = f"https://m.blog.naver.com/hyungsutech/{logno}"
    r = requests.get(url, headers=UA, timeout=20)
    time.sleep(SLEEP)
    html = r.text
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return html


def body_paragraphs(text):
    """get_text('\n') 결과를 빈줄/제로폭 라인 기준 문단으로 묶는다."""
    paras, cur = [], []
    for line in text.split("\n"):
        s = line.replace("​", "").strip()
        if not s:
            if cur:
                paras.append(" ".join(cur))
                cur = []
        else:
            cur.append(s)
    if cur:
        paras.append(" ".join(cur))
    return paras


def title_tokens(title):
    """제목에서 모델명(영숫자 3자+) / 숫자+단위 토큰 추출."""
    toks = set()
    for m in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", title):
        t = m.lower().strip("-")
        if len(t) >= 3 and t not in STOP_TOKENS:
            toks.add(t)
    for m in re.findall(r"\d[\d,\.]*\s*(?:만원|만 원|원|달러|인치|시간|GB|TB|Hz|W|mAh|%|년|세대|nm)", title):
        toks.add(re.sub(r"[\s,]", "", m).lower())
    return toks


def norm_for_match(s):
    return re.sub(r"[\s,\-]", "", s).lower()


PRICE_RE = re.compile(
    r"([가-힣A-Za-z]{2,}?)\s*(?:은|는|이|가|:|=)?\s*(?:약|무려)?\s*"
    r"(\d[\d,\.]*)\s*(만\s?원|달러)"
)


def check_contradiction(paras):
    """같은 문단에서 동일 라벨어+단위의 숫자가 상충하면 플래그(과탐지 허용)."""
    flags = []
    for i, p in enumerate(paras):
        seen = defaultdict(set)
        for label, num, unit in PRICE_RE.findall(p):
            label = label.strip()
            if len(label) < 2:
                continue
            val = num.replace(",", "")
            seen[(label, unit.replace(" ", ""))].add(val)
        for (label, unit), vals in seen.items():
            if len(vals) >= 2:
                flags.append(
                    f"문단{i + 1} '{label}' {unit} 수치 상충: {sorted(vals)}"
                )
    return flags


def check_stale(paras):
    flags = []
    for p in paras:
        for sent in re.split(r"(?<=[.!?다요])\s+", p):
            if ("2024년" in sent or "2025년" in sent) and any(w in sent for w in STALE_WORDS):
                flags.append(sent.strip()[:120])
    return flags


def audit_one(t, refresh=False):
    res = {
        "logno": t["logno"],
        "title": t["title"],
        "date": t["date"],
        "category": t["category"],
        "fmt": t["fmt"],
        "source": t["source"],
        "post_url": t["post_url"],
        "defects": [],
        "has_affiliate": False,
        "affiliate_domains": [],
        "dead": False,
        "body_len": 0,
        "img_count": 0,
    }
    if not t["logno"].isdigit():
        res["dead"] = True
        res["defects"].append({
            "type": "invalid_url",
            "detail": f"post_url이 실제 발행 URL이 아님({t['logno']}) — 발행 실패(임시저장)분이 posted로 기록됨",
        })
        return res

    try:
        html = fetch(t["logno"], refresh=refresh)
    except Exception as e:
        res["defects"].append({"type": "fetch_error", "detail": str(e)[:200]})
        return res

    soup = BeautifulSoup(html, "html.parser")
    mc = soup.select_one("div.se-main-container")

    if mc is None:
        if "존재하지 않" in html or "삭제되었거나" in html:
            res["dead"] = True
            res["defects"].append({"type": "dead", "detail": "삭제된 글(존재하지 않는 게시글) — 이력에 링크 잔존"})
        else:
            res["defects"].append({"type": "parse_fail", "detail": "se-main-container 미검출(비SE ONE 스킨 또는 차단)"})
        return res

    text = mc.get_text("\n", strip=True)
    plain = text.replace("​", "")
    body_len = len(re.sub(r"\s", "", plain))
    res["body_len"] = body_len
    paras = body_paragraphs(text)

    # 1. 라이브 결함 — 마크다운 마커 노출
    found = [m for m in MD_MARKERS if m in plain]
    if TABLE_PIPE_RE.search(plain):
        found.append("|---|")
    if found:
        res["defects"].append({"type": "markdown_exposed", "detail": f"마커 노출: {found}"})

    # 본문 길이
    if body_len < 500:
        res["defects"].append({"type": "too_short", "detail": f"본문 {body_len}자(공백 제외) < 500자"})

    # 이미지 (se-main-container 내부만)
    imgs = mc.find_all("img")
    res["img_count"] = len(imgs)
    if len(imgs) == 0:
        res["defects"].append({"type": "no_images", "detail": "본문 내 img 태그 0개"})

    # 2. 제목-본문 정합
    toks = title_tokens(t["title"])
    if toks:
        body_norm = norm_for_match(plain)
        hit = [tok for tok in toks if norm_for_match(tok) in body_norm]
        if not hit:
            res["defects"].append({
                "type": "title_body_mismatch",
                "detail": f"제목 토큰 {sorted(toks)} 이 본문에 전무",
            })

    # 3. 구식 서술 (2024/2025년 + 현재형 표현)
    stale = check_stale(paras)
    if stale:
        res["defects"].append({"type": "stale_year", "detail": " / ".join(stale[:3])})

    # 5. 내부 모순 (가격 휴리스틱, 과탐지 허용)
    contra = check_contradiction(paras)
    if contra:
        res["defects"].append({"type": "price_conflict", "detail": " / ".join(contra[:3])})

    # 6. 어필리에이트 링크
    domains = set()
    for a in mc.find_all("a", href=True):
        href = a["href"]
        for d in AFFILIATE_DOMAINS:
            if d in href:
                domains.add(d)
    if domains:
        res["has_affiliate"] = True
        res["affiliate_domains"] = sorted(domains)

    return res


def approx_key(title):
    """topic_key 없는 글 근사 그룹핑: 제목의 첫 모델명 토큰(숫자 포함 영숫자) 우선."""
    for m in re.findall(r"[A-Za-z]*\d[A-Za-z0-9\-]*|[A-Za-z]{3,}", title):
        t = m.lower().strip("-")
        if t not in STOP_TOKENS and len(t) >= 3:
            return f"~{t}"
    ko = re.findall(r"[가-힣]{2,}", title)
    return "~" + (ko[0] if ko else "misc")


def build_clusters(targets):
    groups = defaultdict(list)
    for t in targets:
        key = t["topic_key"] if t["topic_key"] else approx_key(t["title"])
        groups[key].append(t)
    clusters = {k: v for k, v in groups.items() if len(v) >= 3}
    return clusters


def severity_group(r):
    if r["dead"]:
        return "A"
    types = {d["type"] for d in r["defects"]}
    major = {"markdown_exposed", "too_short", "no_images", "title_body_mismatch", "parse_fail", "fetch_error"}
    if types & major:
        return "B"
    # 구식 서술 중 '이미 지난 날짜를 미래형(예상/예정)으로 쓰는' 경우는 독자 오인 유발 → B
    for d in r["defects"]:
        if d["type"] == "stale_year" and ("예상" in d["detail"] or "예정" in d["detail"]):
            return "B"
    if types:
        return "C"
    return "OK"


DEFECT_LABEL = {
    "dead": "삭제된 글(링크 잔존)",
    "invalid_url": "무효 URL(임시저장분 posted 기록)",
    "markdown_exposed": "마크다운 마커 노출",
    "too_short": "본문 500자 미만",
    "no_images": "본문 이미지 0개",
    "title_body_mismatch": "제목-본문 불일치",
    "stale_year": "구식 연도 서술",
    "price_conflict": "가격·수치 내부 상충(휴리스틱)",
    "parse_fail": "본문 파싱 실패",
    "fetch_error": "조회 실패",
}


CAR_KEYWORDS = [
    "현대", "기아", "테슬라", "전기차", "캐스퍼", "넥쏘", "자동차", "모빌리티",
    "아이오닉", "제네시스", "BMW", "벤츠", "SUV", "배터리", "볼보", "알파로메오", "EV", "km",
]


def metadata_notes():
    """이력 메타데이터 참고 사항(발행 본문과 무관, 내부 데이터 품질)."""
    notes = []
    with open(os.path.join(DATA, "tech_history.json"), encoding="utf-8") as f:
        th = json.load(f)
    for e in th:
        if e.get("status") == "posted" and e.get("category") == "자동차·모빌리티":
            title = e.get("title", "")
            if not any(k in title for k in CAR_KEYWORDS):
                notes.append(
                    f"- {e.get('date')} · `{title}` — seed category '자동차·모빌리티'로 기록됐으나 제목은 비자동차 주제 "
                    f"(<{e.get('post_url')}>)"
                )
    return notes


def write_report(results, clusters, path):
    total = len(results)
    defective = [r for r in results if r["defects"]]
    type_cnt = Counter(d["type"] for r in results for d in r["defects"])
    aff_cnt = sum(1 for r in results if r["has_affiliate"])
    ga = [r for r in results if severity_group(r) == "A"]
    gb = [r for r in results if severity_group(r) == "B"]
    gc = [r for r in results if severity_group(r) == "C"]

    L = []
    L.append(f"# 형수의테크공장 발행글 전수 점검 결과 ({TODAY})")
    L.append("")
    L.append("> **자동 점검 범위 주의**: 본 점검은 스크립트(`scratch/audit_tech.py`) 기반 자동 점검이다.")
    L.append("> 라이브 결함(마크다운 노출·본문 길이·이미지)·제목-본문 정합·구식 연도 서술·가격 상충 휴리스틱·")
    L.append("> 중복 클러스터·어필리에이트 링크 유무만 기계적으로 확인했으며, 현지언니 점검(docs/AUDIT_2026-07-31.md)과 달리")
    L.append("> **내용의 사실관계(제도·스펙·가격의 실제 정확성)는 검증하지 않았다.** 가격 상충은 과탐지를 허용한 목록이다.")
    L.append("")
    L.append("## ① 요약 통계")
    L.append("")
    L.append(f"- 점검 대상: **{total}건** (tech_history {sum(1 for r in results if r['source']=='tech_history')}건 + tech_guide_history {sum(1 for r in results if r['source']=='tech_guide_history')}건)")
    L.append(f"- 결함이 1개 이상 발견된 글: **{len(defective)}건 / {total}건**")
    L.append(f"- 어필리에이트 링크 보유: **{aff_cnt}건 / {total}건 ({aff_cnt*100//max(total,1)}%)**")
    L.append("")
    L.append("| 유형 | 건수 |")
    L.append("|---|---:|")
    for typ, cnt in type_cnt.most_common():
        L.append(f"| {DEFECT_LABEL.get(typ, typ)} | {cnt} |")
    L.append("")
    L.append("| 그룹 | 건수 |")
    L.append("|---|---:|")
    L.append(f"| A. 삭제 권고(삭제글 링크 잔존·심각) | {len(ga)} |")
    L.append(f"| B. 수정 필요 | {len(gb)} |")
    L.append(f"| C. 경미 | {len(gc)} |")
    L.append(f"| 정상 | {total - len(ga) - len(gb) - len(gc)} |")
    L.append("")

    def post_line(r):
        cat = f"[{r['category']}] " if r["category"] else ""
        return f"### {cat}{r['title']}\n{r['date']} · fmt={r['fmt']} · <{r['post_url']}>"

    L.append("---")
    L.append("")
    L.append(f"## ② A그룹: 삭제 권고 ({len(ga)}건)")
    L.append("")
    if not ga:
        L.append("해당 없음.")
    for r in ga:
        L.append(post_line(r))
        for d in r["defects"]:
            L.append(f"- **{DEFECT_LABEL.get(d['type'], d['type'])}**: {d['detail']}")
        L.append("- 조치: 이력 JSON에서 dead 마킹 또는 항목 정리(내부 링크로 참조 중이면 링크 제거)")
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"## ③ B그룹: 수정 필요 ({len(gb)}건)")
    L.append("")
    if not gb:
        L.append("해당 없음.")
    fix_hint = {
        "markdown_exposed": "노출된 마커를 제거하고 서식(굵게/구분선/표)으로 재변환",
        "too_short": "본문 보강(스펙 표·사용 팁 등 500자 이상으로)",
        "no_images": "본문 관련 이미지 1장 이상 삽입",
        "title_body_mismatch": "제목의 모델명·수치를 본문에 반영하거나 제목을 본문에 맞게 조정",
        "parse_fail": "수동 확인 필요(스킨/차단 여부)",
        "fetch_error": "재조회 필요",
        "stale_year": "발행 시점(2026년) 기준으로 연도·시제 정정",
        "price_conflict": "상충 수치 중 공식 출처 값으로 통일",
    }
    for r in gb:
        L.append(post_line(r))
        for d in r["defects"]:
            L.append(f"- **{DEFECT_LABEL.get(d['type'], d['type'])}**: {d['detail']}")
            L.append(f"  - 정정 방향: {fix_hint.get(d['type'], '수동 확인')}")
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"## ④ C그룹: 경미 ({len(gc)}건)")
    L.append("")
    if not gc:
        L.append("해당 없음.")
    for r in gc:
        L.append(post_line(r))
        for d in r["defects"]:
            L.append(f"- {DEFECT_LABEL.get(d['type'], d['type'])}: {d['detail']}")
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"## ⑤ 중복(카니벌라이제이션) 클러스터 — 같은 topic_key 3건 이상 ({len(clusters)}개)")
    L.append("")
    if not clusters:
        L.append("해당 없음.")
    for key, items in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        label = key[1:] + " (근사 그룹핑)" if key.startswith("~") else key
        L.append(f"### `{label}` — {len(items)}건")
        for t in sorted(items, key=lambda x: x["date"]):
            L.append(f"- {t['date']} · [{t['fmt'] or '-'}] {t['title']} · <{t['post_url']}>")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## ⑥ 어필리에이트 링크 보유율")
    L.append("")
    L.append(f"- 보유 {aff_cnt}건 / 전체 {total}건 = **{aff_cnt*100//max(total,1)}%**")
    dom_cnt = Counter(d for r in results for d in r["affiliate_domains"])
    if dom_cnt:
        L.append("- 도메인 분포:")
        for d, c in dom_cnt.most_common():
            L.append(f"  - {d}: {c}건")
    aff_posts = [r for r in results if r["has_affiliate"]]
    if aff_posts:
        L.append("- 보유 글:")
        for r in aff_posts:
            L.append(f"  - {r['date']} · {r['title']} ({', '.join(r['affiliate_domains'])})")
    else:
        L.append("- 보유 글 없음 — 쇼핑커넥트 딥링크 파이프라인 미가동 상태로 추정")
    L.append("")

    notes = metadata_notes()
    if notes:
        L.append("---")
        L.append("")
        L.append("## 부록: 이력 메타데이터 참고 (발행 본문과 무관)")
        L.append("")
        L.extend(notes)
        L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    refresh = "--refresh" in sys.argv
    targets = load_targets()
    print(f"targets: {len(targets)}")
    results = []
    for i, t in enumerate(targets, 1):
        r = audit_one(t, refresh=refresh)
        results.append(r)
        mark = ",".join(d["type"] for d in r["defects"]) or "ok"
        print(f"[{i}/{len(targets)}] {t['logno']} {mark}")

    out_json = os.path.join(DATA, "audit_tech_result.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    clusters = build_clusters(targets)
    out_md = os.path.join(DOCS, f"AUDIT_TECH_{TODAY}.md")
    write_report(results, clusters, out_md)

    total = len(results)
    defective = sum(1 for r in results if r["defects"])
    aff = sum(1 for r in results if r["has_affiliate"])
    print(f"\ndone: total={total} defective={defective} affiliate={aff} clusters={len(clusters)}")
    print(f"json: {out_json}")
    print(f"md:   {out_md}")


if __name__ == "__main__":
    main()
