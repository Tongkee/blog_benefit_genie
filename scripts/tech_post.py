"""
형수의테크공장 — IT/테크 자동 포스팅 스크립트
GitHub Actions: python -m scripts.tech_post

형식 4종 로테이션(breaking/explain/pick/compare)을 순환 발행.
계정: hyungsutech (khj) — 현지언니와 별도. TECH_NAVER_* 시크릿 사용.
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
    DATA_DIR, LOG_DIR, GOOGLE_API_KEY,
    TECH_NAVER_ID, TECH_NAVER_PW, TECH_NAVER_BLOG_ID, TECH_NAVER_COOKIES,
    NAVER_ID, NAVER_PW, NAVER_COOKIES,  # 로컬 폴백용
)

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "tech_history.json")

# 형식 로테이션 — 5종 균등(2026-07-29 사용자 지시: 신생 블로그라 통계 기반 비중 조정은
# 아직 이르다 — 모든 형식에 공정한 기회를 주고 통계가 쌓이면 그때 방향 결정).
# 형식 자체는 벤치마킹으로 전면 개편: breaking=팩트체크·판정형, compare=승자판정형, top5 신설.
# 성과는 이력 fmt 필드로 추적 — 표본이 쌓이면 어드바이저 조인해 형식별 성적표.
FMT_ROTATION = ["pick", "compare", "top5", "explain", "breaking"]

# 발행 카테고리는 '검색 의도(형식)' 기준(2026-07-29 벤치마크 카테고리 재편).
# 제품군 카테고리(_post_category)는 주제 선정·하루1편 가드·내부링크 기준으로 계속 사용.
# pick(리뷰)은 제품군 카테고리 그대로 → '리뷰·실사용' 그룹 하위.
# 실제 생성된 영어 카테고리 기준(2026-07-29 사용자 최종 확정: BEST PICK 대표/REVIEW/How-To/TECH NEWS).
FMT_BLOG_CATEGORY = {
    "breaking": "TECH NEWS",
    "explain": "Tech 101",
    "compare": "BEST PICK",
    "top5": "BEST PICK",
}
# 제품군(주제 선정용 내부명) → 실제 블로그 카테고리(REVIEW 하위 영어명) 번역.
# CATEGORY_ORDER 내부명은 뉴스 시드·이력 가드가 쓰므로 유지하고 발행 시점만 번역한다.
CAT_BLOG_ALIAS = {
    "스마트폰·모바일": "Mobile",
    "PC·노트북": "PC·Laptop",
    "가전·디지털": "Home Tech",
    "자동차·모빌리티": "Mobility",
    "AI·IT": "TECH NEWS",
}

# 카테고리별 하루 1편 발행 순서 (2026-07-17 사용자 지시) — 크론 슬롯마다
# '오늘 아직 안 나간 카테고리' 중 첫 번째를 발행. 뉴스 없으면 다음 카테고리로 넘어감.
CATEGORY_ORDER = ["스마트폰·모바일", "PC·노트북", "가전·디지털", "자동차·모빌리티", "AI·IT"]

# ★2026-07-30 재설계: '블로그 카테고리' 직접 로테이션 (9카테고리 균형 발행).
# 종전 '제품군 하루1편 + 형식 로테이션'은 형식이 블로그 카테고리를 정해 REVIEW 하위(Mobile 등)가
# 굶고 BEST PICK/TECH NEWS/Tech 101에 편중됐다(pick만 REVIEW로 가고 그마저 5제품군 중 1개씩).
# 뉴스 트랙이 채우는 7개 블로그 카테고리를 (blog_cat, fmt, 제품군제약)으로 정의하고,
# 최근 7일 최소 발행 카테고리부터 채운다. 가이드 트랙(Troubleshooting/AI Lab)은 별도.
NEWS_BLOG_RECIPES = [
    ("TECH NEWS", "breaking", None),   # 속보·팩트체크 (제품군 무관, 최고 온도)
    ("Tech 101",  "explain",  None),   # 개념·설명형
    ("BEST PICK", "compare",  None),   # 비교·승자판정
    ("BEST PICK", "top5",     None),   # 순위형 (BEST PICK=대표라 2슬롯)
    ("Mobile",    "pick", "스마트폰·모바일"),
    ("PC·Laptop", "pick", "PC·노트북"),
    ("Home Tech", "pick", "가전·디지털"),
    ("Mobility",  "pick", "자동차·모빌리티"),
]
# 블로그 카테고리별 하루 발행 상한(BEST PICK만 대표라 2, 나머지 1).
BLOG_CAT_DAILY_MAX = {"BEST PICK": 2}


def _entry_blog_cat(h: dict) -> str:
    """이력 항목의 블로그 카테고리 — 신 항목=blog_category, 구 항목=fmt+제품군으로 역산."""
    if h.get("blog_category"):
        return h["blog_category"]
    fmt = h.get("fmt", "")
    if fmt in FMT_BLOG_CATEGORY:
        return FMT_BLOG_CATEGORY[fmt]
    from generator.tech_content import SEED_CATEGORY
    prod = h.get("category") or SEED_CATEGORY.get(h.get("seed", ""), "")
    return CAT_BLOG_ALIAS.get(prod, prod)

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "tech_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("tech_post")


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


def _posted_categories_today(history: list) -> set:
    """오늘 이미 발행된 제품군 집합. 구 이력(category 필드 없음)은 seed로 역추론."""
    from generator.tech_content import SEED_CATEGORY
    today = datetime.now(KST).strftime("%Y-%m-%d")
    cats = set()
    for h in history:
        if h.get("date") == today and h.get("status") == "posted":
            cat = h.get("category") or SEED_CATEGORY.get(h.get("seed", ""), "")
            if cat:
                cats.add(cat)
    return cats


def _posted_blog_cats_today(history: list):
    """오늘 발행된 '블로그 카테고리'별 건수(균형 로테이션 기준, 2026-07-30)."""
    from collections import Counter
    today = datetime.now(KST).strftime("%Y-%m-%d")
    c = Counter()
    for h in history:
        if h.get("date") == today and h.get("status") == "posted":
            bc = _entry_blog_cat(h)
            if bc:
                c[bc] += 1
    return c


# 주제 과열 게이트 유틸(2026-07-28) — 제목의 핵심 토큰으로 '같은 제품·이슈' 판정.
# 수식어·형식어는 제외해 제품명(갤럭시·폴드8 등) 중심으로 겹침을 센다.
_TOPIC_STOP = {"진짜", "총정리", "가이드", "이유", "방법", "확인", "정리", "출시", "공개",
               "후회", "손해", "이득", "혜택", "최신", "절차", "설정", "해결", "활용",
               "이것", "저것", "무엇", "어떻게", "드디어", "대박", "시리즈"}


def _sig_tokens(title: str) -> set:
    toks = re.findall(r"[가-힣A-Za-z0-9]{2,}", title or "")
    return {w for w in toks if w not in _TOPIC_STOP and not w.isdigit()}


def _recent_gate_titles(history: list, days: int = 3) -> list:
    """최근 N일 발행 제목(뉴스 트랙 + 심층 가이드 트랙 합산 — 가이드도 같은 블로그에 발행)."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    titles = [h.get("title", "") for h in history
              if h.get("status") == "posted" and h.get("date", "") >= cutoff]
    try:
        gh = json.load(open(os.path.join(DATA_DIR, "tech_guide_history.json"), encoding="utf-8"))
        titles += [h.get("title", "") for h in gh
                   if h.get("status") == "posted" and h.get("date", "") >= cutoff]
    except Exception:
        pass
    return [t for t in titles if t]


