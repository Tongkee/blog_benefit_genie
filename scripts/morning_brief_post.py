# -*- coding: utf-8 -*-
"""아침 증시 브리핑 발행 — 무지개로그 포맷 그대로 실험 (2026-07-29 사용자 지시).

매 평일 장 전(06:20 KST) 1건. 신규 카테고리 '아침 증시 브리핑'(블로그 관리에서 생성 필요,
없으면 기본 카테고리로 발행됨). 전체 가운데정렬 + 짧은 호흡 + ✅마커 + 🔺🔻 등락 표기.

사용: python -m scripts.morning_brief_post   (DRAFT=true 로 임시저장 검증)
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (DATA_DIR, GOOGLE_API_KEY, NAVER_BLOG_ID, NAVER_COOKIES,  # noqa: E402
                    NAVER_ID, NAVER_PW)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("morning_brief_post")
KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "morning_brief_history.json")
CATEGORY = os.environ.get("MORNING_CATEGORY", "아침증시 브리핑")  # 실제 생성된 카테고리명(2026-07-29)


def run():
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        hist = json.load(open(HISTORY_PATH, encoding="utf-8"))
        if not isinstance(hist, dict):
            hist = {}
    except Exception:
        hist = {}
    if today in hist and not draft:
        logger.info(f"오늘({today}) 이미 발행 — 종료")
        return
    if not GOOGLE_API_KEY or not NAVER_ID:
        logger.error("GOOGLE_API_KEY / NAVER_ID 필요 — 종료")
        sys.exit(1)

    from generator.market_brief import collect_market_data
    from generator.morning_brief_content import build_morning_brief
    data = collect_market_data()
    if len(data) < 6:
        logger.error(f"지표 수집 부족({len(data)}개) — 발행 포기(오정보 방지)")
        sys.exit(1)
    post = build_morning_brief(data, GOOGLE_API_KEY)
    if not post:
        sys.exit(1)
    logger.info(f"브리핑 생성: {post['title']!r} ({len(post['body'])}자, 섹션 {len(post['subheadings'])})")

    # 표지(헤더 카드) — 피드 CTR용 1장(best-effort)
    images = []
    try:
        from poster.infographic_html import create_infographic_via_html
        header = create_infographic_via_html(
            title=post["title"].replace("📊", "").strip(), keyword="아침 증시 브리핑",
            category="금융재테크",
            bullets=[f"{d['emoji']} {d['name']} {d['pct_str']}" for d in data[:4]])
        if header:
            images.append({"local_path": header, "url": "", "alt_text": "아침 증시 브리핑", "label": ""})
            # ★골격 게이트(B — 2026-07-31): 첫 블록 이미지 금지(메르 24/24 첫 블록 텍스트).
            # 무지개로그 포맷(가운데정렬·✅·섹션)은 유지하되, 헤더카드만 본문 125자 뒤로.
            from generator.skeleton_gate import place_markers_by_chars
            body2, markers = place_markers_by_chars(post["body"], n=1, start_no=1)
            if markers:
                post["body"] = body2
            else:
                images.clear()   # 슬롯이 안 나오면(본문 극단적으로 짧음) 이미지 생략
    except Exception as e:
        logger.warning(f"헤더카드 실패(텍스트만 발행): {e}")

    from poster.naver_blog import post_to_naver_blog
    try:
        result = post_to_naver_blog(
            naver_id=NAVER_ID, naver_pw=NAVER_PW, blog_id=NAVER_BLOG_ID or NAVER_ID,
            title=post["title"], body=post["body"], tags=post["tags"],
            naver_cookies=NAVER_COOKIES, images=images or None, draft=draft,
            allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
            subheadings=post["subheadings"], category=CATEGORY,
            center_align=True,   # ★무지개로그 아이덴티티 — 전체 가운데정렬
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)
    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return
    post_url = (result or {}).get("post_url", "")
    if not post_url or "Redirect=Write" in post_url:
        logger.error(f"발행 실패 — URL: {post_url}")
        sys.exit(1)
    hist[today] = {"title": post["title"], "post_url": post_url,
                   "timestamp": datetime.now(KST).isoformat()}
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(hist, open(HISTORY_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    logger.info(f"아침 브리핑 발행 완료: {post_url}")


if __name__ == "__main__":
    run()
