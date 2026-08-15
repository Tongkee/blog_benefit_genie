# -*- coding: utf-8 -*-
"""일일 커버리지 갭 리뷰 — 오늘 발행 글 vs 금융 뉴스 헤드라인 대조 (2026-07-13 신설).

배경: 코스피 -8.95% 폭락 날(2026-07-13) 크론은 무명 상한가 종목 글을 냈고, 사용자가 저녁에
뉴스 캡처를 들고 와서야 갭(시장 브리핑·SK하이닉스·레버리지 ETF 각도 누락)이 드러났다.
이 대조를 매일 저녁 자동화한다: 네이버 금융 주요·많이본 뉴스 헤드라인을 수집해 오늘 발행
글 제목들과 비교하고, 놓친 각도가 있으면 마크다운 리포트를 출력 파일로 남긴다(워크플로가
GitHub 이슈로 등록 — wp_propose 패턴). 갭이 없으면 출력 파일을 만들지 않는다.

사용: python -m scripts.market_review [출력파일.md]
필요 env: GOOGLE_API_KEY. 의존성: requests, beautifulsoup4, google-genai (경량 — 무거운
yfinance/playwright 미사용, 크론에서 빠르게 돈다).
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
KST = timezone(timedelta(hours=9))
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _collect_headlines() -> list[str]:
    """네이버 금융 주요뉴스(제목+리드문) + 많이 본 뉴스(제목) — 마크업 변경 대비 best-effort.

    리드문 보강(2026-07-13): 제목만으로는 이슈의 실체 판단이 얕아, 주요뉴스는
    기사 첫 문단 요약(.articleSummary)까지 함께 넘겨 LLM 판단 근거를 높인다."""
    items: list[str] = []
    seen: set[str] = set()

    # ① 주요뉴스 — 제목 + 리드문
    try:
        r = requests.get("https://finance.naver.com/news/mainnews.naver", headers=_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for li in soup.select(".mainNewsList li"):
            subj = li.select_one(".articleSubject a")
            if not subj:
                continue
            t = (subj.get("title") or subj.get_text(" ", strip=True) or "").strip()
            if len(t) < 10 or t in seen:
                continue
            seen.add(t)
            summ = li.select_one(".articleSummary")
            lead = summ.get_text(" ", strip=True)[:130] if summ else ""
            items.append(f"{t} — {lead}" if lead else t)
            found += 1
        # 구조 변경 폴백: li 파스 실패 시 제목만이라도
        if not found:
            for a in soup.select("dd.articleSubject a, dt.articleSubject a"):
                t = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
                if len(t) >= 10 and t not in seen:
                    seen.add(t)
                    items.append(t)
                    found += 1
        print(f"[수집] mainnews → {found}건(리드문 포함)")
    except Exception as e:
        print(f"[수집 실패(무시)] mainnews: {e}")

    # ② 많이 본 뉴스 — 제목만
    try:
        r = requests.get(
            "https://finance.naver.com/news/news_list.naver?mode=RANK", headers=_HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for sel in ("ul.simpleNewsList li a", ".hotNewsList a", ".simpleNewsList a"):
            for a in soup.select(sel):
                t = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
                if len(t) >= 10 and t not in seen:
                    seen.add(t)
                    items.append(t)
                    found += 1
            if found:
                break
        print(f"[수집] RANK → {found}건")
    except Exception as e:
        print(f"[수집 실패(무시)] RANK: {e}")

    return items[:45]


def _market_snapshot_line() -> str:
    """코스피·코스닥 등락 한 줄 (실패 시 빈 문자열)."""
    parts = []
    for code, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        try:
            r = requests.get(
                f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}",
                headers=_HEADERS, timeout=10,
            )
            d = ((r.json() or {}).get("datas") or [{}])[0]
            parts.append(f"{label} {d.get('closePrice')} ({d.get('fluctuationsRatio')}%)")
        except Exception:
            pass
    return " · ".join(parts)


def _todays_posts() -> list[str]:
    """오늘 발행된 글 제목 목록 — 주식·정보성·정부지원 이력 파일 전수."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    titles: list[str] = []
    patterns = ["stock_*_history.json", "info_*_history.json", "gov_history.json"]
    for pat in patterns:
        for path in glob.glob(os.path.join(DATA_DIR, pat)):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                rows = data if isinstance(data, list) else data.get("posts", [])
                for h in rows:
                    if h.get("date") == today and h.get("status") == "posted" and h.get("title"):
                        titles.append(str(h["title"]))
            except Exception as e:
                print(f"[이력 읽기 실패(무시)] {path}: {e}")
    return titles


