"""형수테크 WP(tech.hyunjiunni.com) 발행글 잔여 마크다운 in-place 보정.

배경: wp_tech_post 초기 발행분 중 LLM이 강조·목록을 마크다운(**, '* ')으로 낸 글이
변환 없이 발행돼 리터럴 '**'·'*'가 노출됨(2026-07-21 규명: hipass·chatgpt).
generator/wp_html.normalize_residual_md 로 <strong>·<ul><li> 변환 후 같은 post ID에
업데이트(slug/URL 유지, 중복 글 생성 없음). WordPress는 리비전을 남기므로 되돌릴 수 있음.

실행(EC2 — TECH_WP_APP_PW 있는 환경):
    python scripts/wp_tech_repair.py            # 전 tech 글 스캔 → 깨진 것만 보정
    DRY_RUN=true python scripts/wp_tech_repair.py   # 변경 없이 진단만
    SLUGS="a-slug,b-slug" python scripts/wp_tech_repair.py  # 특정 글만
"""
from __future__ import annotations

import logging
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from generator.wp_html import has_residual_md, normalize_residual_md, rendered_to_raw  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_tech_repair")

WP_URL = os.environ.get("TECH_WP_URL", "https://tech.hyunjiunni.com").rstrip("/")
WP_USER = os.environ.get("TECH_WP_APP_USER", "hyungsu_admin")
WP_PW = os.environ.get("TECH_WP_APP_PW", "")
DRY = os.environ.get("DRY_RUN", "false").lower() == "true"
SLUGS = [s.strip() for s in os.environ.get("SLUGS", "").split(",") if s.strip()]


def _auth():
    return (WP_USER, WP_PW)


def _fetch_posts() -> list[dict]:
    """context=edit 로 content.raw(저장 원문) 포함해 전 글을 가져옴."""
    posts, page = [], 1
    while True:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts", auth=_auth(), timeout=60,
                         params={"per_page": 50, "page": page, "context": "edit",
                                 "status": "publish", "_fields": "id,slug,content,title"})
        if r.status_code != 200:
            logger.error("목록 조회 실패 p%d: %s %s", page, r.status_code, r.text[:200])
            break
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return posts


def _raw_body(post: dict) -> str:
    """저장 원문 우선(content.raw), 없으면 rendered 환원."""
    content = post.get("content", {})
    raw = content.get("raw")
    if raw:
        return raw
    return rendered_to_raw(content.get("rendered", ""))


def main() -> int:
    if not WP_PW:
        logger.error("TECH_WP_APP_PW 없음 — EC2(.env 있는 곳)에서 실행하세요.")
        return 1
    posts = _fetch_posts()
    logger.info("tech WP 글 %d개 스캔%s", len(posts), " [DRY_RUN]" if DRY else "")
    fixed_n = 0
    for p in posts:
        slug = p.get("slug", "")
        if SLUGS and slug not in SLUGS:
            continue
        rendered = p.get("content", {}).get("rendered", "")
        raw = _raw_body(p)
        broken = has_residual_md(rendered) or has_residual_md(raw)
        if not broken:
            logger.info("  clean  id=%s %s", p["id"], slug)
            continue
        fixed = normalize_residual_md(raw)
        if fixed == raw:
            logger.info("  no-change id=%s %s (마크다운 미검출)", p["id"], slug)
            continue
        before_stars = raw.count("**")
        logger.info("  BROKEN id=%s %s | **x%d → 변환 <strong>x%d <li>x%d",
                    p["id"], slug, before_stars, fixed.count("<strong>"), fixed.count("<li>"))
        if DRY:
            fixed_n += 1
            continue
        u = requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{p['id']}", auth=_auth(), timeout=60,
                          json={"content": fixed})
        if u.status_code in (200, 201):
            logger.info("    ✅ 업데이트 완료 id=%s", p["id"])
            fixed_n += 1
        else:
            logger.error("    ❌ 업데이트 실패 id=%s: %s %s", p["id"], u.status_code, u.text[:200])
    logger.info("완료: %d개 %s", fixed_n, "보정대상(DRY)" if DRY else "보정됨")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
