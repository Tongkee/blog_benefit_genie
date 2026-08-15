"""네이버 라이브 글 리터럴 마크다운(**·__·##·[[]]) 누출 전수 스캔 (로컬 검증 도구).

배경: 2026-07-30 QC FAIL — info 보험글(224362055349)에 `**` 6개가 라이브 노출.
requests는 사내/집 프록시 SSL로 막혀서(self-signed chain) Playwright 쿠키 세션으로 스캔.
이력 파일에서 최근 발행 logNo를 모아 PostView.naver 본문을 뜯어 리터럴 마커를 찾는다.

사용: python scripts/_scan_live_markdown.py [--blog benefit_genie] [--days 14] [--max 40]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright  # noqa: E402
sys.path.insert(0, ROOT)
import poster.naver_blog as nb  # noqa: E402

# 라이브에 있으면 안 되는 리터럴 마커
LEAK_PATTERNS = [
    ("**", re.compile(r"\*\*")),
    ("__", re.compile(r"(?<!_)__(?!_)")),
    ("[[]]", re.compile(r"\[\[.+?\]\]")),
    ("##제목", re.compile(r"(?m)^#{1,6}\s")),
    ("[사진", re.compile(r"\[사진\d")),
    ("[표시작", re.compile(r"\[표시작")),
    ("[FAQ", re.compile(r"\[FAQ")),
]


def recent_lognos(blog_id: str, days: int, max_n: int):
    """이력 파일들에서 최근 logNo 수집 (블로그별)."""
    cut = None
    if days:
        from datetime import datetime, timedelta
        cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    # 블로그별 이력 파일 매핑(베네핏지니=info/gov/cheongyak/stock, 형수=tech)
    if blog_id == "hyungsutech":
        files = glob.glob(os.path.join(ROOT, "data", "tech_*history*.json"))
    else:
        files = [f for f in glob.glob(os.path.join(ROOT, "data", "*history*.json"))
                 if "tech" not in os.path.basename(f)]
    out = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        items = d if isinstance(d, list) else list(d.values())
        for it in items:
            if not isinstance(it, dict):
                continue
            url = str(it.get("post_url", ""))
            m = re.search(r"/(\d{9,})", url)
            if not m:
                continue
            if cut and str(it.get("date", ""))[:10] < cut:
                continue
            out.append((str(it.get("date", ""))[:10], m.group(1),
                        (it.get("title") or "")[:32],
                        os.path.basename(f).replace("_history.json", "")))
    # logNo 중복 제거, 최신순
    seen, uniq = set(), []
    for row in sorted(out, reverse=True):
        if row[1] in seen:
            continue
        seen.add(row[1])
        uniq.append(row)
    return uniq[:max_n]


def scan_body(body: str):
    hits = []
    for name, rx in LEAK_PATTERNS:
        n = len(rx.findall(body))
        if n:
            hits.append(f"{name}×{n}")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog", default="benefit_genie")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()

    targets = recent_lognos(a.blog, a.days, a.max)
    print(f"[{a.blog}] 최근 {a.days}일 · {len(targets)}글 스캔\n")
    if not targets:
        print("대상 글 없음(이력 URL 파싱 실패?)")
        return 0

    flagged = []
    with sync_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                kw = dict(headless=True, args=["--disable-blink-features=AutomationControlled"])
                if ch:
                    kw["channel"] = ch
                browser = pw.chromium.launch(**kw)
                break
            except Exception:
                continue
        ctx = browser.new_context(user_agent=nb._UA, locale="ko-KR")
        # 쿠키 로드(비공개/전체공개 무관하게 안전) — 동기 컨텍스트라 직접 주입
        try:
            ck = json.load(open(os.path.join(ROOT, "data", "naver_cookies.json"), encoding="utf-8"))
            ctx.add_cookies(ck if isinstance(ck, list) else ck.get("cookies", []))
        except Exception as e:
            print(f"(쿠키 로드 실패, 공개글만 가능: {e})")
        page = ctx.new_page()

        for date, logno, title, track in targets:
            url = f"https://blog.naver.com/PostView.naver?blogId={a.blog}&logNo={logno}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                body = page.eval_on_selector(".se-main-container", "el => el.innerText") \
                    if page.query_selector(".se-main-container") else ""
            except Exception as e:
                print(f"  ? {logno} fetch 실패: {str(e)[:50]}")
                continue
            hits = scan_body(body or "")
            mark = "🔴" if hits else "·"
            print(f"  {mark} {date} [{track:16}] {logno} {title}  {' '.join(hits)}")
            if hits:
                flagged.append({"logno": logno, "date": date, "track": track,
                                "title": title, "leaks": hits})
        browser.close()

    print(f"\n=== 누출 {len(flagged)}건 / {len(targets)}글 ===")
    out = os.path.join(ROOT, "data", "live_markdown_scan.json")
    json.dump(flagged, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