def _topic_overused(headline: str, recent_titles: list, need_overlap: int = 2) -> bool:
    """표면형 토큰 겹침 — 보조 게이트로만 남긴다.

    ★2026-07-31 실측: 이 게이트는 사실상 한 번도 발동한 적이 없다.
    *뉴스 헤드라인*을 *블로그 제목*과 비교하는데 어휘 공간이 다르고
    (언론사 "삼성 폴더블 사전예약서" vs 블로그 "갤럭시 Z 폴드8"),
    한국어 형태론(`갤럭시Z폴드8`=1토큰 vs `갤럭시`+`폴드8`=2토큰, `가격`≠`가격은`)을
    토큰 완전일치가 못 넘는다. 실제 중복 3쌍을 넣어보면 교집합이 전부 공집합이었다.
    → 주 게이트는 아래 _topic_key_blocked(엔티티 기준)로 옮겼다.
    """
    ht = _sig_tokens(headline)
    return any(len(ht & _sig_tokens(rt)) >= need_overlap for rt in recent_titles)


def _topic_key_of(headline: str, seed: str) -> str:
    """이력 저장용 주제 키(모듈 없으면 빈 문자열 — 발행은 막지 않는다)."""
    try:
        from generator.tech_topic_key import topic_key
        return topic_key(headline, seed)
    except Exception:
        return ""


