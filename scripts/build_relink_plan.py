# -*- coding: utf-8 -*-
"""깨진 내부링크 교체 계획 생성 — docs/broken_links.json → docs/relink_plan.json.

각 대상 글의 블로그 카테고리를 발행 이력에서 찾아, **같은 카테고리의 살아있는
최신 글 3개**를 교체 링크로 고른다(2026-07-31 §2-②).

안전장치:
- 죽은 글 제목(broken_links.json 값)과 같은 제목의 후보는 제외
- 후보 URL은 모바일 페이지 실조회로 생존 확인(삭제 글을 다시 꽂는 사고 방지 —
  이력 파일에는 삭제된 글도 status=posted 로 남아 있어 이력만 믿으면 안 된다)
- 대상 글 자신은 후보에서 제외

사용: py -3 scripts/build_relink_plan.py
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
BLOG = "benefit_genie"

import requests  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/126.0 Mobile"}
_alive_cache: dict = {}


def _logno(url: str) -> str:
    m = re.search(r"/(\d{9,})", url or "")
    return m.group(1) if m else ""


def is_alive(logno: str) -> bool:
    if logno in _alive_cache:
        return _alive_cache[logno]
    ok = False
    try:
        r = requests.get(f"https://m.blog.naver.com/{BLOG}/{logno}", headers=UA, timeout=12)
        ok = r.status_code == 200 and "존재하지 않" not in r.text[:20000]
    except Exception:
        ok = False
    _alive_cache[logno] = ok
    return ok


def main():
    broken = json.load(open(os.path.join(DOCS, "broken_links.json"), encoding="utf-8"))
    dead_titles = {t for ts in broken.values() for t in ts}

    # ★B그룹 '제목 오류' 글은 곧 삭제+재발행된다(§2-③) — 대체 링크로 꽂으면
    # 그 삭제 때 링크가 다시 깨진다. 후보 풀에서 선제 제외(2026-07-31 밤 실사고:
    # 기초연금 글에 에너지바우처 224361584557을 꽂았는데 삭제 후보였다).
    doomed = set()
    bg_path = os.path.join(DOCS, "bgroup_plan.json")
    if os.path.exists(bg_path):
        for e in json.load(open(bg_path, encoding="utf-8")):
            if e.get("title_error"):
                doomed.add(e["logno"])
    print(f"삭제 예정(제목 오류) 후보 제외: {len(doomed)}건")

    logno_map = {}   # logno -> entry(+category)
    for path in glob.glob(os.path.join(DATA, "*_history.json")):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = data if isinstance(data, list) else data.get("posts", [])
        if not isinstance(rows, list):
            continue
        for h in rows:
            if not isinstance(h, dict) or h.get("status") != "posted":
                continue
            no = _logno(h.get("post_url", ""))
            if no:
                logno_map.setdefault(no, {
                    "title": h.get("title", ""),
                    "category": h.get("blog_category") or h.get("category") or "",
                    "url": f"https://blog.naver.com/{BLOG}/{no}",
                    "ts": h.get("timestamp", ""),
                })
    print(f"이력 매핑 {len(logno_map)}건 · 대상 {len(broken)}건 · 죽은 제목 {len(dead_titles)}종")

    # 카테고리별 후보(최신순) — 죽은 제목 제외
    by_cat: dict = {}
    for no, e in logno_map.items():
        if e["title"] in dead_titles or no in doomed:
            continue
        by_cat.setdefault(e["category"], []).append((e["ts"], no, e))
    for cat in by_cat:
        by_cat[cat].sort(reverse=True)

    plan, skipped = [], []
    for t_idx, target in enumerate(broken):
        te = logno_map.get(target)
        cat = te["category"] if te else ""
        pool = [x for x in by_cat.get(cat, [])] or \
               [x for rows in by_cat.values() for x in rows]
        # 대상별 오프셋 로테이션 — 전부 같은 3개 링크를 받으면 내부링크가 한 곳에
        # 쏠린다. 풀을 돌려가며 골라 링크를 분산한다(회유·SEO 분산).
        if pool:
            off = (t_idx * 3) % len(pool)
            pool = pool[off:] + pool[:off]
        picks = []
        for _, no, e in pool:
            if no == target or any(no == p["logno"] for p in picks):
                continue
            if not is_alive(no):
                continue
            picks.append({"logno": no, "url": e["url"], "title": e["title"]})
            if len(picks) == 3:
                break
        if len(picks) < 2:
            skipped.append(target)
            continue
        plan.append({"logno": target, "category": cat,
                     "urls": [p["url"] for p in picks],
                     "titles": [p["title"] for p in picks]})

    out = os.path.join(DOCS, "relink_plan.json")
    json.dump(plan, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"계획 {len(plan)}건 → {os.path.normpath(out)}")
    if skipped:
        print(f"⚠ 후보 부족 스킵 {len(skipped)}건: {skipped[:5]}")
    for it in plan[:3]:
        print(f"  예시 {it['logno']} [{it['category']}] → {[t[:22] for t in it['titles']]}")


if __name__ == "__main__":
    main()
