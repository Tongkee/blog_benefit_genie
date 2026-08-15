"""실계좌 투자 기록 — 토스증권 Open API → WP '투자 기록' 카테고리 주간 발행 (2026-07-17 뼈대).

키 발급 전엔 MOCK(스펙 예시)으로만 동작하며, MOCK 상태에선 절대 publish 하지 않는다
(크론=조용히 스킵 / 수동 ALLOW_MOCK=true + draft 검증만). 키 발급 후: 시크릿/.env에
TOSS_CLIENT_ID·TOSS_CLIENT_SECRET 등록 → 매주 일요일 21:30 자동 발행.

구성: 계좌 요약 → 보유 종목 표 → 이번 주 매매 일지 → 관찰 코멘트 → 다음 주 계획 → 면책.
사용: python -m scripts.toss_invest_post  (WP_STATUS/DRY_RUN/ALLOW_MOCK)
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, GOOGLE_API_KEY, WP_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("toss_invest_post")

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "toss_report_history.json")
CATEGORY = "투자 기록"          # WP 전용 카테고리(없으면 자동 생성)
CATEGORY_SLUG = "invest-log"

_EXTRA_INSTRUCTIONS = """\
- 이 글은 블로그 주인장이 매주 쓰는 '실계좌 적립식 투자 기록' 시리즈다. 페르소나는 그대로 현지언니 —
  "제 실제 계좌를 그대로 공개하는 기록"이라는 톤. 꾸밈·과장 없이 담백하게.
- ★투자 방식 = '주식 모으기(적립식·DCA)'. 매일 여러 종목에 정해둔 소액을 자동으로 나눠 담는 방식이다.
  '단타·매매·사고팔기'가 아니라 '꾸준히 모아간다'는 적립 톤으로 써라(팩트의 '투자 방식' 참고).
- 구조(순서 유지, 소제목 문구는 자연스럽게):
  ① 이번 주 계좌 한 줄 요약 — 평가금액·수익률을 두괄식으로(금액은 달러·원화 병기)
  ② 보유 종목 현황 — 표로(종목/수량/평단/현재가/수익률), 표 아래 눈에 띄는 종목 1~2개 코멘트
  ③ 이번 주 적립 일지 — 어떤 종목을 얼마씩 모았는지(적립식). '샀다 팔았다'가 아니라 '모았다' 톤. 없으면 '이번 주 적립 쉬어감' 한 줄
  ④ 배당·인컴 관찰 — 배당/인컴형 보유분(커버드콜·배당 ETF 등)에 대한 짧은 관찰
  ⑤ 앞으로의 계획 — 적립을 이어갈 방향 1~2개(단정 금지, '꾸준히 모아가려 해요' 톤)
- ★수치는 [팩트 데이터]의 값만 그대로 사용. 계산·추정으로 새 수치를 만들지 마라.
- ★금액은 팩트의 '$X (약 Y원)' 형식으로 달러·원화 병기. 수량은 팩트에 준 반올림값 그대로(소수점 6자리 등 과다 표기 금지).
- ★절대 투자 권유·종목 추천으로 읽히게 쓰지 마라. 특정 종목 매수 유도 문구 금지.
- 글 끝 면책 1줄: "이 글은 개인 투자 기록일 뿐 투자 권유가 아니며, 모든 투자 판단과 책임은
  본인에게 있습니다." """


def _load_history() -> dict:
    try:
        return json.load(open(HISTORY_PATH, encoding="utf-8"))
    except Exception:
        return {"count": 0, "posts": []}


def _ensure_category() -> None:
    """WP에 '투자 기록' 카테고리 보장 — 없으면 생성(최초 1회)."""
    import requests
    from poster.wp_publish import _api, _headers
    try:
        r = requests.get(_api("categories"), params={"search": CATEGORY, "per_page": 5},
                         headers=_headers(), timeout=15)
        if r.ok and any(c.get("name") == CATEGORY for c in r.json()):
            return
        r = requests.post(_api("categories"),
                          json={"name": CATEGORY, "slug": CATEGORY_SLUG,
                                "description": "실계좌로 쓰는 투자 기록 시리즈"},
                          headers=_headers(), timeout=15)
        if r.status_code in (200, 201):
            logger.info(f"WP 카테고리 생성: {CATEGORY}")
    except Exception as e:
        logger.warning(f"카테고리 보장 실패(발행은 계속): {e}")


