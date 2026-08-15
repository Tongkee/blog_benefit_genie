"""
Kadence 전환 후 홈 페이지 구축 (토스피드 벤치마크, 2026-07-10).

구성: 히어로(정체성+허브 칩) → 지금 많이 보는 글(Koko) → 최신 칼럼 그리드
      → 허브별 섹션(3편+더보기) → 소개 스트립.
front page('홈')·posts page('칼럼')를 REST로 생성/갱신하고 표시 설정까지 시도.
(설정 실패 시 서버에서: wp option update show_on_front page 등 — 출력 안내 참고)

사용: python -m scripts.setup_wp_home
"""
import logging
import os
import sys

import requests

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import WP_URL
from generator.wp_topics import CATEGORY_HUBS
from poster.wp_publish import _api, _headers  # 내부 재사용(동일 인증)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("setup_wp_home")

BASE = WP_URL.rstrip("/")


def _category_ids() -> dict[str, int]:
    r = requests.get(_api("categories"), params={"per_page": 100}, headers=_headers(), timeout=30)
    r.raise_for_status()
    return {c["slug"]: c["id"] for c in r.json()}


def _latest_posts_block(cat_id: int | None = None, n: int = 3) -> str:
    attrs = {
        "postsToShow": n, "displayPostContent": False, "displayPostDate": True,
        "postLayout": "grid", "columns": 3, "displayFeaturedImage": True,
        "featuredImageSizeSlug": "medium_large", "addLinkToFeaturedImage": True,
    }
    if cat_id:
        attrs["categories"] = [{"id": cat_id}]
    import json as _json
    return f'<!-- wp:latest-posts {_json.dumps(attrs, ensure_ascii=False)} /-->'


def _home_content(cats: dict[str, int]) -> str:
    chips = "\n".join(
        f'<li><a href="{BASE}/category/{h["slug"]}/">{h["name"].split(" ")[0] if " " in h["name"] else h["name"]}</a></li>'
        for h in CATEGORY_HUBS.values()
    )
    parts = [
        # ── 히어로 ──
        '<!-- wp:group {"className":"hj-hero","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-hero">',
        '<!-- wp:heading {"level":1} --><h1 class="wp-block-heading">현지언니</h1><!-- /wp:heading -->',
        '<!-- wp:paragraph {"className":"hj-hero-tagline"} -->'
        '<p class="hj-hero-tagline">놓치기 쉬운 돈·제도 정보, 공식 자료 기준으로 계산까지 해서 정리합니다</p>'
        '<!-- /wp:paragraph -->',
        f'<!-- wp:html --><ul class="hj-hero-chips">\n{chips}\n</ul><!-- /wp:html -->',
        '</div><!-- /wp:group -->',
        # ── 지금 많이 보는 글 (Koko Analytics — 데이터 없으면 CSS로 섹션 숨김) ──
        '<!-- wp:group {"className":"hj-popular","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-popular">',
        '<!-- wp:heading {"className":"hj-home-heading"} -->'
        '<h2 class="wp-block-heading hj-home-heading">지금 많이 보는 글</h2><!-- /wp:heading -->',
        '<!-- wp:shortcode -->[koko_analytics_most_viewed_posts number=5 days=30]<!-- /wp:shortcode -->',
        '</div><!-- /wp:group -->',
        # ── 최신 칼럼 ──
        '<!-- wp:heading {"className":"hj-home-heading"} -->'
        '<h2 class="wp-block-heading hj-home-heading">최신 칼럼</h2><!-- /wp:heading -->',
        _latest_posts_block(n=6),
    ]
    # ── 허브별 섹션 ──
    for hub in CATEGORY_HUBS.values():
        cid = cats.get(hub["slug"])
        if not cid:
            continue
        parts += [
            f'<!-- wp:heading {{"className":"hj-home-heading"}} -->'
            f'<h2 class="wp-block-heading hj-home-heading">{hub["name"]}</h2><!-- /wp:heading -->',
            f'<!-- wp:paragraph {{"className":"hj-home-desc"}} -->'
            f'<p class="hj-home-desc">{hub["desc"]} · <a href="{BASE}/category/{hub["slug"]}/">전체 보기 →</a></p>'
            f'<!-- /wp:paragraph -->',
            _latest_posts_block(cat_id=cid, n=3),
        ]
    # ── 소개 스트립 ──
    parts += [
        '<!-- wp:group {"className":"hj-about-strip","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-about-strip">',
        f'<!-- wp:paragraph --><p>현지언니는 정부 제도·세금·연금·보험·주거를 <strong>공식 자료 기준</strong>으로 '
        f'분석하는 생활금융 칼럼입니다. 수치는 국세청·금융감독원·국토교통부 공시를 우선 인용합니다. '
        f'<a href="{BASE}/about/">더 알아보기</a></p><!-- /wp:paragraph -->',
        '</div><!-- /wp:group -->',
    ]
    return "\n\n".join(parts)


def _upsert_page(slug: str, title: str, content: str) -> int:
    r = requests.get(_api("pages"), params={"slug": slug, "per_page": 1, "context": "edit",
                                            "status": "publish,draft"},
                     headers=_headers(), timeout=30)
    payload = {"title": title, "slug": slug, "status": "publish", "content": content}
    if r.ok and r.json():
        pid = r.json()[0]["id"]
        requests.post(_api(f"pages/{pid}"), json=payload, headers=_headers(), timeout=30).raise_for_status()
        logger.info(f"페이지 갱신: {slug} (id={pid})")
        return pid
    resp = requests.post(_api("pages"), json=payload, headers=_headers(), timeout=30)
    resp.raise_for_status()
    pid = resp.json()["id"]
    logger.info(f"페이지 생성: {slug} (id={pid})")
    return pid


def main():
    cats = _category_ids()
    home_id = _upsert_page("home", "홈", _home_content(cats))
    posts_id = _upsert_page("columns", "칼럼", "")

    # 표시 설정 (REST /settings — 실패 시 wp-cli 안내)
    r = requests.post(f"{BASE}/wp-json/wp/v2/settings",
                      json={"show_on_front": "page", "page_on_front": home_id,
                            "page_for_posts": posts_id},
                      headers=_headers(), timeout=30)
    if r.ok:
        logger.info("표시 설정 완료: show_on_front=page")
    else:
        logger.warning(
            f"REST 설정 실패({r.status_code}) — 서버에서 실행:\n"
            f"  wp option update show_on_front page\n"
            f"  wp option update page_on_front {home_id}\n"
            f"  wp option update page_for_posts {posts_id}"
        )
    print(f"HOME_ID={home_id} POSTS_ID={posts_id}")


if __name__ == "__main__":
    main()
