# -*- coding: utf-8 -*-
"""creator-advisor 통계 API 표면 전수 탐색 (v2 — 번들 실측 기반).

v1(추측 경로)은 41개 전부 실패했다. 원인 2가지:
  ① 파라미터 키가 serviceId 가 아니라 service (collect_naver_stats.py 와 동일해야 함)
  ② 경로를 추측함 → 프론트 번들 JS(_probe_stats_bundle.py)에서 실제 경로를 추출해 교체

번들 실측 결과(2026-07-31, index-BjIDFe8q.js):
  - integrated-analysis/{metric}: 추이형(interval+startDate+endDate)
    metric = view-count·visit-count·uv-count·average-duration(평균사용시간)·
             average-visit·retention-rate(재방문율)·like-count·reply-count·follower-count
  - integrated-analysis/{X}-distribution: 분포형(interval+date[+metric])
    X = demo(성별연령)·hour(시간대)·device(기기)·country(국가)·follower(이웃)
  - integrated-analysis/{cv|like|reply|d1}-ranks: 순위형(interval+date+limit)
  - home/*: yesterday-summary·realtime-summary(-histogram)·soaring-contents·
            popular-demo-keyword·popular-category-keyword·weekly-recommendation
  - inflow-analysis/*: referrer-query-rank·inflow-search-trend·impression-inflow-trend·
            query-compare·query-competitiveness·popular-contents·infl-inflow-rate

사용: py -3 scripts/_probe_stats_api.py [blog_id] [cookie_file]
출력: data/stats_api_surface.json
"""
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scripts.collect_naver_stats as cs  # noqa: E402

BLOG = sys.argv[1] if len(sys.argv) > 1 else "benefit_genie"
COOKIE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "naver_cookies.json")

TREND_METRICS = ["view-count", "visit-count", "uv-count", "average-duration",
                 "average-visit", "retention-rate", "like-count", "reply-count",
                 "follower-count"]
DISTRIBUTIONS = ["demo-distribution", "hour-distribution", "device-distribution",
                 "country-distribution", "follower-distribution"]
RANKS = ["cv-ranks", "like-ranks", "reply-ranks", "d1-ranks"]
HOME = ["yesterday-summary", "realtime-summary", "realtime-summary-histogram",
        "soaring-contents", "popular-demo-keyword", "popular-category-keyword",
        "weekly-recommendation"]
INFLOW = ["referrer-query-rank", "inflow-search-trend", "impression-inflow-trend",
          "query-compare", "query-competitiveness", "popular-contents",
          "infl-inflow-rate"]


def main():
    try:
        s = cs.build_session(COOKIE, BLOG)
        boot = cs.bootstrap(s, BLOG)
        print("bootstrap OK:", json.dumps(boot, ensure_ascii=False)[:120])
    except Exception as e:
        print("세션/부트스트랩 실패:", e)
        return

    today = date.today()
    yesterday = today - timedelta(days=1)
    week_monday = cs.last_complete_week(today)
    start30 = today - timedelta(days=29)
    common = {"service": "naver_blog", "channelId": BLOG}

    # (경로, 파라미터) 후보 — 같은 경로도 형태가 여러 개면 전부 시도
    probes = []
    for m in TREND_METRICS:
        probes.append((f"/integrated-analysis/{m}",
                       {**common, "interval": "day",
                        "startDate": start30.isoformat(), "endDate": today.isoformat()}))
    for d in DISTRIBUTIONS:
        for interval, dt in (("week", week_monday), ("day", yesterday)):
            probes.append((f"/integrated-analysis/{d}",
                           {**common, "metric": "cv", "interval": interval,
                            "date": dt.isoformat()}))
    for r in RANKS:
        probes.append((f"/integrated-analysis/{r}",
                       {**common, "interval": "week", "date": week_monday.isoformat(),
                        "limit": 30}))
    for h in HOME:
        probes.append((f"/home/{h}", {**common, "date": today.isoformat()}))
    for i in INFLOW:
        probes.append((f"/inflow-analysis/{i}",
                       {**common, "metric": "cv", "interval": "week",
                        "date": week_monday.isoformat(), "limit": 30}))

    ok, fail = [], []
    seen_ok = set()
    for path, params in probes:
        if path in seen_ok:   # 한 형태가 이미 성공한 경로는 재시도 불필요
            continue
        try:
            data, err = cs.api(s, path, params)
        except Exception as e:
            data, err = None, e.__class__.__name__
        if data:
            body = json.dumps(data, ensure_ascii=False)
            ok.append({"path": path, "params": params, "size": len(body),
                       "sample": body[:500]})
            seen_ok.add(path)
            print(f"[OK ] {path}  ({len(body)}B)")
        else:
            fail.append({"path": path, "params": params, "err": str(err)[:80]})
            print(f"[   ] {path}  {str(err)[:60]}")

    out = os.path.join(ROOT, "data", "stats_api_surface.json")
    json.dump({"ok": ok, "fail": fail}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n응답 {len(ok)}경로 / 실패 {len(fail)}시도  → {os.path.normpath(out)}")


main()
