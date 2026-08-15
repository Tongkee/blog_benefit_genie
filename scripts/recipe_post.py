"""
'오늘의 집밥 레시피' 자동 포스팅 — daily_post.py 와 같은 포스터를 재사용,
카테고리='오늘의 집밥 레시피' 로 발행. 별도 시간대(KST 17:00)에 실행.
GitHub Actions: python -m scripts.recipe_post
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
HISTORY_PATH = os.path.join(DATA_DIR, "recipe_history.json")
CATEGORY = "오늘의 집밥 레시피"
MAX_QUALITY_RETRIES = 2   # 품질 미달 시 최대 재생성 횟수
QUALITY_PASS_SCORE  = 60  # 발행 최소 점수

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "recipe_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("recipe_post")


def _load_history() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _already_posted_today(history: list) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return any(h.get("date") == today and h.get("status") == "posted" for h in history)


def _recent_dishes(history: list, days: int = 14) -> list[str]:
    cutoff = datetime.now(KST) - timedelta(days=days)
    out = []
    for h in history:
        try:
            ts = datetime.fromisoformat(h.get("timestamp", ""))
            if ts > cutoff and h.get("dish"):
                out.append(h["dish"])
        except Exception:
            continue
    return out


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_internal_links(body: str, history: list, current_category: str) -> tuple:
    """과거 발행 성공한 글 중 현재 카테고리와 같은 글 1~2개를 본문 맨 끝에 자동 연계.
    반환: (수정된_body, 추가_소제목_리스트)
    """
    related = []
    for h in history:
        h_cat = h.get("category_name") or h.get("category")
        if (h.get("status") == "posted"
                and h_cat == current_category
                and h.get("post_url")
                and h.get("title")):
            related.append(h)
            if len(related) >= 2:
                break

    if not related:
        return body, []

    # 회색바 소제목 + 가운데 정렬 링크 — 항상 본문 맨 끝에 추가 (마지막 사진 이후)
    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"

    return body + links_text, ["함께 보면 좋은 글"]


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


def run():
    logger.info("=" * 60)
    logger.info(f"레시피 포스팅 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        return
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        return

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    if draft:
        logger.info("DRAFT=true — 임시저장 검증 모드 (공개 발행 안 함 / 이력 미기록)")
    history = _load_history()
    if _already_posted_today(history) and not force and not draft:
        logger.info("오늘 이미 레시피 포스팅 완료 — 건너뜀 (FORCE_POST=true 로 강제)")
        return

    # ── 1. 레시피 생성 (최근 14일 메뉴 회피 및 품질 검증 루프) ──
    from generator.recipe import generate_recipe
    from generator.quality import score_content
    recent = _recent_dishes(history, days=14)
    logger.info(f"최근 14일 메뉴 {len(recent)}개 회피: {recent}")
    
    post = None
    quality_result = None
    feedback_issues = None

    for attempt in range(1, MAX_QUALITY_RETRIES + 2):
        logger.info(f"레시피 생성 시도 {attempt}/{MAX_QUALITY_RETRIES + 1}")
        candidate = generate_recipe(
            GOOGLE_API_KEY, 
            recent=recent,
            feedback=feedback_issues,
        )
        if not candidate:
            logger.error(f"레시피 생성 실패 (시도 {attempt})")
            if attempt > MAX_QUALITY_RETRIES:
                logger.error("레시피 생성 최종 실패 — 종료")
                sys.exit(1)
            continue
            
        # 품질 채점
        qr = score_content(
            title=candidate.get("title", ""),
            body=candidate.get("body", ""),
            tags=candidate.get("tags", []),
            table_str=candidate.get("table_str", ""),
            faq_str=candidate.get("faq_str", ""),
            category=CATEGORY,
        )
        logger.info(f"품질 점수: {qr['score']}/100 ({'통과' if qr['pass'] else '재생성'})")
        
        # 점수 통과(>=60)여도 수정 가능한 중대 이슈(키워드 과다반복·본문 매우 짧음·AEO 거의 없음)가
        # 있으면 재시도 한도 내에서 재생성하여 피드백 루프로 개선한다.
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
        logger.error("레시피 생성 최종 실패 — 종료")
        sys.exit(1)

    # 본문에서 닉네임 '현지언니' 직접 언급 제거(1인칭 치환) — 프롬프트 규칙 위반 대비 안전장치
    from generator.content import scrub_persona_name
    post["body"] = scrub_persona_name(post.get("body", ""))

    dish = post.get("dish", "")
    logger.info(f"메뉴: {dish} | 제목: {post['title']}")
    logger.info("===== 본문 전문 시작 =====\n" + post.get("body", "") + "\n===== 본문 전문 끝 =====")

    # ── 2. AI 이미지 생성 (완성사진 1장 + 단계별 4장) ──
    # Pexels 대신 전부 Gemini AI 생성 — 같은 주방/도구/식재료로 일관성 유지
    images: list[dict] = []
    img_key = os.environ.get("GEMINI_API_KEY") or GOOGLE_API_KEY
    scene_desc = post.get("scene_desc", "")
    step_images = post.get("step_images", [])

    from generator.image import generate_recipe_step_image

    # step_images[0] = 완성요리, step_images[1..] = 단계별
    # [사진1] = 완성요리, [사진2~5] = 단계별
    total_slots = 5
    for i in range(total_slots):
        step_desc = step_images[i] if i < len(step_images) else ""
        if not step_desc and i == 0:
            step_desc = f"beautifully plated {dish}, Korean home cooking style"
        if not step_desc:
            step_desc = f"cooking step {i} of {dish}"

        try:
            path = generate_recipe_step_image(
                dish=dish,
                scene_desc=scene_desc,
                step_desc=step_desc,
                api_key=img_key,
                step_index=i,
            )
            label = "완성 요리" if i == 0 else f"단계 {i}"
            if path:
                images.append({"local_path": path, "url": "", "alt_text": f"{dish} {label}", "label": label})
                logger.info(f"[사진{i+1}] AI 이미지 생성 완료: {label}")
            else:
                logger.warning(f"[사진{i+1}] AI 이미지 생성 실패 — 슬롯 건너뜀")
        except Exception as e:
            logger.warning(f"[사진{i+1}] 이미지 생성 예외(무시): {e}")

    logger.info(f"AI 이미지 총 {len(images)}장 생성 완료")

    # 쿠팡 우회 쇼핑 가이드 연계
    post["body"] = _append_shopping_guide(post["body"], post.get("coupang_hints"))

    # 과거 관련 레시피 포스팅 링크 연계 (Action 3)
    post["body"], extra_subs = _append_internal_links(post["body"], history, CATEGORY)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

    # ── 3. 포스팅 (카테고리=오늘의 집밥 레시피) ──
    from poster.naver_blog import post_to_naver_blog
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
        category=CATEGORY,
    )

    if draft:
        if result:
            logger.info(f"[DRAFT] 임시저장 결과: {result.get('post_url')} | 이미지 {result.get('images_inserted')}장")
        else:
            logger.error("[DRAFT] 포스팅 함수 None 반환 — 로그/스크린샷 확인")
        logger.info("[DRAFT] 이력 미기록 — 검증 모드 종료")
        return

    # ── 4. 이력 저장 ──
    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)
    entry = {
        "date":            datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp":       datetime.now(KST).isoformat(),
        "dish":            dish,
        "title":           post["title"],
        "tags":            post["tags"],
        "category":        CATEGORY,
        "status":          "posted" if is_posted else "failed",
        "post_url":        post_url if is_posted else None,
        "quality_score":   quality_result["score"] if quality_result else None,
        "quality_pass":    quality_result["pass"] if quality_result else None,
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table":       bool(post.get("table_str")),
        "has_faq":         bool(post.get("faq_str")),
    }
    history.insert(0, entry)
    _save_history(history[:200])

    if is_posted:
        logger.info(f"레시피 포스팅 완료: {post_url}")
    else:
        logger.error(f"레시피 포스팅 실패 — 쿠키 만료/발행 오류 의심. URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
