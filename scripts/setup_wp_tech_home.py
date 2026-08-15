"""
형수의 테크공장(tech.hyunjiunni.com) 홈 페이지 구축 — 현지 WP(setup_wp_home) 이식.
2026-07-22 사용자 지시: 현지 WP처럼 '지금 많이 보는 글 → 최신 칼럼' 순 홈.

구성: 히어로(정체성+허브 칩) → 지금 많이 보는 글(Koko) → 최신 칼럼 → 허브별 섹션 → 소개.
front page('홈')·posts page('칼럼')를 REST로 생성/갱신하고 표시 설정까지.

사용(EC2, TECH_WP_* env 필요): python -m scripts.setup_wp_tech_home
"""
import json
import logging
import os
import sys

import requests

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

WP_URL = os.environ.get("TECH_WP_URL", "https://tech.hyunjiunni.com").rstrip("/")
WP_USER = os.environ.get("TECH_WP_APP_USER", "hyungsu_admin")
WP_PW = os.environ.get("TECH_WP_APP_PW", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("setup_wp_tech_home")

# tech WP 카테고리 8종(기기형 5 + 기능형 3, 2026-07-22 실측 id·사용자 확정)
TECH_HUBS = [
    {"id": 6,  "name": "스마트폰·모바일", "desc": "최신 스마트폰·앱·모바일 활용법"},
    {"id": 7,  "name": "PC·노트북",       "desc": "PC·노트북 선택과 문제 해결"},
    {"id": 8,  "name": "가전·디지털",     "desc": "가전·디지털 기기 리뷰와 구매 가이드"},
    {"id": 9,  "name": "자동차·모빌리티", "desc": "자동차·모빌리티 신기술 소식"},
    {"id": 10, "name": "AI·IT",           "desc": "AI·IT 트렌드와 실전 활용"},
    {"id": 2,  "name": "PC 오류해결",     "desc": "PC·윈도우 오류를 원인부터 해결"},
    {"id": 3,  "name": "AI 활용",         "desc": "챗GPT 등 AI 실전 활용·자동화"},
    {"id": 4,  "name": "오피스·툴 활용",  "desc": "엑셀·오피스·생산성 툴 실전 팁"},
]


def _auth():
    return (WP_USER, WP_PW)


def _api(path: str) -> str:
    return f"{WP_URL}/wp-json/wp/v2/{path}"


def _latest_posts_block(cat_id: int | None = None, n: int = 3) -> str:
    attrs = {
        "postsToShow": n, "displayPostContent": False, "displayPostDate": True,
        "postLayout": "grid", "columns": 3, "displayFeaturedImage": True,
        "featuredImageSizeSlug": "medium_large", "addLinkToFeaturedImage": True,
    }
    if cat_id:
        attrs["categories"] = [{"id": cat_id}]
    return f'<!-- wp:latest-posts {json.dumps(attrs, ensure_ascii=False)} /-->'


def _home_content() -> str:
    chips = "\n".join(
        f'<li><a href="{WP_URL}/?cat={h["id"]}">{h["name"]}</a></li>' for h in TECH_HUBS
    )
    parts = [
        # ── 히어로 ──
        '<!-- wp:group {"className":"hj-hero","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-hero">',
        '<!-- wp:heading {"level":1} --><h1 class="wp-block-heading">형수의 테크공장</h1><!-- /wp:heading -->',
        '<!-- wp:paragraph {"className":"hj-hero-tagline"} -->'
        '<p class="hj-hero-tagline">어려운 IT·테크 소식을 누구나 5분 안에 이해하도록 쉽고 정확하게 정리합니다</p>'
        '<!-- /wp:paragraph -->',
        f'<!-- wp:html --><ul class="hj-hero-chips">\n{chips}\n</ul><!-- /wp:html -->',
        '</div><!-- /wp:group -->',
        # ── 지금 많이 보는 글 (Koko) ──
        '<!-- wp:group {"className":"hj-popular","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-popular">',
        '<!-- wp:heading {"className":"hj-home-heading"} -->'
        '<h2 class="wp-block-heading hj-home-heading">지금 많이 보는 글</h2><!-- /wp:heading -->',
        '<!-- wp:shortcode -->[koko_analytics_most_viewed_posts number=5 days=30]<!-- /wp:shortcode -->',
        '</div><!-- /wp:group -->',
        # ── 최신 칼럼 ──
        '<!-- wp:heading {"className":"hj-home-heading"} -->'
        '<h2 class="wp-block-heading hj-home-heading">최신 글</h2><!-- /wp:heading -->',
        _latest_posts_block(n=6),
    ]
    # ── 허브별 섹션 ──
    for hub in TECH_HUBS:
        parts += [
            f'<!-- wp:heading {{"className":"hj-home-heading"}} -->'
            f'<h2 class="wp-block-heading hj-home-heading">{hub["name"]}</h2><!-- /wp:heading -->',
            f'<!-- wp:paragraph {{"className":"hj-home-desc"}} -->'
            f'<p class="hj-home-desc">{hub["desc"]} · <a href="{WP_URL}/?cat={hub["id"]}">전체 보기 →</a></p>'
            f'<!-- /wp:paragraph -->',
            _latest_posts_block(cat_id=hub["id"], n=3),
        ]
    # ── 소개 스트립 ──
    parts += [
        '<!-- wp:group {"className":"hj-about-strip","layout":{"type":"constrained"}} -->',
        '<div class="wp-block-group hj-about-strip">',
        '<!-- wp:paragraph --><p>형수의 테크공장은 스마트폰·PC·가전·자동차·AI 등 IT/테크 소식을 '
        '<strong>쉽고 정확하게</strong> 풀어주는 기술 블로그입니다.</p><!-- /wp:paragraph -->',
        '</div><!-- /wp:group -->',
    ]
    return "\n\n".join(parts)


def _upsert_page(slug: str, title: str, content: str) -> int:
    r = requests.get(_api("pages"), params={"slug": slug, "per_page": 1, "context": "edit",
                                            "status": "publish,draft"},
                     auth=_auth(), timeout=30)
    payload = {"title": title, "slug": slug, "status": "publish", "content": content}
    if r.ok and r.json():
        pid = r.json()[0]["id"]
        requests.post(_api(f"pages/{pid}"), json=payload, auth=_auth(), timeout=30).raise_for_status()
        logger.info(f"페이지 갱신: {slug} (id={pid})")
        return pid
    resp = requests.post(_api("pages"), json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()
    pid = resp.json()["id"]
    logger.info(f"페이지 생성: {slug} (id={pid})")
    return pid


def main():
    if not WP_PW:
        logger.error("TECH_WP_APP_PW 미설정 — EC2 .env에서 실행하세요.")
        sys.exit(1)
    home_id = _upsert_page("home", "홈", _home_content())
    posts_id = _upsert_page("columns", "글 목록", "")

    r = requests.post(f"{WP_URL}/wp-json/wp/v2/settings",
                      json={"show_on_front": "page", "page_on_front": home_id,
                            "page_for_posts": posts_id},
                      auth=_auth(), timeout=30)
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
