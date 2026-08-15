# -*- coding: utf-8 -*-
"""현지언니 WP(hyunjiunni.com) Koko Analytics → 총괄 대시보드용 조회수 스냅샷.

Koko Analytics REST(Application Password Basic Auth)로 게시글별 조회수(pageviews)와
최근 30일 방문자 요약을 가져와 표준 insights.json으로 저장한다(스레드/릴스와 동일 포맷).
SSH 불필요 — 순수 REST.

저장: data/insights.json  (platform=wordpress)
사용: python scripts/collect_insights.py
"""
import base64
import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import WP_URL, WP_USER, WP_APP_PW

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT = os.path.join(DATA_DIR, "insights.json")


def _headers() -> dict:
    tok = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    return {"Authorization": f"Basic {tok}"}


def _get(base: str, ep: str, params: dict):
    r = requests.get(f"{base}/wp-json/koko-analytics/v1/{ep}", headers=_headers(),
                     params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def main():
    if not (WP_URL and WP_USER and WP_APP_PW):
        print("WP 설정 누락(WP_URL/WP_USER/WP_APP_PW)", flush=True)
        sys.exit(1)
    base = WP_URL.rstrip("/")
    end = datetime.now(KST).date()
    start = end - timedelta(days=30)
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}

    posts_raw = _get(base, "posts", params)
    stats_raw = _get(base, "stats", params)
    visitors_30d = sum(d.get("visitors", 0) for d in stats_raw) if isinstance(stats_raw, list) else 0
    pageviews_30d = sum(d.get("pageviews", 0) for d in stats_raw) if isinstance(stats_raw, list) else 0

    posts = []
    for it in (posts_raw if isinstance(posts_raw, list) else []):
        title = it.get("post_title") or it.get("label", "") or it.get("path", "")
        posts.append({
            "id": str(it.get("post_id", "")),
            "ts": "",  # Koko는 게시글별 발행일 미제공 — 조회수 정렬로 대체
            "type": "post",
            "code": "",
            "title": title,
            "url": it.get("post_permalink", "") or (base + it.get("path", "")),
            "views": it.get("pageviews"),
            "visitors": it.get("visitors"),
            "likes": None, "replies": None,
        })
    posts.sort(key=lambda x: x.get("views") or 0, reverse=True)

    out = {
        "updated": datetime.now(KST).isoformat(timespec="minutes"),
        "account": "hyunjiunni.com", "platform": "wordpress",
        "visitors_30d": visitors_30d, "pageviews_30d": pageviews_30d,
        "posts": posts,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"💾 저장: {OUT} (게시글 {len(posts)}건 · 30일 방문자 {visitors_30d}·조회 {pageviews_30d})", flush=True)
    for r in posts[:5]:
        print(f"  {r['views']}v / {r['visitors']}명  {(r['title'] or '')[:34]}", flush=True)


if __name__ == "__main__":
    main()
