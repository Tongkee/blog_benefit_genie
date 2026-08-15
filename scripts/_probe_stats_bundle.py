# -*- coding: utf-8 -*-
"""creator-advisor 프론트엔드 JS 번들에서 실제 API 경로 전수 추출.

_probe_stats_api.py 1차 실행(2026-07-31 집 PC)의 교훈: 경로를 추측으로 두드리면
404(경로 없음)만 쌓인다. SPA 번들 JS에는 모든 API 경로 문자열이 박혀 있으므로
그걸 긁는 게 전수 조사다. 읽기 전용(GET만).

사용: py -3 scripts/_probe_stats_bundle.py [blog_id] [cookie_file]
출력: data/stats_api_bundle_paths.json (경로 후보 목록)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import scripts.collect_naver_stats as cs  # noqa: E402

BLOG = sys.argv[1] if len(sys.argv) > 1 else "hyunji_unni"
COOKIE = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "naver_cookies.json")

APP = f"https://creator-advisor.naver.com/naver_blog/{BLOG}"


def main():
    s = cs.build_session(COOKIE, BLOG)
    r = s.get(APP, timeout=30)
    print(f"앱 페이지: HTTP {r.status_code} ({len(r.text)}B)")
    html = r.text

    # 번들 스크립트 URL 수집 (절대/상대 모두)
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    js_urls = []
    for u in srcs:
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = "https://creator-advisor.naver.com" + u
        js_urls.append(u)
    print(f"스크립트 태그 {len(js_urls)}개")

    paths = set()
    pat_api = re.compile(r'["\'`](/?(?:api/)?v\d+/[A-Za-z0-9_\-/{}$.]+)["\'`]')
    # 세그먼트 결합형("/integrated-analysis/"+"view-count")도 잡도록 -analysis/-rank 계열 단독 문자열 수집
    pat_seg = re.compile(r'["\'`](/[a-z][a-z0-9\-]*(?:-analysis|-summary|-rank|-ranks)'
                         r'(?:/[A-Za-z0-9_\-{}$]+)*)["\'`]')
    pat_word = re.compile(r'["\'`]([a-z][a-z0-9]*(?:-[a-z0-9]+)+)["\'`]')

    words = set()
    for u in js_urls:
        try:
            jr = s.get(u, timeout=30)
            if jr.status_code != 200:
                print(f"  [{jr.status_code}] {u[:90]}")
                continue
            body = jr.text
            got_api = pat_api.findall(body)
            got_seg = pat_seg.findall(body)
            paths.update(got_api)
            paths.update(got_seg)
            words.update(pat_word.findall(body))
            print(f"  [OK ] {u[:90]}  api {len(got_api)} · seg {len(got_seg)} ({len(body)}B)")
        except Exception as e:
            print(f"  [ERR] {u[:90]}  {type(e).__name__}: {str(e)[:60]}")

    # 하이픈 단어 중 지표명으로 보이는 것(…-count/-rate/-ranks/-time/-summary 등)만 추림
    metric_words = sorted(w for w in words if re.search(
        r"-(count|rate|ranks?|time|summary|age|analysis|trend|inflow)s?$", w))

    out = {
        "app_status": r.status_code,
        "paths": sorted(paths),
        "metric_words": metric_words,
    }
    dst = os.path.join(ROOT, "data", "stats_api_bundle_paths.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nAPI 경로 {len(paths)}개 · 지표성 단어 {len(metric_words)}개 → {os.path.normpath(dst)}")
    for p in sorted(paths):
        print("  ", p)


main()
