"""PC 유입 특화 심층 가이드 발행 (2026-07-19 신설, 사용자 승인 — 하루 1건).

주제 풀(data/tech_guide_pool.json)에서 미발행 주제를 카테고리 교차로 선택 →
generate_tech_guide → hyungsutech 블로그에 발행(카테고리: PC 오류해결·설정 / AI 활용·자동화).
헤더는 테크 텍스트 카드(가이드는 뉴스 실사진이 없음 — 무관 사진보다 깔끔한 카드).
이력: data/tech_guide_history.json
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from config import GOOGLE_API_KEY  # noqa: E402

KST = timezone(timedelta(hours=9))
POOL_PATH = os.path.join(ROOT, "data", "tech_guide_pool.json")
HIST_PATH = os.path.join(ROOT, "data", "tech_guide_history.json")
# 같은 풀을 쓰는 WP 트랙(wp_tech_post)과 동일 주제가 같은 시기에 양 채널 발행되는 것 방지
# (07-19 윈도우11·07-20 챗GPT 2일 연속 동일일 충돌 — §7 0-m)
CROSS_HIST_PATH = os.path.join(ROOT, "data", "wp_tech_history.json")
CROSS_EXCLUDE_DAYS = 14

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("tech_guide_post")


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _pick_topic() -> dict | None:
    """미발행 우선 + 카테고리 교차(직전 발행과 다른 카테고리 우선)."""
    pool = _load(POOL_PATH, {}).get("topics", [])
    hist = _load(HIST_PATH, [])
    done = {h.get("id") for h in hist}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if any(h.get("date") == today and h.get("status") == "posted" for h in hist):
        logger.info("오늘 가이드 1건 이미 발행 — 스킵")
        return None
    cutoff = (datetime.now(KST) - timedelta(days=CROSS_EXCLUDE_DAYS)).strftime("%Y-%m-%d")
    cross = {h.get("id") for h in _load(CROSS_HIST_PATH, []) if h.get("date", "") >= cutoff}
    fresh = [t for t in pool if t.get("id") not in done and t.get("id") not in cross]
    if cross:
        logger.info(f"교차 배제: WP 트랙 최근 {CROSS_EXCLUDE_DAYS}일 주제 {len(cross)}건 제외")
    if not fresh:
        logger.warning("가이드 주제 풀 소진 — 보충 필요")
        return None
    # 2026-07-28 주제 과열 게이트(AI엑셀 유사 글 2건 연속 실사고): 최근 7일 발행 제목
    # (가이드+뉴스 트랙 합산 — 같은 블로그)과 핵심 토큰 2개 이상 겹치는 후보 제외.
    import re as _re
    _stop = {"진짜", "총정리", "가이드", "이유", "방법", "확인", "정리", "활용", "해결",
             "설정", "자동화", "시작", "구축", "관리"}
    _tok = lambda s: {w for w in _re.findall(r"[가-힣A-Za-z0-9]{2,}", s or "")
                      if w not in _stop and not w.isdigit()}
    _cut7 = (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")
    _recent = [h.get("title", "") for h in hist
               if h.get("status") == "posted" and h.get("date", "") >= _cut7]
    try:
        _th = _load(os.path.join(os.path.dirname(HIST_PATH), "tech_history.json"), [])
        _recent += [h.get("title", "") for h in _th
                    if h.get("status") == "posted" and h.get("date", "") >= _cut7]
    except Exception:
        pass
    _hot = [t for t in fresh
            if any(len(_tok(t.get("keyword", "")) & _tok(rt)) >= 2 for rt in _recent if rt)]
    if _hot:
        logger.info(f"주제 과열 제외: {', '.join(t.get('keyword', '')[:20] for t in _hot[:3])}"
                    + (f" 외 {len(_hot) - 3}건" if len(_hot) > 3 else ""))
        fresh = [t for t in fresh if t not in _hot]
    if not fresh:
        logger.info("잔여 후보 전부 최근 주제와 과열 겹침 — 오늘 가이드 스킵")
        return None
    last_cat = next((h.get("category") for h in reversed(hist) if h.get("status") == "posted"), "")
    alt = [t for t in fresh if t.get("category") != last_cat]
    return (alt or fresh)[0]


def main():
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"

    naver_id = os.environ.get("TECH_NAVER_ID", "") or os.environ.get("NAVER_ID", "")
    naver_pw = os.environ.get("TECH_NAVER_PW", "") or os.environ.get("NAVER_PW", "")
    naver_cookies = os.environ.get("TECH_NAVER_COOKIES", "") or os.environ.get("NAVER_COOKIES", "")
    blog_id = os.environ.get("TECH_NAVER_BLOG_ID", "") or "hyungsutech"
    if not dry_run and not naver_id and not naver_cookies:
        logger.error("TECH_NAVER 계정/쿠키 없음")
        sys.exit(1)

    forced = os.environ.get("FORCE_TOPIC_ID", "").strip()
    if forced:
        topic = next((t for t in _load(POOL_PATH, {}).get("topics", []) if t.get("id") == forced), None)
    else:
        topic = _pick_topic()
    if not topic:
        return
    logger.info(f"주제: [{topic['category']}] {topic['keyword']}")

    from generator.tech_guide_content import generate_tech_guide
    post = generate_tech_guide(GOOGLE_API_KEY, topic)
    if not post:
        logger.error("가이드 생성 실패 — 종료")
        sys.exit(1)
    if post.get("body"):
        post["body"] = re.sub(r"^[ \t]*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
    _unbrace = lambda s: re.sub(r"\{\{(.+?)\}\}", r"\1", s or "")
    post["title"] = _unbrace(post.get("title", ""))
    post["summary_text"] = _unbrace(post.get("summary_text", ""))
    if post.get("faq_pairs"):
        post["faq_pairs"] = [[_unbrace(q), _unbrace(a)] for q, a in post["faq_pairs"]]

    logger.info(f"제목: {post['title']}")
    # 네이버 마크다운 잔여 정리(볼드 제거 + 줄머리 불릿 → '· ') — WP normalize와 별개 경로(2026-07-22)
    import re as _re
    _b = post.get("body", "")
    _b = _re.sub(r"\*\*(.+?)\*\*", r"\1", _b)
    _b = _re.sub(r"(?m)^[ \t]*[*\-•]\s+", "· ", _b)
    post["body"] = _b
    if dry_run:
        logger.info("[DRY_RUN] 원고만 생성:\n" + post.get("body", "")[:800])
        return

    images = []
    try:
        from poster.infographic_html import create_tech_header_card
        tc = create_tech_header_card(post["title"], keyword=topic["keyword"])
        if tc:
            images.append({"local_path": tc, "url": "", "alt_text": topic["keyword"], "label": ""})
    except Exception as e:
        logger.warning(f"헤더 카드 실패(이미지 없이 진행): {e}")

    from poster.naver_blog import post_to_naver_blog
    result = post_to_naver_blog(
        naver_id=naver_id, naver_pw=naver_pw, blog_id=blog_id,
        title=post["title"], body=post["body"], tags=post.get("tags", []),
        naver_cookies=naver_cookies, images=images or None, draft=draft,
        allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
        table_str=post.get("table_str", ""), table_strs=post.get("table_strs", []),
        subheadings=post.get("subheadings", []),
        faq_questions=post.get("faq_questions", []),
        # 주제 풀 내부명(한글) → 실제 블로그 카테고리(How-To 하위 영어명, 2026-07-29 개편)
        category={"PC 오류해결·설정": "Troubleshooting", "AI 활용·자동화": "AI Lab",
                  "오피스·툴 활용": "How-To"}.get(topic["category"], topic["category"]),
        faq_pairs=post.get("faq_pairs", []),
        summary_text=post.get("summary_text", ""),
        summary_quote_style="포스트잇",
        set_representative=True,
        style_line_markers=True,
    )
    url = (result or {}).get("post_url", "") if isinstance(result, dict) else str(result or "")
    status = "posted" if result else "failed"
    hist = _load(HIST_PATH, [])
    hist.append({"id": topic["id"], "date": datetime.now(KST).strftime("%Y-%m-%d"),
                 "timestamp": datetime.now(KST).isoformat(timespec="seconds"),
                 "keyword": topic["keyword"], "category": topic["category"],
                 "title": post["title"], "post_url": url, "status": status})
    json.dump(hist, open(HIST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    logger.info(f"발행 {status}: {url}")
    if status != "posted":
        sys.exit(1)


if __name__ == "__main__":
    main()
