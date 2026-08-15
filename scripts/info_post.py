"""
고CPC 정보성 범용 포스팅 스크립트 (금융재테크·세금절세·보험·부동산주거).
카테고리는 환경변수 INFO_CATEGORY로 지정.
GitHub Actions: INFO_CATEGORY=금융재테크 python -m scripts.info_post
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
    GOOGLE_API_KEY,
    NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES,
)

KST = timezone(timedelta(hours=9))

# INFO_CATEGORY(키워드풀 id) → 네이버 블로그 카테고리명
# 2026-07-29 사용자 카테고리 개편: 쉼표 → 가운뎃점 리네임 + '금융지식' 그룹 하위로 이동
INFO_CAT_MAP = {
    "금융재테크": "금융·재테크",
    "세금절세": "세금·절세",
    "보험": "보험",
    "부동산주거": "부동산·주거",
}

def _posted_today(history: list) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return any(h.get("date") == today and h.get("status") == "posted" for h in history)


# 2026-07-29 어드바이저 분석: 세금절세가 글당 28일 31뷰로 최고 효율(자녀장려금 497뷰 지속형)
# — 로테이션에서 마지막 발행을 36시간 오래된 것처럼 취급해 선택 빈도를 높인다.
_CAT_HANDICAP_H = {"세금절세": 36}


def _pick_least_recent_category() -> str:
    """스케줄 실행(카테고리 미지정) 시: 오늘 미발행 카테고리 중 가장 오래 전 발행(또는 미발행)된 것 선택."""
    best, best_ts = None, None
    for cid in INFO_CAT_MAP:
        path = os.path.join(DATA_DIR, f"info_{cid}_history.json")
        last = ""
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                rows = data if isinstance(data, list) else data.get("posts", [])
                if _posted_today(rows):
                    continue
                posted = [h.get("timestamp", "") for h in rows if h.get("status") == "posted"]
                last = max(posted) if posted else ""
        except Exception:
            last = ""
        key = last or "0000"
        h = _CAT_HANDICAP_H.get(cid)
        if h and last:
            try:
                key = (datetime.fromisoformat(last) - timedelta(hours=h)).isoformat()
            except ValueError:
                pass
        if best is None or key < best_ts:
            best, best_ts = cid, key
    return best or "금융재테크"


INFO_CAT_ID = os.environ.get("INFO_CATEGORY", "").strip()
if not INFO_CAT_ID or INFO_CAT_ID == "auto":
    INFO_CAT_ID = _pick_least_recent_category()
    print(f"[자동 순환] 카테고리 선택: {INFO_CAT_ID}")
if INFO_CAT_ID not in INFO_CAT_MAP:
    print(f"알 수 없는 INFO_CATEGORY: {INFO_CAT_ID!r} (가능: {list(INFO_CAT_MAP)})")
    sys.exit(1)
BLOG_CATEGORY = INFO_CAT_MAP[INFO_CAT_ID]
HISTORY_PATH = os.path.join(DATA_DIR, f"info_{INFO_CAT_ID}_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "info_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("info_post")


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


def _is_real_post_url(url) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))




def _append_internal_links(body: str, history: list) -> tuple:
    """같은 블로그 카테고리 '최신' 글 최대 3개를 본문 끝에 관련글 링크카드로 추가.
    2026-07-24 개선: 기존 history[:2](오래된 것 고정)→관련성·최신순·자기제외(회유↑)."""
    from generator.related_links import append_related
    return append_related(body, history, blog_category=BLOG_CATEGORY, limit=3, blog_id=NAVER_BLOG_ID or NAVER_ID)




def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"[{BLOG_CATEGORY}] 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
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
    if _posted_today(history) and not force and not draft and not dry_run:
        logger.info(f"오늘 이미 {BLOG_CATEGORY} 포스팅 완료 — 건너뜀")
        return
    if _already_posted_this_run(history, run_slot) and not force and not draft and not dry_run:
        logger.info(f"오늘 슬롯 {run_slot}에 이미 {BLOG_CATEGORY} 포스팅 완료 — 건너뜀")
        return

    # ── 1. 키워드 선정 ──
    from generator.keyword import pick_keyword_for_blog_category, keyword_cluster
    # 키워드 강제(2026-07-13): 오류 글 삭제 후 같은 키워드 재발행용 — 30일 회피·클러스터 쿨다운 우회
    forced_kw = os.environ.get("FORCE_KEYWORD", "").strip()
    if forced_kw:
        logger.info(f"키워드 강제 지정: {forced_kw!r} (중복회피 우회)")
        keyword = forced_kw
        kw_result = {"keyword": forced_kw, "category": BLOG_CATEGORY}
    # ★블로그 전 트랙 이력을 합쳐서 본다(2026-07-31). 자기 카테고리 파일만 보면 같은
    # 키워드가 다른 카테고리로 연달아 나간다('여름 집 습기 관리' 부동산→금융 연속 발행).
    from generator.keyword import recent_keywords_all_tracks
    recent_kws = _get_recent_posted_keywords(history) | recent_keywords_all_tracks()
    # ★exclude 필수: 풀 필터 없이 재선정만 돌리면 DataLab 트렌딩이 같은 고검색량
    # 키워드를 반복 반환해 3회 소진 후 중복 발행됨(보험 국민연금 2연속 실사고).
    if not forced_kw:
        # 풀 소진이면 중복을 내느니 이 슬롯을 거른다(2026-07-31 fail-closed)
        from generator.keyword import KeywordPoolExhausted
        try:
            kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
        except KeywordPoolExhausted as e:
            logger.warning(f"{e} — 발행 스킵")
            print(f"::warning::{BLOG_CATEGORY} 키워드 풀 소진 — 발행 스킵. 키워드 보충 필요")
            return
        keyword = kw_result["keyword"]
        try:
            for _ in range(3):
                if keyword not in recent_kws:
                    break
                logger.info(f"최근 발행 키워드 중복 ({keyword!r}) — 재선정")
                kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=recent_kws)
                keyword = kw_result["keyword"]

            # 주제 클러스터 3일 쿨다운 — 키워드가 달라도 같은 계열(자동차보험 등) 연속 발행 방지
            recent3_clusters = {
                keyword_cluster(kw_result["category"], k)
                for k in _get_recent_posted_keywords(history, days=3)
            } - {None}
            exclude_more = set(recent_kws)
            for _ in range(5):
                cluster = keyword_cluster(kw_result["category"], keyword)
                if cluster is None or cluster not in recent3_clusters:
                    break
                logger.info(f"주제 클러스터 연속 회피 ({keyword!r} ∈ '{cluster}') — 재선정")
                exclude_more.add(keyword)
                kw_result = pick_keyword_for_blog_category(BLOG_CATEGORY, exclude=exclude_more)
                keyword = kw_result["keyword"]
        except KeywordPoolExhausted as e:
            logger.warning(f"{e} — 발행 스킵(재선정 중 소진)")
            print(f"::warning::{BLOG_CATEGORY} 키워드 풀 소진 — 발행 스킵. 키워드 보충 필요")
            return
    # ★카테고리 정합 가드(2026-07-31): 선정된 키워드가 이 카테고리 풀 소속인지 확인한다.
    # 매핑이 어긋나 살림 키워드('베란다 청소 꿀팁')가 세금·절세로 배정되고, 그 위에
    # 고CPC 템플릿이 씌워져 없는 제도를 지어낸 글이 나갔다. 어긋나면 발행을 거른다.
    if not forced_kw:
        from generator.keyword import CATEGORIES, blog_category_keyword_cats
        allowed = set()
        for cid in blog_category_keyword_cats(BLOG_CATEGORY):
            allowed |= set(CATEGORIES[cid]["keywords"])
        if keyword not in allowed:
            logger.error(f"키워드 {keyword!r}가 {BLOG_CATEGORY} 풀에 없습니다 — 발행 중단. "
                         f"카테고리에 안 맞는 글을 내보내느니 이 슬롯을 거릅니다.")
            sys.exit(1)
    logger.info(f"선정 키워드: {keyword!r} | 카테고리: {BLOG_CATEGORY}")

    # ── 2. 글 생성 ──
    from generator.info_content import generate_info_post
    post = generate_info_post(keyword=keyword, api_key=GOOGLE_API_KEY, info_cat_id=INFO_CAT_ID)
    if not post:
        logger.error(f"{BLOG_CATEGORY}글 생성 실패 — 종료")
        sys.exit(1)

    # ★종료 제도 게이트(2026-07-31): 이미 끝난 제도를 현행처럼 안내하면 발행을 막는다.
    # 전수 점검 최대 오류 유형이 이것이었다(청년희망적금·신혼부부 취득세 감면 등
    # 폐지 제도에 신청 방법·취급 은행까지 안내한 글이 실제로 발행됨).
    try:
        from generator.official_facts import terminated_mentions
        _blob = " ".join([post.get("title", ""), post.get("body", ""),
                          post.get("summary_text", "")] + list(post.get("subheadings", [])))
        _dead = terminated_mentions(_blob)
        if _dead:
            logger.error(f"종료된 제도를 현행처럼 서술 — 발행 중단: {_dead}. "
                         f"(종료 사실을 명시하지 않은 언급) 잘못된 안내를 내보내느니 슬롯을 거릅니다.")
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        logger.warning(f"종료 제도 게이트 스킵: {e}")

    # 안전장치: 헤더([사진1]) 외 본문 사진 마커([사진2]+) 제거
    if post.get("body"):
        cleaned = re.sub(r"^[ \t]*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        if cleaned != post["body"]:
            logger.info("본문 사진 마커 [사진2]+ 제거 (헤더카드만 사용)")
            post["body"] = cleaned

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")
    # 본문 전문을 아티팩트로 보존(2026-07-13) — 로그 500자 절단 때문에 발행 전
    # 정밀 검증(사실관계·형식)이 불가했던 문제 해소. data/screenshots/는 아티팩트로 업로드됨.
    try:
        shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        with open(os.path.join(shot_dir, "generated_body.txt"), "w", encoding="utf-8") as f:
            f.write(f"TITLE: {post['title']}\nTAGS: {post.get('tags')}\n\n{post.get('body', '')}")
    except Exception as e:
        logger.warning(f"본문 아티팩트 저장 실패(무해): {e}")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 이미지: 헤더 카드만 (본문 스톡사진 없음) ──
    images: list[dict] = []
    from generator.content import extract_summary_bullets
    bullets = extract_summary_bullets(post.get("summary_text", "")) or None
    header_path = None

    # HTML/CSS + Playwright 우선, 실패시 PIL 폴백
    try:
        from poster.infographic_html import create_infographic_via_html
        header_path = create_infographic_via_html(
            title=post["title"], keyword=keyword, category=INFO_CAT_ID, bullets=bullets
        )
        if header_path:
            logger.info(f"HTML 인포그래픽 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"HTML 인포그래픽 실패 — PIL 폴백: {e}")

    if not header_path:
        try:
            from poster.naver_blog import create_info_infographic
            header_path = create_info_infographic(
                title=post["title"], keyword=keyword, category=INFO_CAT_ID, bullets=bullets
            )
            if header_path:
                logger.info(f"PIL 인포그래픽 생성 완료: {header_path}")
        except Exception as e:
            logger.warning(f"PIL 헤더 카드 생성 실패 (무시): {e}")

    if header_path:
        images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
        logger.info(f"{BLOG_CATEGORY} 헤더 카드 완료 (불릿 {len(bullets) if bullets else 0}개)")

    # ── 본문 이미지: 에디토리얼 일러스트[사진2] + 개념 카드[사진3] (두번째스물하나 벤치마킹) ──
    # 일러스트=주제맞춤 AI 플랫벡터(gov/info가 버린 '무관한 스톡사진' 문제 해결). 개념카드=요약 시각화.
    # ★개념카드는 summary_text 원문 사용(헤더 bullets는 5~35자 필터라 긴 불릿 탈락). 실패/앵커없으면
    #   해당 이미지만 스킵하고 나머지는 유지(arrange가 placed 플래그로 images 정합 보장).
    if header_path:
        try:
            from poster.illustration import generate_editorial_illustration
            from poster.infographic_html import create_concept_infographic
            from generator.body_layout import arrange_body_image_markers
            illust_path = generate_editorial_illustration(keyword, category=INFO_CAT_ID, api_key=GOOGLE_API_KEY)
            concept_lines = [l for l in post.get("summary_text", "").splitlines() if l.strip()]
            concept_path = create_concept_infographic(concept_lines, category=INFO_CAT_ID)
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
            _extra = "\n".join((post.get("table_strs") or [])
                               + [post.get("summary_text", "")]
                               + [f"{q}\n{a}" for q, a in (post.get("faq_pairs") or [])])
            as_fields = extract_as_fields(GOOGLE_API_KEY, post["title"], post.get("body", ""),
                                          extra_text=_extra)
        except Exception as e:
            logger.warning(f"A/S 필드 추출 스킵(무해): {e}")
    entry = {
        "date": datetime.now(KST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(KST).isoformat(),
        "run_slot": run_slot,
        "keyword": keyword,
        "info_category": INFO_CAT_ID,
        "blog_category": BLOG_CATEGORY,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table": bool(post.get("table_strs")),
        "has_faq": bool(post.get("faq_pairs")),
        **as_fields,  # claim / claim_numbers / verify_event / verify_date
    }
    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"{BLOG_CATEGORY} 포스팅 완료: {post_url} | 이미지 {entry['images_inserted']}장")
    else:
        logger.error(f"{BLOG_CATEGORY} 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
