"""
정부지원&혜택 카테고리 자동 포스팅 스크립트
GitHub Actions: python -m scripts.gov_post
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
BLOG_CATEGORY = "정부지원·혜택"  # 2026-07-29 카테고리 개편(쉼표→가운뎃점)
HISTORY_PATH = os.path.join(DATA_DIR, "gov_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "gov_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("gov_post")


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
    """같은 블로그 카테고리 '최신' 글 최대 3개를 본문 끝에 관련글 링크카드로 추가.
    2026-07-24 개선: 기존 history[:2](오래된 것 고정)→관련성·최신순·자기제외(회유↑)."""
    from generator.related_links import append_related
    return append_related(body, history, blog_category=BLOG_CATEGORY, limit=3)



def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"정부지원 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)
    if not NAVER_ID:
        logger.error("NAVER_ID 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    history = _load_history()

    if _already_posted_this_run(history, run_slot) and not force and not draft and not dry_run:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 정부지원 포스팅 완료 — 건너뜀")
        return

    # ── 1. 키워드 선정 ──
    from generator.keyword import (pick_keyword_for_blog_category,
                                   recent_keywords_all_tracks)
    # ★블로그 전 트랙 이력 합산(2026-07-31) — '자녀장려금'이 정부지원→세금·절세로
    # 넘어가 3회 발행된 것처럼, 카테고리별 파일만 보면 교차 중복을 못 잡는다.
    recent_kws = _get_recent_posted_keywords(history) | recent_keywords_all_tracks()

    # 키워드 강제(2026-07-14): 오류 글 삭제 후 같은 키워드 재발행용 — 중복회피 우회
    forced_kw = os.environ.get("FORCE_KEYWORD", "").strip()
    if forced_kw:
        logger.info(f"키워드 강제 지정: {forced_kw!r} (중복회피 우회)")
        keyword = forced_kw
        gov_category = "정부지원&혜택"
    else:
        # ★exclude로 풀 단계에서 자기 이력 제외 (DataLab 트렌딩 반복 반환 → 중복 발행 차단)
        from generator.keyword import KeywordPoolExhausted
        try:
            kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
        except KeywordPoolExhausted as e:
            # 풀 소진이면 중복을 내느니 슬롯을 거른다(2026-07-31 fail-closed)
            logger.warning(f"{e} - 발행 스킵")
            print(f"::warning::{BLOG_CATEGORY} 키워드 풀 소진 - 발행 스킵. 키워드 보충 필요")
            return
        keyword = kw_result["keyword"]
        gov_category = kw_result["category_name"]

        for _ in range(3):
            if keyword not in recent_kws:
                break
            logger.info(f"최근 발행 키워드 중복 ({keyword!r}) — 재선정")
            kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
            keyword = kw_result["keyword"]
            gov_category = kw_result["category_name"]

    logger.info(f"선정 키워드: {keyword!r} | 정부지원 카테고리: {gov_category}")

    # ── 2. 글 생성 ──
    from generator.content import generate_gov_post
    post = generate_gov_post(keyword=keyword, api_key=GOOGLE_API_KEY, gov_category=gov_category)

    if not post:
        logger.error("정부지원글 생성 실패 — 종료")
        sys.exit(1)

    # ★종료 제도 게이트(2026-07-31) — info_post와 동일. 폐지된 제도를 현행처럼 안내하면 중단.
    try:
        from generator.official_facts import terminated_mentions
        _blob = " ".join([post.get("title", ""), post.get("body", ""),
                          post.get("summary_text", "")] + list(post.get("subheadings", [])))
        _dead = terminated_mentions(_blob)
        if _dead:
            logger.error(f"종료된 제도를 현행처럼 서술 — 발행 중단: {_dead}")
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        logger.warning(f"종료 제도 게이트 스킵: {e}")

    # 안전장치: 헤더([사진1]) 외 본문 사진 마커([사진2]+)가 남아 있으면 제거 (리터럴 노출 방지)
    if post.get("body"):
        cleaned = re.sub(r"^[ \t]*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        if cleaned != post["body"]:
            logger.info("본문 사진 마커 [사진2]+ 제거 (헤더카드만 사용)")
            post["body"] = cleaned

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 이미지 수집 ──
    images: list[dict] = []
    image_keywords = post.get("image_keywords", [])
    image_labels = post.get("image_labels", [])

    # 브랜드 헤더 카드 (images[0] = [사진1]) — HTML/CSS 인포그래픽 우선, 실패 시 PIL 폴백
    # (info_post.py의 4개 정보성 카테고리와 동일한 카드 시스템 — 정부지원도 정보성 글이라 통일)
    from generator.content import extract_summary_bullets
    bullets = extract_summary_bullets(post.get("summary_text", "")) or None
    header_path = None
    try:
        from poster.infographic_html import create_infographic_via_html
        header_path = create_infographic_via_html(
            title=post["title"], keyword=keyword, category="gov", bullets=bullets
        )
        if header_path:
            logger.info(f"HTML 인포그래픽 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"HTML 인포그래픽 실패 — PIL 폴백: {e}")

    if not header_path:
        try:
            from poster.naver_blog import create_info_infographic
            header_path = create_info_infographic(
                title=post["title"], keyword=keyword, category="gov", bullets=bullets
            )
            if header_path:
                logger.info(f"PIL 인포그래픽 생성 완료: {header_path}")
        except Exception as e:
            logger.warning(f"PIL 헤더 카드 생성 실패 (무시): {e}")

    if header_path:
        images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
        logger.info(f"정부지원 헤더 카드 완료 (불릿 {len(bullets) if bullets else 0}개)")

    # ── 본문 이미지: 에디토리얼 일러스트[사진2] + 개념 카드[사진3] (두번째스물하나 벤치마킹) ──
    # 정부지원은 스톡사진 대신 주제맞춤 AI 일러스트 + 생성 인포그래픽 → 이미지 정책과 정합.
    if header_path:
        try:
            from poster.illustration import generate_editorial_illustration
            from poster.infographic_html import create_concept_infographic
            from generator.body_layout import arrange_body_image_markers
            illust_path = generate_editorial_illustration(keyword, category="정부지원혜택", api_key=GOOGLE_API_KEY)
            concept_lines = [l for l in post.get("summary_text", "").splitlines() if l.strip()]
            concept_path = create_concept_infographic(concept_lines, category="정부지원혜택")
            post["body"], placed_i, placed_c, sub_i, sub_c = arrange_body_image_markers(
                post["body"], bool(illust_path), bool(concept_path))
            if placed_i:
                images.append({"local_path": illust_path, "url": "",
                               "alt_text": f"{keyword} 관련 이미지", "label": "",
                               "insert_before": sub_i})
            if placed_c:
                images.append({"local_path": concept_path, "url": "",
                               "alt_text": f"{keyword} 핵심 정리", "label": f"{keyword} 핵심 정리",
                               "insert_before": sub_c})
            logger.info(f"본문 이미지: 일러스트={placed_i} 개념카드={placed_c} (헤더 [사진1] 보장)")
        except Exception as e:
            logger.warning(f"본문 이미지 생성/삽입 실패(무시) — 헤더 카드만: {e}")

    logger.info("정부지원 글: 스톡사진 생략 (헤더 + AI 일러스트 + 개념 카드)")

    # 내부 링크 연계
    post["body"], extra_subs = _append_internal_links(post["body"], history)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

    # ── 4. 포스팅 ──
    # E-E-A-T 신뢰 시그널: 요약블록 끝에 '기준시점 · 최종 업데이트' 한 줄을 발행일 기준 자동 삽입.
    # ★반드시 여기서(헤더카드 bullets·개념카드 concept_lines가 원문 summary_text를 이미 소비한 뒤)만 붙인다.
    from generator.source_refs import append_eeat_line
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
            summary_text=append_eeat_line(post.get("summary_text", "")),
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

    # A/S 4필드(2026-07-31 — docs/NEXT_SESSION.md §1.A): 뒷날 공식 발표 수치와 나란히
    # 붙일 후속(A/S) 글의 원료. 발행 성공분만 추출하고, 실패는 null 기록으로 무해.
    as_fields = {"claim": None, "claim_numbers": None, "verify_event": None, "verify_date": None}
    if is_posted:
        try:
            from generator.as_fields import extract_as_fields
            _extra = "\n".join([post.get("table_str", ""), post.get("faq_str", ""),
                                post.get("summary_text", "")])
            as_fields = extract_as_fields(GOOGLE_API_KEY, post["title"], post.get("body", ""),
                                          extra_text=_extra)
        except Exception as e:
            logger.warning(f"A/S 필드 추출 스킵(무해): {e}")

    entry = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(KST).isoformat(),
        "run_slot": run_slot,
        "keyword": keyword,
        "gov_category": gov_category,
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table": bool(post.get("table_str")),
        "has_faq": bool(post.get("faq_str")),
        **as_fields,  # claim / claim_numbers / verify_event / verify_date
    }

    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"정부지원 포스팅 완료: {post_url} | 이미지 {entry['images_inserted']}장")
    else:
        logger.error(f"정부지원 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
