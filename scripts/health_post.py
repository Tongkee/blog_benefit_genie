"""
건강&다이어트 카테고리 자동 포스팅 스크립트
GitHub Actions: python -m scripts.health_post
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR, LOG_DIR,
    GOOGLE_API_KEY, PEXELS_API_KEY,
    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES,
)

KST = timezone(timedelta(hours=9))
BLOG_CATEGORY = "건강, 다이어트"
HISTORY_PATH = os.path.join(DATA_DIR, "health_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "health_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("health_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("posts", [])


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_this_run(history: list, run_slot: str) -> bool:
    """같은 실행 슬롯(09/14/19)에 오늘 이미 발행했으면 True"""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("run_slot") == run_slot and h.get("status") == "posted":
            return True
    return False


def _get_recent_posted_keywords(history: list, days: int = 30) -> set:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {h["keyword"] for h in history if h.get("date", "") >= cutoff and h.get("keyword")}


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_internal_links(body: str, history: list) -> tuple:
    """같은 카테고리 최근 글 1~2개를 본문 끝에 가운데 정렬 링크로 추가"""
    related = [h for h in history if h.get("status") == "posted" and h.get("post_url") and h.get("title")][:2]
    if not related:
        return body, []

    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"

    return body + links_text, ["함께 보면 좋은 글"]


_BULLET_LINE_RE = re.compile(r"^(?:· |•|◦|▪|‣|[①-⑳]|[❶-❿]|\d+[.)]\s)")


def _center_body_lines(body: str) -> str:
    """본문 프로즈 줄만 가운데 정렬([가운데] 추가).
    ※ 구조 마커([표삽입]/[요약삽입]/[FAQ삽입]/[구분선]/[사진N]/[가운데] 등 모든 대괄호 마커)와
      글머리(· 등)·URL·빈줄에는 붙이지 않는다.
      마커 줄에 [가운데]가 붙으면 poster의 앵커 매칭(_preceding_text_at)이 '[가운데]'만 남겨
      표/요약/FAQ가 문서 끝 등 엉뚱한 위치에 삽입되고, '[구분선]' 리터럴 노출·글머리 리스트
      변환 실패까지 유발한다."""
    lines = body.split("\n")
    result = []
    for line in lines:
        s = line.strip()
        if not s:
            result.append(line)
            continue
        if (s.startswith("[")            # 모든 대괄호 마커([표삽입]/[구분선]/[사진N]/[가운데]/…)
                or s.startswith("http://")
                or s.startswith("https://")
                or _BULLET_LINE_RE.match(s)):
            result.append(line)
            continue
        result.append("[가운데] " + s)
    return "\n".join(result)


def _extract_subheadings(body: str) -> list[str]:
    """본문에서 [소제목] 줄의 항목명 추출 (인포그래픽용)"""
    headings = []
    for line in body.split("\n"):
        s = line.strip()
        if s.startswith("[소제목]"):
            heading = s[len("[소제목]"):].strip()
            # ①②③④⑤ 등 원형 번호 제거
            heading = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", heading)
            if heading:
                headings.append(heading)
    return headings


def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"건강 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"

    history = _load_history()

    if _already_posted_this_run(history, run_slot) and not force and not draft:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 건강 포스팅 완료 — 건너뜀")
        return

    # ── 1. 키워드 선정 ──
    from generator.keyword import pick_keyword_for_blog_category
    recent_kws = _get_recent_posted_keywords(history)

    kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY)
    keyword = kw_result["keyword"]
    health_category = kw_result["category_name"]

    # 최근 30일 발행 키워드와 중복이면 재선정 (최대 3회)
    for _ in range(3):
        if keyword not in recent_kws:
            break
        logger.info(f"최근 발행 키워드 중복 ({keyword!r}) — 재선정")
        kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY)
        keyword = kw_result["keyword"]
        health_category = kw_result["category_name"]

    logger.info(f"선정 키워드: {keyword!r} | 건강 카테고리: {health_category}")

    # ── 2. 글 생성 ──
    from generator.content import generate_health_post
    post = generate_health_post(keyword=keyword, api_key=GOOGLE_API_KEY, health_category=health_category)

    if not post:
        logger.error("건강글 생성 실패 — 종료")
        sys.exit(1)

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    # ── 3. 이미지 수집 ──
    images: list[dict] = []
    image_keywords = post.get("image_keywords", [])
    image_labels = post.get("image_labels", [])

    # 이미지 조립: images[0]=헤더카드([사진1]), images[1+]=Pexels 소제목별([사진2+])

    # 브랜드 헤더 카드 (images[0] = [사진1])
    try:
        from poster.naver_blog import create_health_header_card
        header_path = create_health_header_card(title=post["title"], keyword=keyword)
        if header_path:
            images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
            logger.info(f"헬스 헤더 카드 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"헤더 카드 생성 실패 (무시): {e}")

    # Pexels 소제목별 사진 (images[1+] = [사진2+])
    # image_keywords[0]="health header", [1:]부터 Pexels
    pexels_keywords = image_keywords[1:] if len(image_keywords) > 1 else []
    pexels_labels = image_labels[1:] if len(image_labels) > 1 else []
    if PEXELS_API_KEY and pexels_keywords:
        try:
            from generator.image import get_post_images
            pexels_imgs = get_post_images(
                keyword=keyword,
                api_key=PEXELS_API_KEY,
                count=len(pexels_keywords),
                image_keywords=pexels_keywords,
            )
            for idx, img in enumerate(pexels_imgs):
                if idx < len(pexels_labels):
                    img["label"] = pexels_labels[idx]
            images.extend(pexels_imgs)
            logger.info(f"Pexels 이미지 {len(pexels_imgs)}장 수집")
        except Exception as e:
            logger.warning(f"이미지 수집 실패 (무시): {e}")

    # 내부 링크 연계
    post["body"], extra_subs = _append_internal_links(post["body"], history)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

    # 전체 가운데 정렬 후처리
    post["body"] = _center_body_lines(post["body"])

    # ── 4. 포스팅 ──
    from poster.naver_blog import post_to_naver_blog
    try:
        result = post_to_naver_blog(
            naver_id=NAVER_ID,
            naver_pw=NAVER_PW,
            blog_id=NAVER_BLOG_ID or NAVER_ID,
            title=post["title"],
            body=post["body"],
            tags=post["tags"],
            naver_cookies=NAVER_COOKIES,
            images=images if images else None,
            draft=draft,
            allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
            table_str=post.get("table_str", ""),
            table_strs=post.get("table_strs", []),
            subheadings=post.get("subheadings", []),
            faq_questions=post.get("faq_questions", []),
            category=BLOG_CATEGORY,
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)

    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return

    # ── 5. 이력 저장 ──
    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)

    entry = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(KST).isoformat(),
        "run_slot": run_slot,
        "keyword": keyword,
        "health_category": health_category,
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "is_rx": post.get("is_rx", False),
    }

    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"건강 포스팅 완료: {post_url} | 이미지 {entry['images_inserted']}장")
    else:
        logger.error(f"건강 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