def _topic_key_blocked(headline: str, seed: str, history: list) -> str:
    """엔티티 기준 주제 상한 — 같은 주제 하루 1건 / 7일 2건.

    폴드8이 2주에 8~12건 나간 실사고의 직접 대책(2026-07-31).
    차단 사유 문자열을 반환하고, 통과면 빈 문자열.
    """
    try:
        from generator.tech_topic_key import count_recent, topic_key
    except Exception:
        return ""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    key = topic_key(headline, seed)
    if count_recent(key, history, days=1, today=today) >= 1:
        return f"'{key}' 오늘 이미 발행"
    if count_recent(key, history, days=7, today=today) >= 2:
        return f"'{key}' 최근 7일 2건 도달"
    return ""


def _recent_headlines(history: list, days: int = 14) -> set:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {h["headline"] for h in history if h.get("date", "") >= cutoff and h.get("headline")}


def _next_format(history: list) -> str:
    """로테이션 순번 선택 — 발행 횟수 기반.
    ※직전 fmt의 index+1 방식은 중복 슬롯(pick 2회)에서 첫 index만 잡아
    pick↔compare 루프에 고착되고 breaking·두번째 pick이 영원히 안 돈다(2026-07-29)."""
    n = sum(1 for h in history if h.get("fmt"))
    return FMT_ROTATION[n % len(FMT_ROTATION)]


def _is_real_post_url(url) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _clean_shopping_placeholder(body: str) -> str:
    """쇼핑커넥트 링크 미발급 상태 — [쇼핑추천] 마커와 안내 플레이스홀더 줄 제거(리터럴 노출 방지)."""
    body = re.sub(r"^[ \t]*\[쇼핑추천\]\s*$\n?", "", body, flags=re.MULTILINE)
    body = re.sub(r"^[ \t]*\(※\s*쇼핑커넥트.*$\n?", "", body, flags=re.MULTILINE)
    return body


def _extract_summary_for_postit(post: dict):
    """본문의 '핵심 요약' 소제목+불릿 섹션을 인용구용으로 분리 (2026-07-17 사용자 지시).
    성공 시 post['summary_text']를 채우고 본문 자리는 [요약삽입] 마커로 교체
    → poster가 도입부 뒤 '포스트잇' 인용구 블록으로 삽입한다."""
    body = post.get("body", "")
    m = re.search(r"\[구분선\]\n([^\n]*(?:요약|핵심만)[^\n]*)\n((?:·[^\n]+\n?)+)", body)
    if not m:
        # 폴백(07-17 draft 실측): 모델이 요약 소제목에 제품명을 넣어 '요약' 단어가 빠지는 경우 —
        # '첫 번째 섹션이 불릿 2~4줄로만 구성'이면 구조상 핵심 요약(_BENCH_OPEN 고정 위치)으로 간주.
        cand = re.search(r"\[구분선\]\n([^\n]+)\n((?:·[^\n]+\n?)+)", body)
        if cand:
            n_bullets = len([l for l in cand.group(2).splitlines() if l.strip()])
            nxt = body[cand.end():].lstrip("\n")
            if (cand.start() == body.find("[구분선]") and 2 <= n_bullets <= 4
                    and (not nxt or nxt.startswith(("[구분선]", "[사진", "[표", "[FAQ")))):
                m = cand
    if not m:
        logger.info("핵심 요약 섹션 미검출 — 포스트잇 인용구 생략(본문 그대로)")
        return
    post["summary_text"] = m.group(2).strip()
    post["body"] = body[:m.start()] + "[요약삽입]\n" + body[m.end():]
    sub = m.group(1).strip()
    post["subheadings"] = [s for s in post.get("subheadings", []) if s != sub]
    logger.info(f"핵심 요약 {len(post['summary_text'].splitlines())}줄 → 포스트잇 인용구로 분리 ('{sub}')")


