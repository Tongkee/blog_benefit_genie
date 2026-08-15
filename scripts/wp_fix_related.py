# -*- coding: utf-8 -*-
"""기존 WP 글의 '함께 보면 좋은 글' 상대경로 결함 일괄 교정 (2026-07-16).

렌더러가 base_url(글 자신의 URL) 기준으로 관련글 링크를 만들어
/글슬러그/관련슬러그/ 형태로 저장돼 있던 것을 사이트 루트 기준으로 바로잡는다.
(WP canonical 301이 구제 중이었지만 저장 HTML·SEO 상 교정)

idempotent — hj-related 블록 안의 2단 경로만 마지막 세그먼트로 축약.
실행: python -m scripts.wp_fix_related [--dry-run]
"""
import logging
import re
import sys

import requests

from poster.wp_publish import _api, _base, _headers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("wp_fix_related")


def fix_related_block(content: str, site: str) -> str:
    m = re.search(r'<nav class="hj-related">.*?</nav>', content, re.S)
    if not m:
        return content
    block = m.group(0)
    # href="https://site/aaa/bbb/" → href="https://site/bbb/" (2단 경로만)
    fixed = re.sub(
        re.escape(site) + r"/([^\"/]+)/([^\"/]+)/",
        lambda mm: f"{site}/{mm.group(2)}/",
        block,
    )
    if fixed == block:
        return content
    return content.replace(block, fixed)


def run(dry_run: bool = False) -> None:
    site = _base()
    r = requests.get(_api("/posts"), params={"per_page": 100, "status": "publish",
                                             "_fields": "id,slug,content"},
                     headers=_headers(), timeout=30)
    r.raise_for_status()
    posts = r.json()
    logger.info(f"라이브 글 {len(posts)}편 점검")
    fixed = skipped = 0
    for p in posts:
        content = p["content"]["rendered"] if isinstance(p["content"], dict) else p["content"]
        # rendered가 아닌 raw가 필요 — rendered에는 wp가 덧씌운 것들이 있을 수 있어 개별 raw 조회
        pr = requests.get(_api(f"/posts/{p['id']}"), params={"context": "edit", "_fields": "content"},
                          headers=_headers(), timeout=30)
        pr.raise_for_status()
        raw = pr.json()["content"]["raw"]
        new = fix_related_block(raw, site)
        if new == raw:
            skipped += 1
            continue
        if dry_run:
            logger.info(f"[dry-run] 교정 대상: {p['slug']}")
            fixed += 1
            continue
        ur = requests.post(_api(f"/posts/{p['id']}"), json={"content": new},
                           headers=_headers(), timeout=30)
        if ur.ok:
            fixed += 1
            logger.info(f"교정 완료: {p['slug']}")
        else:
            logger.error(f"교정 실패 {ur.status_code}: {p['slug']} — {ur.text[:150]}")
    logger.info(f"완료 — 교정 {fixed} / 스킵 {skipped}")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
