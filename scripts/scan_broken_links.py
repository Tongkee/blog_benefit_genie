# -*- coding: utf-8 -*-
"""깨진 내부링크 전수 스캔 — docs/broken_links.json 재생성 (2026-07-31 밤 신설).

배경: 최초 broken_links.json은 회사 세션 수작업 산출물이라 재생성 도구가 없었다.
B그룹 삭제+재발행이 돌 때마다 다른 글의 관련글 카드가 새로 깨지므로,
[삭제 → 재발행 → 이 스캐너 → build_relink_plan → fix_related_links] 사이클로 쓴다.

방식(비로그인·읽기 전용): 이력의 모든 발행 글 모바일 페이지를 조회해
본문 속 내부링크 대상(blog.naver.com/{BLOG}/{logno})을 뽑고, 대상 생존을
실조회로 확인한다. 죽은 대상의 제목은 이력에서 역추적(삭제돼도 이력엔 남는다).

사용: py -3 scripts/scan_broken_links.py
"""
import glob
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import requests  # noqa: E402

BLOG = "hyunji_unni"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/126.0 Mobile"}
_alive: dict = {}


def _logno(url):
    m = re.search(r"/(\d{9,})", url or "")
    return m.group(1) if m else ""


def fetch(logno):
    try:
        r = requests.get(f"https://m.blog.naver.com/{BLOG}/{logno}", headers=UA, timeout=12)
        if r.status_code != 200 or "존재하지 않" in r.text[:20000]:
            return None
        return r.text
    except Exception:
        return None


def is_alive(logno):
    if logno not in _alive:
        _alive[logno] = fetch(logno) is not None
        time.sleep(0.25)
    return _alive[logno]


def main():
    title_map, all_posts = {}, []
    for path in glob.glob(os.path.join(ROOT, "data", "*_history.json")):
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = rows if isinstance(rows, list) else rows.get("posts", [])
        for h in rows:
            if not isinstance(h, dict):
                continue
            no = _logno(h.get("post_url", ""))
            if no:
                title_map.setdefault(no, h.get("title", "(제목 미상)"))
                if h.get("status") == "posted":
                    all_posts.append(no)
    all_posts = sorted(set(all_posts), reverse=True)
    print(f"스캔 대상(이력 발행글) {len(all_posts)}건")

    broken: dict = {}
    scanned = 0
    for no in all_posts:
        html = fetch(no)
        time.sleep(0.3)
        if html is None:      # 자기 자신이 삭제된 글 — 대상 아님
            continue
        scanned += 1
        targets = {t for t in re.findall(rf"blog\.naver\.com/{BLOG}/(\d{{9,}})", html)
                   if t != no}
        dead = [t for t in targets if not is_alive(t)]
        if dead:
            broken[no] = sorted({title_map.get(t, f"(미상 {t})") for t in dead})
            print(f"  ✗ {no}: 죽은 링크 {len(dead)}개 — {broken[no][0][:36]}")
        if scanned % 50 == 0:
            print(f"  … {scanned}건 스캔")

    dst = os.path.join(ROOT, "docs", "broken_links.json")
    json.dump(broken, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n생존 글 {scanned}건 중 깨진 링크 보유 {len(broken)}건 → {os.path.normpath(dst)}")


if __name__ == "__main__":
    main()