def _review(headlines: list[str], posts: list[str], snapshot: str, api_key: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    prompt = (
        "너는 재테크 블로그의 편집장이다. 오늘 저녁 기준으로 '독자들이 실제로 검색할 이슈'를 "
        "우리 블로그가 커버했는지 검토하라.\n\n"
        f"[오늘 시장] {snapshot or '수집 실패'}\n\n"
        "[오늘 금융 뉴스 헤드라인 — 화제성 순 참고]\n"
        + "\n".join(f"- {t}" for t in headlines)
        + "\n\n[오늘 우리 블로그가 발행한 글 제목]\n"
        + ("\n".join(f"- {t}" for t in posts) if posts else "- (오늘 발행 글 없음)")
        + "\n\n[지시]\n"
        "1. 헤드라인을 3~5개 핵심 이슈로 묶어라(예: 특정 종목 급등락, 시장 급변, 정책 발표).\n"
        "2. 각 이슈에 대해 우리 발행 글이 그 검색 수요를 커버하는지 판정하라.\n"
        "3. '검색량이 클 것으로 보이는데 우리가 안 다룬 각도'가 있으면 놓친 각도로 최대 3개 뽑아라. "
        "각각 근거 헤드라인, 제안 주제(가제), 타깃 키워드, 담당 파이프라인(종목분석/ETF/공모주/정보성 중)을 붙여라.\n"
        "4. 사소한 것까지 갭으로 만들지 마라 — 방문자 유입에 의미 있게 기여할 각도만. "
        "놓친 게 없으면 다른 말 없이 첫 줄에 '갭 없음'만 출력하라.\n"
        "5. 갭이 있으면 마크다운으로: '## 오늘 핵심 이슈' / '## 커버 현황' / '## 놓친 각도와 제안' 구조.\n"
    )
    # 503(UNAVAILABLE)·429는 일시적 과부하 — 지수 백오프 재시도(2026-07-29: 7/28 크론이
    # 'model is currently experiencing high demand' 단발 503으로 실패했음)
    import time as _t
    last = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            return (getattr(resp, "text", "") or "").strip()
        except Exception as ex:
            last = ex
            if not any(k in str(ex) for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")):
                raise
            if attempt < 2:
                _t.sleep(20 * (attempt + 1))
    raise last


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "review.md"
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)

    headlines = _collect_headlines()
    if len(headlines) < 5:
        print(f"헤드라인 {len(headlines)}건뿐 — 리뷰 스킵(수집 실패 추정)")
        return
    posts = _todays_posts()
    snapshot = _market_snapshot_line()
    print(f"헤드라인 {len(headlines)}건, 오늘 발행 {len(posts)}건, 시장: {snapshot}")

    report = _review(headlines, posts, snapshot, api_key)
    if not report:
        print("리뷰 생성 실패 — 종료(이슈 미생성)")
        return
    if report.replace(" ", "").startswith("갭없음"):
        print("커버리지 갭 없음 — 이슈 미생성")
        return

    header = (
        f"> 자동 생성: 오늘({datetime.now(KST).strftime('%Y-%m-%d')}) 발행 글 vs 금융 뉴스 커버리지 대조\n"
        f"> 시장: {snapshot}\n"
        f"> 발행 글 {len(posts)}건: " + (" / ".join(posts[:6]) or "없음") + "\n\n"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + report + "\n")
    print(f"갭 리포트 저장: {out_path}")


if __name__ == "__main__":
    main()
