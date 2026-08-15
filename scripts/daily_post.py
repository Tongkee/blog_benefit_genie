"""
매일 자동 포스팅 메인 스크립트
GitHub Actions: python -m scripts.daily_post

업그레이드 내역 (v2):
- 카테고리 기반 키워드 선정
- 품질 점수 검증 + 60점 미만 재생성 (최대 2회)
- Pexels 이미지 3장 수집 및 포스터 전달
- 트렌딩 캐시 활용
- 이력에 카테고리/품질점수 저장
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta

# Windows cp949 인코딩 오류 방지
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
HISTORY_PATH = os.path.join(DATA_DIR, "post_history.json")
MAX_QUALITY_RETRIES = 2   # 품질 미달 시 최대 재생성 횟수
QUALITY_PASS_SCORE  = 60  # 발행 최소 점수

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "daily_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_today_category(history: list, blog_category: str) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("status") == "posted":
            # Check explicit blog_category first
            h_blog_cat = h.get("blog_category")
            if not h_blog_cat:
                # Fall back to mapping keyword_category to blog_category
                kw_cat = h.get("category")
                if kw_cat in ["청소정리", "절약재테크", "신혼살림기초", "요리식비"]:
                    h_blog_cat = "알뜰 살림 꿀팁"
                elif kw_cat in ["인테리어", "쇼핑정보"]:
                    h_blog_cat = "살림템 비교·추천"
                elif kw_cat in ["신혼일상"]:
                    h_blog_cat = "일상"
                else:
                    h_blog_cat = "알뜰 살림 꿀팁"
            if h_blog_cat == blog_category:
                return True
    return False


def _is_real_post_url(url: str | None) -> bool:
    """실제 게시된 포스트 URL인지 확인 (숫자 ID 포함, 에디터 URL 아님)"""
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_shopping_guide(body: str, hints: list) -> str:
    """본문 내에 쿠팡 힌트 기반의 안전한 우회 쇼핑 가이드 단락 추가"""
    if not hints:
        return body

    guide_text = "\n\n🛒 언급된 살림 추천 아이템 가격 정보:\n"
    for hint in hints:
        guide_text += f"📍 {hint} -> 검색창에 이름을 검색하시면 최저가 비교 정보를 빠르게 보실 수 있어요!\n"

    # [사진N] 중 가장 마지막 마커의 바로 직전에 삽입
    last_photo_match = list(re.finditer(r"\[사진\d+\]", body))
    if last_photo_match:
        last_match = last_photo_match[-1]
        start_idx = last_match.start()
        body = body[:start_idx] + guide_text + "\n" + body[start_idx:]
    else:
        body = body + guide_text

    return body


def _append_internal_links(body: str, history: list, blog_category: str) -> tuple:
    """과거 발행 성공한 글 중 현재 블로그 카테고리와 같은 글 1~2개를 본문 맨 끝에 자동 연계.
    반환: (수정된_body, 추가_소제목_리스트)
    """
    related = []
    for h in history:
        if h.get("status") != "posted" or not h.get("post_url") or not h.get("title"):
            continue

        h_blog_cat = h.get("blog_category")
        if not h_blog_cat:
            kw_cat = h.get("category")
            if kw_cat in ["청소정리", "절약재테크", "신혼살림기초", "요리식비"]:
                h_blog_cat = "알뜰 살림 꿀팁"
            elif kw_cat in ["인테리어", "쇼핑정보"]:
                h_blog_cat = "살림템 비교·추천"
            elif kw_cat in ["신혼일상"]:
                h_blog_cat = "일상"
            else:
                h_blog_cat = "알뜰 살림 꿀팁"

        if h_blog_cat == blog_category:
            related.append(h)
            if len(related) >= 2:
                break

    if not related:
        return body, []

    # 소제목(회색바) + 가운데 정렬 URL — 항상 본문 맨 끝에 추가 (마지막 사진 이후)
    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"

    return body + links_text, ["함께 보면 좋은 글"]


def run():
    logger.info("=" * 60)
    logger.info(f"일일 다중 카테고리 포스팅 시작 v3: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    if draft:
        logger.info("DRAFT=true — 임시저장 검증 모드 (공개 발행 안 함 / 중복체크 무시 / 이력 미기록)")

    blog_categories = ["알뜰 살림 꿀팁", "살림템 비교·추천", "일상"]
    failed_categories = []

    for blog_cat in blog_categories:
        logger.info("-" * 50)
        logger.info(f"블로그 카테고리 처리 시작: {blog_cat}")
        logger.info("-" * 50)
        
        # 반복 시점마다 최신 이력을 로드하여 다른 루프 회차에서 추가된 이력을 인지할 수 있도록 함
        history = _load_history()
        
        if _already_posted_today_category(history, blog_cat) and not force and not draft:
            logger.info(f"오늘 {blog_cat} 카테고리에 이미 포스팅 완료 — 건너뜀")
            continue
            
        if force:
            logger.info("FORCE_POST=true — 오늘 중복 체크 무시하고 강제 실행")

        # ── 1. 키워드 선정 (카테고리 기반) ──────────────────────────
        from generator.keyword import pick_keyword_for_blog_category
        try:
            kw_result = pick_keyword_for_blog_category(blog_cat)
            keyword = kw_result["keyword"]
            category = kw_result["category"]
            category_name = kw_result["category_name"]
            logger.info(f"선정 키워드: {keyword!r} | 키워드 카테고리: {category_name}")
        except Exception as e:
            logger.error(f"키워드 선정 실패 (카테고리: {blog_cat}): {e}")
            failed_categories.append(blog_cat)
            continue

        # ── 2. 트렌딩 수집 (캐시 우선) ──────────────────────────────
        try:
            from generator.trend import get_weekly_trends, suggest_trend_angle
            trends = get_weekly_trends()
            trend_angle = suggest_trend_angle(keyword, trends, category)
            logger.info(f"트렌딩 {len(trends)}개 수집 | 각도: {trend_angle[:60] if trend_angle else '없음'}")
        except Exception as e:
            logger.warning(f"트렌딩 수집 실패 (무시): {e}")
            trends = []
            trend_angle = ""

        # ── 3. 글 생성 + 품질 검증 (최대 2회 재시도) ────────────────
        from generator.content import generate_post
        from generator.quality import score_content

        post = None
        quality_result = None
        feedback_issues = None

        for attempt in range(1, MAX_QUALITY_RETRIES + 2):  # 최대 3번 시도
            logger.info(f"글 생성 시도 {attempt}/{MAX_QUALITY_RETRIES + 1}")
            candidate = generate_post(
                keyword=keyword,
                api_key=GOOGLE_API_KEY,
                trending=trends[:4] if trends else None,
                category=category_name,
                feedback=feedback_issues,
            )
            if not candidate:
                logger.error(f"글 생성 실패 (시도 {attempt})")
                if attempt > MAX_QUALITY_RETRIES:
                    break
                continue

            # 품질 채점
            qr = score_content(
                title=candidate.get("title", ""),
                body=candidate.get("body", ""),
                tags=candidate.get("tags", []),
                table_str=candidate.get("table_str", ""),
                faq_str=candidate.get("faq_str", ""),
                category=category,
            )
            logger.info(f"품질 점수: {qr['score']}/100 ({'통과' if qr['pass'] else '재생성'})")

            # 점수 통과(>=60)여도 수정 가능한 중대 이슈가 있으면 재시도 한도 내에서 재생성.
            accept = (qr["pass"] and not qr.get("needs_retry")) or attempt > MAX_QUALITY_RETRIES
            if accept:
                post = candidate
                quality_result = qr
                if not qr["pass"]:
                    logger.warning(f"품질 미달({qr['score']}점)이지만 재시도 소진 — 발행 진행")
                elif qr.get("needs_retry"):
                    logger.warning(f"중대 이슈 잔존(점수 {qr['score']}점)이나 재시도 소진 — 발행 진행")
                break
            else:
                reason = "품질 미달" if not qr["pass"] else f"점수 통과({qr['score']}점)이나 중대 이슈"
                fb = qr.get("critical") or qr["issues"]
                logger.warning(
                    f"{reason} (기준 {QUALITY_PASS_SCORE}점) — 재생성\n"
                    f"이슈: {' / '.join(fb[:3])}"
                )
                feedback_issues = fb

        if not post:
            logger.error(f"글 생성 최종 실패 (블로그 카테고리: {blog_cat}) — 다음 카테고리로 진행")
            failed_categories.append(blog_cat)
            continue

        # 본문에서 닉네임 '현지언니' 직접 언급 제거(1인칭 치환) — 프롬프트 규칙 위반 대비 안전장치
        from generator.content import scrub_persona_name
        post["body"] = scrub_persona_name(post.get("body", ""))

        logger.info(f"제목: {post['title']}")
        logger.info(f"태그: {post['tags']}")
        logger.info(f"표 포함: {'있음' if post.get('table_str') else '없음'}")
        logger.info(f"FAQ 포함: {'있음' if post.get('faq_str') else '없음'}")
        logger.info("===== 본문 전문 시작 =====\n" + post.get("body", "") + "\n===== 본문 전문 끝 =====")
        if post.get("coupang_hints"):
            logger.info(f"쿠팡 힌트: {post['coupang_hints']}")

        # ── 4. 이미지 수집 (image_keywords 활용 시 위치별 수집) ──────
        images: list[dict] = []
        image_keywords = post.get("image_keywords", [])
        image_labels = post.get("image_labels", [])
        if image_keywords:
            logger.info(f"이미지 키워드 {len(image_keywords)}개: {image_keywords}")
        if image_labels:
            logger.info(f"이미지 라벨 {len(image_labels)}개: {image_labels}")
        if PEXELS_API_KEY:
            try:
                from generator.image import get_post_images
                img_count = len(image_keywords) if image_keywords else 7
                images = get_post_images(
                    keyword=keyword,
                    api_key=PEXELS_API_KEY,
                    count=img_count,
                    category=category,
                    image_keywords=image_keywords if image_keywords else None,
                )
                # 각 이미지 객체에 한글 라벨 텍스트 매핑
                for idx, img in enumerate(images):
                    if idx < len(image_labels):
                        img["label"] = image_labels[idx]
                logger.info(f"이미지 수집 및 라벨 매핑 완료: {len(images)}장")
            except Exception as e:
                logger.warning(f"이미지 수집 실패 (무시): {e}")
        else:
            logger.info("PEXELS_API_KEY 없음 — 이미지 없이 진행")

        # 과거 관련 포스팅 링크 연계 (Action 3)
        post["body"], extra_subs = _append_internal_links(post["body"], history, blog_cat)
        post["subheadings"] = post.get("subheadings", []) + extra_subs

        # ── 5. 포스팅 ────────────────────────────────────────────────
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
                category=blog_cat,
                faq_pairs=post.get("faq_pairs", []),
                summary_text=post.get("summary_text", ""),
            )
        except Exception as e:
            logger.error(f"포스팅 중 예외 발생 (블로그 카테고리: {blog_cat}): {e}")
            failed_categories.append(blog_cat)
            continue

        # ── 드래프트 검증 모드: 이력 기록 없이 결과만 로깅하고 종료 ──
        if draft:
            if result:
                logger.info(
                    f"[DRAFT] [{blog_cat}] 임시저장 결과: {result.get('post_url')} | "
                    f"에디터 본문 {result.get('editor_text_len')}자 | "
                    f"이미지 {result.get('images_inserted')}장 삽입"
                )
            else:
                logger.error(f"[DRAFT] [{blog_cat}] 포스팅 함수 None 반환 — 로그/스크린샷 확인 필요")
                failed_categories.append(blog_cat)
            continue

        # ── 6. 이력 저장 ─────────────────────────────────────────────
        post_url  = result.get("post_url") if result else None
        is_posted = _is_real_post_url(post_url)
        now_str   = datetime.now(KST).isoformat()

        entry = {
            "date":           datetime.now(KST).strftime("%Y-%m-%d"),
            "timestamp":      now_str,
            "keyword":        keyword,
            "category":       category,
            "category_name":  category_name,
            "blog_category":  blog_cat,
            "title":          post["title"],
            "tags":           post["tags"],
            "status":         "posted" if is_posted else "failed",
            "post_url":       post_url if is_posted else None,
            "quality_score":  quality_result["score"] if quality_result else None,
            "quality_pass":   quality_result["pass"]  if quality_result else None,
            "images_count":   len(images),
            "images_inserted": result.get("images_inserted", 0) if result else 0,
            "has_table":      bool(post.get("table_str")),
            "has_faq":        bool(post.get("faq_str")),
        }
        
        history = _load_history()
        history.insert(0, entry)
        _save_history(history[:200])

        if is_posted:
            logger.info(f"[{blog_cat}] 포스팅 완료: {post_url}")
            logger.info(
                f"품질: {quality_result['score'] if quality_result else 'N/A'}점 | "
                f"이미지: {entry['images_inserted']}장 삽입"
            )
        else:
            logger.error(f"[{blog_cat}] 포스팅 실패 — URL: {post_url}")
            failed_categories.append(blog_cat)

    if failed_categories:
        logger.error(f"다음 카테고리 포스팅 실패함: {failed_categories}")
        sys.exit(1)
    else:
        logger.info("모든 카테고리 포스팅 성공 또는 이미 포스팅 완료됨.")


if __name__ == "__main__":
    run()