def _inject_section_images(post: dict, pool: list[dict], images: list[dict],
                           make_card=None, max_body: int = 3, max_cards: int = 2) -> None:
    """콘텐츠 소제목 아래 [사진N] 마커 주입 (2026-07-27 고도화).
    ①실사진 풀(pool)을 우선 소진 — 기존 인덱스 1:1 페어링 결함(대상 소제목이 표/요약
      플레이스홀더로 시작하면 확보한 사진을 폐기하고 이월하지 않던 문제)을
      '다음 적합 소제목으로 이월'로 수정.
    ②실사진이 부족하면 브랜드 섹션 미니카드(make_card(소제목, 카드인덱스)→경로|None)로
      채워 본문 이미지를 보증 — 소제목 텍스트 카드라 오프토픽 자체가 불가능해
      '무관 사진 방지 필터 유지' 정책과 양립한다.
    images 리스트에 항목을 추가하고 post['body']를 갱신한다."""
    # 모델이 소제목 문구를 변형('핵심 요약'/'목차 정리' 등)해도 걸리도록 부분일치로 스킵(2026-07-16)
    _skip_kw = ("핵심 요약", "핵심만", "목차", "총평", "자주 묻는 질문", "요약")
    content_subs = [s for s in post.get("subheadings", [])
                    if not any(k in s.strip() for k in _skip_kw)]
    targets = content_subs[1:] or content_subs  # 첫 콘텐츠 섹션은 헤더와 가까워 두 번째부터
    body = post.get("body", "")
    marker_n, inserted, cards = 2, 0, 0
    for sub in targets:
        if inserted >= max_body:
            break
        if not pool and (make_card is None or cards >= max_cards):
            break
        pat = f"[구분선]\n{sub}\n"  # 실제 소제목([구분선] 뒤)만 매칭 — 목차 '· {sub}'는 안 걸림
        if pat not in body:
            continue
        # 소제목 바로 다음 줄이 표/요약/FAQ 플레이스홀더면 스킵 — [사진N] 다음 앵커가 산문이 아니라
        # following-anchor가 비어 소제목 텍스트 폴백(목차 충돌 위험)을 타는 경로 차단(2026-07-16).
        # ★사진은 버리지 않고 다음 적합 소제목으로 이월한다(2026-07-27 결함 수정).
        after = body.split(pat, 1)[1].lstrip("\n")
        if after.startswith(("[표삽입]", "[요약삽입]", "[FAQ삽입]", "[표시작]")):
            logger.info(f"섹션 이미지 슬롯 스킵: '{sub[:15]}' 다음이 플레이스홀더({after[:8]}…) — 다음 소제목으로 이월")
            continue
        if pool:
            im = pool.pop(0)
            local, lbl, kind = im["local_path"], im.get("label", ""), im.get("kind", "실사진")
        else:
            local = None
            try:
                local = make_card(sub, cards)
            except Exception as e:
                logger.warning(f"섹션 미니카드 생성 실패: {e}")
            if not local:
                break  # 카드 생성이 안 되는 환경(Playwright 등) — 남은 슬롯 생략
            lbl, kind = "", "미니카드"
            cards += 1
        # ★소제목 '다음 줄'에 [사진N] 주입 → 마커 다음의 '고유한 본문 첫 줄'이 앵커가 되어 그 앞에 삽입.
        #   insert_before(소제목 텍스트)는 목차에도 같은 텍스트가 있어 목차 항목에 먼저 걸리므로 쓰지 않는다.
        body = body.replace(pat, f"{pat}[사진{marker_n}]\n", 1)
        images.append({
            "local_path": local, "url": "",
            "alt_text": post.get("seed", "테크"), "label": lbl,
        })
        logger.info(f"섹션 이미지 예약: [사진{marker_n}] → '{sub[:15]}' 섹션 ({kind})")
        marker_n += 1
        inserted += 1
    post["body"] = body