def run():
    from generator.toss_collector import build_invest_facts, is_mock, has_manual_snapshot

    status = os.environ.get("WP_STATUS", "publish").strip().lower()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    allow_mock = os.environ.get("ALLOW_MOCK", "false").lower() == "true"

    manual = is_mock() and has_manual_snapshot()  # 캡처 스냅샷 = 실데이터(반자동 모드)
    if is_mock() and not manual:
        if not (allow_mock or dry_run):
            logger.info("토스 키 미발급(MOCK) — 크론 스킵. 검증은 ALLOW_MOCK=true 또는 DRY_RUN=true")
            return
        status = "draft"  # 가짜(MOCK) 데이터는 어떤 경우에도 실발행 금지
        logger.warning("MOCK 모드 — 강제 draft")

    history = _load_history()
    n = history.get("count", 0) + 1
    now = datetime.now(KST)
    period = f"{(now - timedelta(days=7)).strftime('%m월 %d일')} ~ {now.strftime('%m월 %d일')}"
    keyword = f"실계좌 투자 기록 {n}주차"

    topic = {
        "keyword": keyword,
        "category": CATEGORY,
        "hub_id": CATEGORY_SLUG,
        "facts": build_invest_facts(f"{n}주차 · {period}"),
        "key_stats": [],
        "sources": [("토스증권 (실계좌 데이터)", "https://tossinvest.com")],
        "use_search": False,  # 계좌 팩트만 — 외부 검색 섞지 않음
        "extra_instructions": _EXTRA_INSTRUCTIONS,
        # 실계좌 인증글은 팩트 위주 경량 — 심층 게이트(3000자·계산2·FAQ) 완화(2026-07-22)
        "gate": {"body_min": 1400, "min_calc": 0, "min_faq": 0, "require_table": False},
    }

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)
    from generator.deep_content import generate_deep_post
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("투자 기록 생성 실패")
        sys.exit(1)

    if dry_run:
        logger.info(f"[DRY_RUN] 생성만 완료: {post['title']!r} ({len(post.get('body', ''))}자)")
        print(post.get("body", "")[:600])
        return

    from generator.wp_render import render_wordpress_post
    from poster.wp_publish import (publish_wordpress, check_connection,
                                   upload_media_info, set_featured_image)
    if not check_connection():
        sys.exit(1)
    _ensure_category()

    slug = f"invest-log-{n:03d}"
    r = render_wordpress_post(
        post, category=CATEGORY, base_url=f"{WP_URL.rstrip('/')}/{slug}/",
        slug_override=slug, related_posts=[], site_url=WP_URL, category_slug=CATEGORY_SLUG,
    )

    # 실계좌 인증 캡처 (2026-07-17 사용자 지시: 인증이 신뢰의 핵심) —
    # data/toss_captures/ 에 이미지를 넣어두면 첫 h2 섹션 끝에 '실계좌 화면' 블록으로 삽입.
    # ★계좌번호 없는 화면(내투자 요약·보유목록)만 넣는 것이 규칙. 폴더는 gitignore(공개 레포).
    try:
        import glob as _glob
        import re as _re
        figs = ""
        # 자동 생성 실계좌 인증 카드(대시보드형, 항상 1장) — 2026-07-22 사용자 요청
        try:
            from poster.toss_card import render_account_card
            from generator.toss_collector import fetch_holdings, fetch_exchange_rate, _num as _tnum
            card = render_account_card(fetch_holdings(), _tnum(fetch_exchange_rate()), f"{n}주차 · {period}")
            if card:
                ci = upload_media_info(card, f"{slug}-card.png", alt_text="실계좌 현황 카드")
                if ci:
                    figs += (f'<figure class="wp-block-image size-large hj-proof">'
                             f'<img src="{ci["source_url"]}" alt="실계좌 현황 인증" loading="lazy"/>'
                             f'<figcaption>토스증권 Open API 실계좌 데이터 기준</figcaption></figure>\n')
                    logger.info("실계좌 인증 카드(자동 생성) 삽입")
        except Exception as e:
            logger.warning(f"인증 카드 생성 실패(무시): {e}")
        # 수동 캡처가 있으면 추가(계좌번호 없는 화면만)
        for i, cp in enumerate(sorted(_glob.glob(os.path.join(DATA_DIR, "toss_captures", "*.[pjPJ]*[gG]")))[:3], 1):
            info = upload_media_info(cp, f"{slug}-proof-{i}.png", alt_text=f"실계좌 화면 {i}")
            if info:
                figs += (f'<figure class="wp-block-image size-large hj-proof">'
                         f'<img src="{info["source_url"]}" alt="실계좌 화면" loading="lazy"/>'
                         f"<figcaption>실제 계좌 화면 ({now.strftime('%Y.%m.%d')} 캡처)</figcaption></figure>\n")
        if figs:
            h2s = list(_re.finditer(r'<h2 id="sec-\d+">[^<]+</h2>', r["content_html"]))
            pos = h2s[1].start() if len(h2s) > 1 else len(r["content_html"])
            r["content_html"] = r["content_html"][:pos] + figs + r["content_html"][pos:]
    except Exception as e:
        logger.warning(f"인증 이미지 삽입 실패(무시): {e}")
    res = publish_wordpress(r, title=post["title"], status=status, category=CATEGORY)
    if not res:
        sys.exit(1)
    logger.info(f"발행 완료 [{res['status']}] {res['link']}")

    try:
        from generator.wp_featured import build_featured_image
        img = build_featured_image(post["title"], keyword, CATEGORY, CATEGORY_SLUG,
                                   api_key=GOOGLE_API_KEY)
        if img:
            info = upload_media_info(img, f"featured-{slug}.png", alt_text=post["title"])
            try:
                os.unlink(img)
            except OSError:
                pass
            if info:
                set_featured_image(res["id"], info["id"])
    except Exception as e:
        logger.warning(f"대표 이미지 실패(무시): {e}")

    if status == "publish":
        history["count"] = n
        history.setdefault("posts", []).append(
            {"n": n, "date": now.strftime("%Y-%m-%d"), "slug": slug, "link": res.get("link", "")})
        os.makedirs(DATA_DIR, exist_ok=True)
        json.dump(history, open(HISTORY_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run()
