# -*- coding: utf-8 -*-
"""B그룹(수치·조건 오류 63건) 처리 계획 생성 — docs/AUDIT_2026-07-31.md 파싱.

분류(2026-07-31 §2-③):
- 제목 오류(삭제 후 FORCE_KEYWORD 재발행): ①지적 '문제' 서술에 '제목' 언급
  또는 ②오류 인용문의 수치 토큰이 제목에도 등장 — 두 신호 중 하나라도 있으면 후보.
- 본문만 오류(본문 수정): 나머지.

출력: docs/bgroup_plan.json
  [{logno, title, category, date, findings, title_error, signals,
    keyword, track}]  — keyword/track 은 발행 이력에서 역추적(재발행 경로용).
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DATA = os.path.join(ROOT, "data")

# 이력에서 logno→(keyword, track) 역추적
TRACK_OF = {"info_금융재테크": ("info", "금융재테크"), "info_세금절세": ("info", "세금절세"),
            "info_보험": ("info", "보험"), "info_부동산주거": ("info", "부동산주거"),
            "gov": ("gov", None)}


def _logno(url):
    m = re.search(r"/(\d{9,})", url or "")
    return m.group(1) if m else ""


def load_keyword_map():
    out = {}
    for path in glob.glob(os.path.join(DATA, "*_history.json")):
        base = os.path.basename(path).replace("_history.json", "")
        if base.startswith("info_"):
            track = ("info", base.replace("info_", ""))
        elif base == "gov":
            track = ("gov", None)
        else:
            continue
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = rows if isinstance(rows, list) else rows.get("posts", [])
        for h in rows:
            no = _logno(h.get("post_url", "")) if isinstance(h, dict) else ""
            if no and h.get("keyword"):
                out[no] = {"keyword": h["keyword"], "track": track[0], "cat": track[1]}
    return out


def main():
    md = open(os.path.join(DOCS, "AUDIT_2026-07-31.md"), encoding="utf-8").read()
    b_sec = md.split("## B.", 1)[1]
    b_sec = re.split(r"\n## [A-Z]\.", b_sec)[0]
    kw_map = load_keyword_map()

    entries = []
    blocks = re.split(r"\n### ", b_sec)[1:]
    for blk in blocks:
        head = blk.splitlines()[0].strip()
        m = re.match(r"\[([^\]]+)\]\s*(.+)", head)
        cat, title = (m.group(1), m.group(2)) if m else ("", head)
        mu = re.search(r"<(https://blog\.naver\.com/[^>]+)>", blk)
        md_ = re.search(r"^(\d{4}-\d{2}-\d{2})", blk.splitlines()[1] if len(blk.splitlines()) > 1 else "")
        logno = _logno(mu.group(1) if mu else "")
        findings = len(re.findall(r"- \*\*(critical|high|medium|low)", blk))

        signals = []
        if re.search(r"문제[^\n]*제목|제목[^\n]*(오류|모순|반대|박혀|단정)", blk):
            signals.append("지적문에 제목 언급")
        # 오류 인용 수치가 제목에도 존재하는지
        title_nums = set(re.findall(r"\d[\d,.]*", title.replace(",", "")))
        for quote in re.findall(r"본문: `([^`]+)`", blk):
            qn = set(re.findall(r"\d[\d,.]*", quote.replace(",", "")))
            hit = qn & title_nums - {"2026", "2025", "2024"}
            if hit:
                signals.append(f"오류 인용 수치가 제목에 존재: {sorted(hit)[:3]}")
                break
        info = kw_map.get(logno, {})
        entries.append({
            "logno": logno, "title": title, "category": cat,
            "date": md_.group(1) if md_ else "", "findings": findings,
            "title_error": bool(signals), "signals": signals,
            "keyword": info.get("keyword"), "track": info.get("track"),
            "track_cat": info.get("cat"),
        })

    out = os.path.join(DOCS, "bgroup_plan.json")
    json.dump(entries, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    te = [e for e in entries if e["title_error"]]
    print(f"B그룹 {len(entries)}건 파싱 → {os.path.normpath(out)}")
    print(f"제목 오류(삭제+재발행) 후보 {len(te)}건 · 본문만 수정 {len(entries) - len(te)}건")
    no_kw = [e for e in te if not e["keyword"]]
    if no_kw:
        print(f"⚠ 재발행 키워드 미확인 {len(no_kw)}건: {[e['logno'] for e in no_kw]}")
    for e in te:
        print(f"  [{e['logno']}] {e['title'][:38]} — {e['signals'][0][:36]}"
              f" | kw={e['keyword']!r} track={e['track']}/{e['track_cat']}")


if __name__ == "__main__":
    main()