def run():
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(f"[형수의테크공장] 포스팅 시작 (슬롯 {run_slot}): {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    logger.info("=" * 60)

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료")
        sys.exit(1)

    force = os.environ.get("FORCE_POST", "false").lower() == "true"
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    # 계정: TECH_NAVER_* 우선, 없으면 로컬 테스트용 NAVER_* 폴백
    naver_id = TECH_NAVER_ID or NAVER_ID
    naver_pw = TECH_NAVER_PW or NAVER_PW
    naver_cookies = TECH_NAVER_COOKIES or NAVER_COOKIES
    blog_id = TECH_NAVER_BLOG_ID or "hyungsutech"

    if not dry_run and not naver_id and not naver_cookies:
        logger.error("TECH_NAVER 계정/쿠키 없음 — 발행 불가 (DRY_RUN만 가능)")
        sys.exit(1)

    history = _load_history()

    # ── 1. 블로그 카테고리 균형 선택 + 형식 + 주제 (2026-07-30 재설계) ──
    # 종전 '제품군 하루1편 + 형식 로테이션 + 주간상한'을 폐지하고, 뉴스 트랙이 채우는 7개
    # 블로그 카테고리(NEWS_BLOG_RECIPES)를 '최근 7일 최소 발행분부터' 직접 로테이션한다.
    # → REVIEW 하위 굶주림·BEST PICK 편중 해소. 주간상한 불필요(하루 상한이 폭주 방지).
    from generator.tech_content import generate_tech_post, pick_tech_topic, SEED_CATEGORY
    from collections import Counter as _Counter

    forced_fmt = os.environ.get("FORCE_FMT", "").strip()          # 형식 강제
    forced_bcat = os.environ.get("TECH_BLOG_CATEGORY", "").strip()  # 블로그 카테고리 강제
    forced_prod = os.environ.get("TECH_CATEGORY", "").strip()      # 제품군 강제(하위호환)

    bcat_today = _Counter() if force else _posted_blog_cats_today(history)
    _wk_cut = (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")
    # ★균형 카운트는 '새 시스템 글'(blog_category 필드 보유)만 센다. 개편(2026-07-29) 전 글은
    # 옛 제품군 카테고리로 발행됐으므로 역산하면 새 영어 카테고리를 오판(예: TECH NEWS 실제 0인데
    # 역산 7)한다. 전환 시점엔 전부 0에서 시작 → 굶주린 신규 카테고리부터 고르게 채워진다.
    wk_bcat = _Counter(h["blog_category"] for h in history
                       if h.get("status") == "posted" and h.get("date", "") >= _wk_cut
                       and h.get("blog_category"))

    # 후보 레시피: 오늘 상한 미달 + (강제 필터 적용)
    recipes = []
    for bcat, rfmt, prod in NEWS_BLOG_RECIPES:
        if forced_bcat and bcat != forced_bcat:
            continue
        if forced_fmt and rfmt != forced_fmt:
            continue
        if forced_prod and prod != forced_prod:
            continue
        day_max = BLOG_CAT_DAILY_MAX.get(bcat, 1)
        if not force and bcat_today.get(bcat, 0) >= day_max:
            continue
        recipes.append((bcat, rfmt, prod))
    if not recipes:
        logger.info(f"오늘 블로그 카테고리 발행 상한 도달 — 슬롯 {run_slot} 건너뜀")
        return

    # 최근 7일 최소 발행 카테고리 우선(균형) → 동률이면 레시피 정의 순서
    recipes.sort(key=lambda r: (wk_bcat.get(r[0], 0), NEWS_BLOG_RECIPES.index(r)))
    logger.info("블로그 카테고리 균형(7일): "
                + " | ".join(f"{b}={wk_bcat.get(b, 0)}"
                             for b in dict.fromkeys(r[0] for r in NEWS_BLOG_RECIPES)))

    recent_heads = _recent_headlines(history)     # 같은 헤드라인 재발행 차단
    recent_titles = _recent_gate_titles(history)  # 같은 제품·이슈 과열 차단

    # 균형 순서로 순회하며 '발행 가능한(뉴스 있는)' 첫 카테고리 선정.
    # 제품군 제약(pick 계열) 있으면 그 시드만, 없으면(형식형) 전체 시드에서 최고 온도 주제.
    chosen = None
    for bcat, rfmt, prod in recipes:
        cat_seeds = [s for s, c in SEED_CATEGORY.items() if c == prod] if prod else None
        _ex = set(recent_heads)
        topic = None
        for _ in range(3):  # 과열 주제면 제외하고 최대 3회 재탐색
            t = pick_tech_topic(exclude_headlines=_ex, seeds=cat_seeds)
            if not t:
                break
            # ★주 게이트: 엔티티 기준 주제 상한(2026-07-31). 표면형 토큰 게이트는
            # 어휘 공간·형태론 문제로 실제 중복을 한 번도 못 잡았다.
            _blk = _topic_key_blocked(t.get("headline", ""), t.get("seed", ""), history)
            if _blk:
                logger.info(f"주제 상한 제외({bcat}): {_blk} — {t.get('headline', '')[:36]}")
                _ex.add(t.get("headline", ""))
                continue
            if _topic_overused(t.get("headline", ""), recent_titles):
                logger.info(f"주제 과열 제외({bcat}): {t.get('headline', '')[:40]}")
                _ex.add(t.get("headline", ""))
                continue
            topic = t
            break
        if topic:
            chosen = (bcat, rfmt, prod, topic)
            break
        logger.info(f"블로그 카테고리 '{bcat}' 최신 소비자 뉴스 없음 — 다음 후보")

    if not chosen:
        # 뉴스 없음 — 억지 발행 대신 정상 스킵(2026-07-16)
        logger.warning("발행할 소비자 주제 없음(잔여 카테고리 전부 뉴스 부족/B2B성) — 이번 슬롯 스킵")
        sys.exit(0)

    blog_cat, fmt, _prod_filter, topic = chosen
    _post_category = _prod_filter or SEED_CATEGORY.get(topic.get("seed", ""), "AI·IT")
    logger.info(f"블로그카테고리={blog_cat} | 형식={fmt} | 제품군={_post_category} "
                f"| 시드={topic['seed']} | 주제={topic['headline'][:40]}")

    # ── 2. 글 생성 ──
    post = generate_tech_post(GOOGLE_API_KEY, fmt=fmt, topic=topic)
    if not post:
        logger.error("테크글 생성 실패 — 종료")
        sys.exit(1)

    # 본문 사진 마커([사진2]+)·쇼핑 플레이스홀더 정리
    if post.get("body"):
        post["body"] = re.sub(r"^[ \t]*\[사진([2-9]|\d{2,})\]\s*$\n?", "", post["body"], flags=re.MULTILINE)
        post["body"] = _clean_shopping_placeholder(post["body"])

    # 핵심 요약 섹션 → 포스트잇 인용구로 분리 (2026-07-17 사용자 지시)
    _extract_summary_for_postit(post)

    # {{음영}} 마커는 본문 전용 — 별도 타이핑 경로(제목/요약/표/FAQ)에 섞이면 리터럴로
    # 노출되므로 방어적 평문화(포스터의 본문 추출은 body만 처리, 2026-07-17)
    _unbrace = lambda s: re.sub(r"\{\{(.+?)\}\}", r"\1", s or "")
    post["title"] = _unbrace(post.get("title", ""))
    post["summary_text"] = _unbrace(post.get("summary_text", ""))
    if post.get("table_str"):
        post["table_str"] = _unbrace(post["table_str"])
    if post.get("table_strs"):
        post["table_strs"] = [_unbrace(t) for t in post["table_strs"]]
    if post.get("faq_questions"):
        post["faq_questions"] = [_unbrace(q) for q in post["faq_questions"]]
    if post.get("faq_pairs"):
        post["faq_pairs"] = [[_unbrace(q), _unbrace(a)] for q, a in post["faq_pairs"]]

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:600] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    # ── 3. 이미지: 실사진 우선 + 브랜드 미니카드 보증 (07-17 피드백 '무관 스톡·AI 일러스트
    # 금지'는 유지 / 2026-07-27: 본문 이미지 0장 방지 — 실사진 부족분은 소제목 텍스트 기반
    # 브랜드 섹션 미니카드로 채움. 텍스트 카드라 오프토픽 자체가 불가능) ──
    # 실사진 소스: 신뢰 언론사 og(시드 뉴스 + 제품명 보조 뉴스검색) → 네이버쇼핑 상품 실사.
    images: list[dict] = []
    from config import PEXELS_API_KEY

    def _ensure_local(p: dict):
        lp = p.get("local_path")
        if not lp and p.get("url"):
            try:
                from poster.naver_blog import _download_image_to_temp
                lp = _download_image_to_temp(p["url"], label=p.get("label"))
            except Exception as e:
                logger.warning(f"이미지 다운로드 실패: {e}")
        return lp

    photos: list[dict] = []
    try:
        from generator.tech_image import get_tech_photos
        # 생성된 실제 제목(정확한 모델명 포함)을 이미지 주제/쿼리 기준으로 넘긴다 —
        # seed가 헤드라인과 어긋나(2026-07-25 실측: seed '갤럭시 Z 플립'인데 글은 폴드8)
        # 엉뚱한 모델 이미지(폴드8 글에 플립7, 로보락 글에 삼성청소기)가 붙던 문제 방지.
        topic["title"] = post.get("title", "")
        photos = get_tech_photos(topic, PEXELS_API_KEY, want=3)
    except Exception as e:
        logger.warning(f"실사진 확보 실패: {e}")

    # 대표(헤더): 실사진 훅카드 → (실사진 없으면) 다크 텍스트 카드. AI 일러스트 금지(07-17).
    lead_local = _ensure_local(photos[0]) if photos else None
    lead_label = photos[0].get("label", "") if photos else ""
    lead_kind = "실사진"
    if lead_local:
        header_local = None
        try:
            from poster.infographic_html import create_photo_header_card
            header_local = create_photo_header_card(
                lead_local, post["title"], keyword=post.get("seed", "테크"), category="tech"
            )
        except Exception as e:
            logger.warning(f"헤더카드 실패 — 원본 이미지 사용: {e}")
        images.append({
            "local_path": header_local or lead_local, "url": "",
            "alt_text": post.get("seed", "테크"),
            # 카드는 이미지가 이미 박혀 있어 '출처' 캡션 불필요, 원본 폴백 시에만 캡션.
            "label": "" if header_local else lead_label,
        })
        logger.info(f"대표 헤더 확보: {lead_kind}{'+훅카드' if header_local else '(원본)'}")
    else:
        try:
            from poster.infographic_html import create_tech_header_card
            tc = create_tech_header_card(post["title"], keyword=post.get("seed", "테크"))
            if tc:
                images.append({"local_path": tc, "url": "",
                               "alt_text": post.get("seed", "테크"), "label": ""})
                logger.info("대표 헤더: 테크 텍스트 카드(최후 폴백)")
        except Exception as e:
            logger.warning(f"테크 텍스트 카드 실패 — 대표 이미지 없음: {e}")

    # 섹션 이미지 — 콘텐츠 소제목(핵심요약/목차/총평/FAQ 제외) 아래 [사진N] 주입.
    # 소스 풀: ①실사진(og+쇼핑) 잔여분 우선(상한 2장 유지) ②부족분은 브랜드 섹션
    # 미니카드로 보증(2026-07-27) — 페어링·이월 로직은 _inject_section_images 참고.
    if images:
        pool: list[dict] = []
        for ph in photos[1:]:
            local = _ensure_local(ph)
            if local:
                pool.append({"local_path": local, "label": ph.get("label", ""), "kind": "실사진"})
        pool = pool[:2]  # 실사진 잔여분 상한 2장(기존 유지)

        def _make_card(sub: str, idx: int):
            # 2026-07-28 사용자 피드백: 소제목을 복창하는 텍스트 미니카드는 무의미 —
            # 주제 관련 AI 일러스트로 교체, 실패 시 None(_inject가 삽입 생략 — 무이미지가 낫다).
            from generator.tech_image import generate_section_illustration
            return generate_section_illustration(topic.get("seed", ""), sub, GOOGLE_API_KEY)

        _inject_section_images(post, pool, images, make_card=_make_card)

    # 함께 보면 좋은 글 — 같은 카테고리 과거 발행글 1~2개 링크(체류시간·내부 순환,
    # 현지언니 daily_post._append_internal_links 이식, 2026-07-19 사용자 요청)
    related = [h for h in history
               if h.get("status") == "posted" and h.get("post_url") and h.get("title")
               and h.get("category") == _post_category][:2]
    if related:
        links_text = "\n\n함께 보면 좋은 글\n"
        for r in related:
            links_text += f"\n[가운데] {r['post_url']}"
        post["body"] += links_text + "\n"
        post["subheadings"] = post.get("subheadings", []) + ["함께 보면 좋은 글"]
        logger.info(f"내부링크 추가: 같은 카테고리({_post_category}) 과거 글 {len(related)}개")

    # 네이버 마크다운 잔여 정리 (WP엔 normalize_residual_md 있으나 네이버 tech는 없어
    # 불릿 리터럴 누출 실측 2026-07-22) — 볼드 마커 제거 + 줄머리 불릿 → '· '(U+00B7)
    import re as _re
    _b = post.get("body", "")
    _b = _re.sub(r"\*\*(.+?)\*\*", r"\1", _b)
    _b = _re.sub(r"(?m)^[ \t]*[*\-•]\s+", "· ", _b)
    post["body"] = _b

    # ── 4. 포스팅 ──
    from poster.naver_blog import post_to_naver_blog
    try:
        result = post_to_naver_blog(
            naver_id=naver_id,
            naver_pw=naver_pw,
            blog_id=blog_id,
            title=post["title"],
            body=post["body"],
            tags=post["tags"],
            naver_cookies=naver_cookies,
            images=images if images else None,
            draft=draft,
            allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
            table_str=post.get("table_str", ""),
            table_strs=post.get("table_strs", []),
            subheadings=post.get("subheadings", []),
            faq_questions=post.get("faq_questions", []),
            category=blog_cat,  # 재설계(2026-07-30): 레시피가 블로그 카테고리를 직접 확정
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
            summary_quote_style="포스트잇",  # 핵심 요약=포스트잇 인용구 (2026-07-17 사용자 지시)
            set_representative=True,  # 헤더카드를 홈판 대표 썸네일로(tech 전용 opt-in)
            style_line_markers=True,  # {{음영}} 형광펜 + [[단독줄]] 미니소제목 (2026-07-17 벤치마킹)
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
        "fmt": fmt,
        "seed": post.get("seed", ""),
        "headline": topic["headline"],
        # 주제 동일성 키(2026-07-31) — 다음 실행의 상한 판정 기준. 표면형이 아니라
        # 엔티티라서 '갤럭시Z폴드8'과 '갤럭시 Z 폴드8, 플립8'이 같은 키로 묶인다.
        "topic_key": _topic_key_of(topic.get("headline", ""), post.get("seed", "")),
        "category": _post_category,   # 제품군(내부링크·시드 역호환)
        "blog_category": blog_cat,    # 블로그 카테고리(균형 로테이션·하루상한 기준, 2026-07-30)
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_inserted": result.get("images_inserted", 0) if result else 0,
    }
    history = _load_history()
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"형수의테크공장 포스팅 완료 [{fmt}]: {post_url}")
    else:
        logger.error(f"형수의테크공장 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
