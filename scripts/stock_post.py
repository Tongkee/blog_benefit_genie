"""
주식 블로그 자동 포스팅 (공모주·주식분석·ETF).
팩트 수집 → Gemini 원고 → 네이버 블로그 포스팅.

GitHub Actions: STOCK_TOPIC=etf포트폴리오 python -m scripts.stock_post
"""
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone, timedelta

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import (
    DATA_DIR,
    LOG_DIR,
    GOOGLE_API_KEY,
    NAVER_ID,
    NAVER_PW,
    NAVER_BLOG_ID,
    NAVER_COOKIES,
)
from generator.stock_content import STOCK_TOPICS

KST = timezone(timedelta(hours=9))

STOCK_TOPIC_MAP = {
    "종목분석": "종목분석",
    "공모주캘린더": "공모주캘린더",
    "etf포트폴리오": "etf포트폴리오",
}

_CARD_CATEGORY = {
    "종목분석": "주식분석",
    "공모주캘린더": "공모주",
    "etf포트폴리오": "주식etf",
}

_INDIVIDUAL_ETF_TYPES = ("kr_individual", "us_individual", "kr_overseas_individual")


def _card_hook_keyword(keyword: str, fact_data, stock_topic: str) -> str:
    """헤더 카드 표시 문구를 절반 확률로 호기심형 질문으로 바꿔보는 실험(카드 전용, 실제
    게시글 제목·alt텍스트는 건드리지 않음). 단일종목/ETF 분석처럼 "사도 될까?"가 실제로
    본문이 답하는 질문일 때만 적용 — 비교·절세계좌 글에는 어울리지 않아 제외."""
    if stock_topic == "종목분석":
        is_individual = True
    elif stock_topic == "etf포트폴리오" and isinstance(fact_data, dict):
        is_individual = fact_data.get("_etf_content_type") in _INDIVIDUAL_ETF_TYPES
    elif stock_topic == "공모주캘린더" and isinstance(fact_data, dict):
        # 개별 공모주 심층분석 — 본문이 실제로 '넣을까 말까'에 답하므로 질문형 훅 적합
        if fact_data.get("_ipo_mode") == "deep" and fact_data.get("종목명") and random.random() < 0.5:
            return f"{fact_data['종목명']} 청약, 넣을까?"
        return keyword
    else:
        is_individual = False
    if not is_individual or random.random() >= 0.5:
        return keyword
    base = keyword.replace(" 분석", "").strip()
    return f"{base} 지금 사도 될까?"


def _pick_ipo_content(ipo_list: list, history: list, force_mode: str = "", ignore_history: bool = False):
    """공모주 발행 모드 선택 (2026-07-07 재설계 — 매일 같은 일정을 반복하던 유사문서 해소).
    1) deep: 청약 D-1~마감 사이 종목 중 미발행 1개 → 개별 심층분석(균등/비례/패스 판단 가이드)
    2) monthly: 매월 25일 이후(또는 월초 1~3일 이월분) '해당 월 일정 총정리' 1회
    3) (None, None): 오늘 발행 없음 → 슬롯 스킵
    force_mode('deep'/'monthly')는 workflow_dispatch 테스트용 — 날짜 윈도 무시하고 강제 선택."""
    from datetime import timedelta

    from generator.stock_collector import StockDataCollector

    today = datetime.now(KST).date()
    covered = set() if ignore_history else {
        h.get("stock_name") for h in history if h.get("status") == "posted" and h.get("stock_name")
    }

    def _status_line(start, end) -> str:
        if today < start:
            return f"청약 시작까지 D-{(start - today).days} ({start.month}월 {start.day}일 시작, {end.month}월 {end.day}일 마감)"
        if today == start:
            return f"오늘 청약 시작 ({end.month}월 {end.day}일 마감)"
        if today == end:
            return "오늘 청약 마감일"
        if start < today < end:
            return "청약 진행 중"
        return "청약 마감됨"

    def _build_deep(entry: dict, start, end) -> dict:
        fact = dict(entry)
        fact["_ipo_mode"] = "deep"
        fact["청약상태"] = _status_line(start, end)
        fact["_header_keyword"] = f"{entry['종목명']} 공모주 청약"
        # 38커뮤니케이션 보강(확약·기관경쟁률·밴드) + 최근 뉴스 — 전부 best-effort
        try:
            detail = StockDataCollector.get_ipo_38_detail(entry["종목명"])
            for k, v in detail.items():
                fact.setdefault(k, v)
        except Exception as e:
            logger.warning(f"공모주 상세 보강 실패(무시): {e}")
        try:
            news = StockDataCollector.get_search_news([f"{entry['종목명']} 공모주"])
            if news:
                fact["최근뉴스"] = news
        except Exception as e:
            logger.warning(f"공모주 뉴스 보강 실패(무시): {e}")
        return fact

    def _deep_pick(window: bool):
        cands = []
        for e in ipo_list:
            rng = StockDataCollector.parse_ipo_date_range(e.get("청약일", ""))
            if not rng or e.get("종목명") in covered:
                continue
            start, end = rng
            if window and not ((start - timedelta(days=1)) <= today <= end):
                continue
            if not window and end < today:
                continue
            cands.append((start, e, end))
        cands.sort(key=lambda x: x[0])
        if cands:
            start, e, end = cands[0]
            return _build_deep(e, start, end)
        return None

    def _monthly_target():
        if today.day >= 25:
            return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        if today.day <= 3:
            return (today.year, today.month)  # 월말 슬롯을 놓친 경우 월초 이월 발행
        return None

    def _build_monthly(y: int, m: int):
        key = f"{y:04d}-{m:02d}"
        if not ignore_history and any(
            h.get("ipo_month") == key and h.get("status") == "posted" for h in history
        ):
            return None
        sched = []
        for e in ipo_list:
            rng = StockDataCollector.parse_ipo_date_range(e.get("청약일", ""))
            if rng and rng[0].year == y and rng[0].month == m:
                sched.append(e)
        if not sched:
            return None
        sched.sort(key=lambda e: e.get("청약일", ""))
        return {
            "_ipo_mode": "monthly",
            "_ipo_month": key,
            "대상월": f"{y}년 {m}월",
            "청약일정": sched,
            "_header_keyword": f"{m}월 공모주 청약 일정",
        }

    if force_mode == "deep":
        fact = _deep_pick(window=False)
        return ("deep", fact) if fact else (None, None)
    if force_mode == "monthly":
        y, m = _monthly_target() or (
            (today.year, today.month) if today.day < 25
            else ((today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1))
        )
        fact = _build_monthly(y, m)
        return ("monthly", fact) if fact else (None, None)

    fact = _deep_pick(window=True)
    if fact:
        return ("deep", fact)
    target = _monthly_target()
    if target:
        fact = _build_monthly(*target)
        if fact:
            return ("monthly", fact)
    return (None, None)


def _pick_least_recent_topic() -> str:
    best, best_ts = None, None
    for tid in STOCK_TOPIC_MAP:
        path = os.path.join(DATA_DIR, f"stock_{tid}_history.json")
        last = ""
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                posted = [h.get("timestamp", "") for h in data if h.get("status") == "posted"]
                last = max(posted) if posted else ""
        except Exception:
            last = ""
        key = last or "0000"
        if best is None or key < best_ts:
            best, best_ts = tid, key
    return best or "etf포트폴리오"


STOCK_TOPIC = os.environ.get("STOCK_TOPIC", "").strip()
if not STOCK_TOPIC or STOCK_TOPIC == "auto":
    STOCK_TOPIC = _pick_least_recent_topic()
    print(f"[자동 순환] 주식 소분류 선택: {STOCK_TOPIC}")
if STOCK_TOPIC not in STOCK_TOPIC_MAP:
    print(f"알 수 없는 STOCK_TOPIC: {STOCK_TOPIC!r} (가능: {list(STOCK_TOPIC_MAP)})")
    sys.exit(1)

HISTORY_PATH = os.path.join(DATA_DIR, f"stock_{STOCK_TOPIC}_history.json")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "stock_post.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("stock_post")


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


def _already_posted_today(history: list) -> bool:
    """같은 날·같은 소분류(stock_topic) 1회만 — posted/pending 모두 차단(ETF 4중복 방지)."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for h in history:
        if h.get("date") == today and h.get("status") in ("posted", "pending"):
            return True
    return False


def _reserve_today_slot(history: list, stock_topic: str, topic_name: str) -> list:
    """동시 실행·연속 재시도 시 중복 발행 방지 — pending 선기록."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    history = [h for h in history if not (h.get("date") == today and h.get("status") == "pending")]
    history.insert(
        0,
        {
            "date": today,
            "timestamp": datetime.now(KST).isoformat(),
            "stock_topic": stock_topic,
            "topic_name": topic_name,
            "status": "pending",
        },
    )
    return history


def _is_real_post_url(url: str | None) -> bool:
    if not url:
        return False
    if "Redirect=Write" in url or "PostWriteForm" in url:
        return False
    return bool(re.search(r"/\d{9,}", url))


def _append_internal_links(body: str, history: list) -> tuple:
    related = [h for h in history if h.get("status") == "posted" and h.get("post_url") and h.get("title")][:2]
    if not related:
        return body, []
    links_text = "\n\n함께 보면 좋은 글\n"
    for r in related:
        links_text += f"\n[가운데] {r['post_url']}"
    links_text += "\n"
    return body + links_text, ["함께 보면 좋은 글"]


def run():
    blog_category = STOCK_TOPICS[STOCK_TOPIC]["blog_category"]
    topic_name = STOCK_TOPICS[STOCK_TOPIC]["name"]
    run_slot = os.environ.get("RUN_SLOT", datetime.now(KST).strftime("%H"))
    logger.info("=" * 60)
    logger.info(
        f"주식 포스팅 시작 [{topic_name}] 카테고리='{blog_category}' (슬롯 {run_slot}): "
        f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}"
    )
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
    if _already_posted_today(history) and not force and not draft and not dry_run:
        logger.info(f"오늘 이미 [{topic_name}] 포스팅 완료 — 건너뜀")
        return

    # ── 공모주: 발행 여부·모드를 슬롯 선점 '전'에 결정 (스킵 시 pending 잔류 방지) ──
    ipo_fact = None
    if STOCK_TOPIC == "공모주캘린더":
        from generator.stock_collector import StockDataCollector

        ipo_list = StockDataCollector.get_ipo_calendar()
        ipo_mode, ipo_fact = _pick_ipo_content(
            ipo_list, history,
            force_mode=os.environ.get("IPO_MODE", "").strip().lower(),
            ignore_history=(force or draft or dry_run),
        )
        if not ipo_fact:
            logger.info("[공모주] 오늘 발행할 콘텐츠 없음(청약 임박 종목 없음·월간 캘린더 시기 아님) — 스킵")
            sys.exit(0)
        logger.info(f"[공모주] 모드={ipo_mode} 대상={ipo_fact.get('종목명') or ipo_fact.get('대상월')}")

    if not force and not draft and not dry_run:
        history = _reserve_today_slot(history, STOCK_TOPIC, topic_name)
        _save_history(history)
        logger.info(f"[{topic_name}] 오늘 슬롯 pending 선점 — 중복 실행 방지")

    from generator.stock_collector import StockDataCollector

    if STOCK_TOPIC == "종목분석":
        # 시장 이벤트 감지(2026-07-13 코스피 -8.95% 날 무명 상한가 종목만 다룬 사고 재발 방지)
        # 주말엔 금요일 종가가 재감지되므로 평일만. STOCK_PIN 수동 지정 시엔 종목분석 우선.
        market_snap = {}
        market_event = None
        try:
            market_snap = StockDataCollector.get_market_snapshot()
            if datetime.now(KST).weekday() < 5:
                market_event = StockDataCollector.detect_market_event(market_snap)
        except Exception as e:
            logger.warning(f"시장 지수 수집 실패(무시): {e}")

        if market_event and not os.environ.get("STOCK_PIN", "").strip():
            ups, downs, popular = [], [], []
            try:
                ups = StockDataCollector.get_today_upper_limit()
                downs = StockDataCollector.get_today_lower_limit()
                popular = StockDataCollector.get_kr_popular()
            except Exception as e:
                logger.warning(f"시장 이벤트 보조 데이터 수집 실패(무시): {e}")
            fact_data = {
                "이벤트": market_event["설명"],
                "시장지수(오늘)": market_snap,
                "상한가 종목 수": len(ups),
                "하한가 종목 수": len(downs),
                "인기검색상위": [
                    {"종목명": p.get("종목명"), "현재가": p.get("현재가"), "등락률": p.get("등락률")}
                    for p in popular[:8]
                ],
                "_market_event": True,
                "_event_direction": market_event["방향"],
                "_header_keyword": f"오늘 증시 {market_event['방향']} 정리",
            }
            side = downs if market_event["방향"] == "급락" else ups
            side_key = "하한가 종목" if market_event["방향"] == "급락" else "상한가 종목"
            if side:
                fact_data[side_key] = [s.get("종목명") for s in side[:8] if s.get("종목명")]
            logger.info(f"[시장 이벤트 모드] {market_event['설명']} — 개별 종목 대신 시장 브리핑")
        else:
            recent_names = {h.get("stock_name") for h in history[:20] if h.get("stock_name")}
            if os.environ.get("STOCK_PIN", "").strip():
                fact_data = StockDataCollector.pick_featured_stock(recent_names=recent_names, history_len=len(history))
            else:
                # 재료 예비조사(2026-07-13): 화제성 1위여도 검색으로 재료(스토리)가 확인 안 되면
                # 차순위 후보로 — '글감 없는 1위' 회피. 확인된 브리프는 본문 생성에 재사용(중복 조사 방지).
                from generator.stock_content import _research_material_brief

                fact_data = None
                candidates = StockDataCollector.pick_featured_candidates(recent_names=recent_names, limit=3)
                is_wknd = datetime.now(KST).weekday() >= 5
                for i, cand in enumerate(candidates):
                    brief = _research_material_brief(
                        cand["종목명"], GOOGLE_API_KEY,
                        reason=str(cand.get("선정사유", "")), weekend=is_wknd,
                    )
                    if brief:
                        cand["_material_brief"] = brief
                        fact_data = cand
                        if i > 0:
                            logger.info(f"[재료 예비조사] 상위 {i}개 후보 원인 미확인 → {cand['종목명']} 선정")
                        break
                if fact_data is None and candidates:
                    fact_data = candidates[0]
                    logger.info("[재료 예비조사] 전 후보 원인 미확인 — 화제성 1위 유지(정직 서술 모드)")
                if isinstance(fact_data, dict):
                    fact_data = StockDataCollector.enrich_stock_detail(fact_data)
            # 시장 맥락 주입(2026-07-13): 종목 글에도 오늘 지수 흐름을 한 문장 짚게 한다
            if isinstance(fact_data, dict) and market_snap and datetime.now(KST).weekday() < 5:
                fact_data["시장지수(오늘)"] = market_snap
    elif STOCK_TOPIC == "etf포트폴리오":
        from generator.etf_collector import EtfDataCollector

        force_content_type = os.environ.get("ETF_CONTENT_TYPE", "").strip()
        fact_data = EtfDataCollector.pick_etf_topic(history=history, force_content_type=force_content_type or None)
        # 전일 지수 급변 직후(07:00 크론 시점 스냅샷=직전 거래일 종가) — 급변 맥락 주입(2026-07-13)
        try:
            ev = StockDataCollector.detect_market_event()
            if ev and isinstance(fact_data, dict):
                fact_data["시장맥락(급변)"] = f"직전 거래일 {ev['설명']}"
        except Exception:
            pass
    elif STOCK_TOPIC == "공모주캘린더":
        fact_data = ipo_fact
    else:
        fact_data = StockDataCollector.collect(STOCK_TOPIC)
    if not fact_data:
        # 상한가 0건인 날·휴장 등 데이터가 없을 수 있음 → 빨간 실패 대신 조용히 건너뜀.
        # (force/draft로 강제 실행한 경우엔 원인 확인을 위해 실패로 종료)
        logger.warning(f"[{topic_name}] 팩트 데이터 없음 — 이번 슬롯 건너뜀 (skip)")
        sys.exit(1 if (force or draft) else 0)
    logger.info(f"팩트 데이터 수집 완료: {type(fact_data).__name__}")

    # ── 최근 뉴스·이슈 검색 보강 (종목분석·ETF 개별분석) ──
    # 기존 '최근뉴스'(국내 종목 상세 페이지 스크랩)와 같은 키로 병합 — 프롬프트 규칙 공유.
    if isinstance(fact_data, dict):
        news_queries: list[str] = []
        if STOCK_TOPIC == "종목분석" and fact_data.get("_market_event"):
            # 시장 브리핑: 급변 원인·개미 자금 흐름 보도를 근거로 확보
            news_queries = [f"코스피 {fact_data.get('_event_direction', '급변')}"]
        elif STOCK_TOPIC == "종목분석" and fact_data.get("종목명"):
            news_queries = [f"{fact_data['종목명']} 주가"]
            # 급변 종목은 목표가 조정·수급 보도가 핵심 근거 — 쿼리 추가(2026-07-13)
            if abs(StockDataCollector._parse_pct(
                    fact_data.get("등락률(%)", fact_data.get("등락률")))) >= 5:
                news_queries.append(f"{fact_data['종목명']} 목표주가")
        elif STOCK_TOPIC == "etf포트폴리오" and fact_data.get("_etf_content_type") in _INDIVIDUAL_ETF_TYPES:
            subject = fact_data.get("_etf_subject") or ""
            if subject:
                news_queries = [f"{subject} ETF"]
        if news_queries:
            try:
                extra_news = StockDataCollector.get_search_news(news_queries)
                if extra_news:
                    merged = list(fact_data.get("최근뉴스") or []) + extra_news
                    fact_data["최근뉴스"] = merged[:6]
            except Exception as e:
                logger.warning(f"뉴스 검색 보강 실패(무시): {e}")

    # ── 종목분석: 연간 매출·영업이익 추이 보강 (본문 인용 + [사진3] 재무 차트와 동일 소스) ──
    if STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict):
        fin_tickers: list[tuple[str, bool]] = []
        if fact_data.get("시장") == "미국" and fact_data.get("티커"):
            fin_tickers = [(fact_data["티커"], False)]
        elif fact_data.get("_code"):
            fin_tickers = [(f"{fact_data['_code']}.KS", True), (f"{fact_data['_code']}.KQ", True)]
        for yft, is_krw in fin_tickers:
            try:
                fin = StockDataCollector.get_financial_trend(yft, is_krw=is_krw)
            except Exception as e:
                logger.warning(f"재무 추이 보강 실패(무시): {e}")
                fin = {}
            if fin:
                fact_data.update(fin)
                fact_data["_fin_ticker"] = yft
                fact_data["_fin_is_krw"] = is_krw
                logger.info(f"재무 추이 보강: {yft}")
                break

    # ── 종목분석(국내): 증권사 리포트·DART 공시 보강 (2026-07-13 소스 확장) ──
    # 리포트 = 실명 목표가·투자의견(급변일 '실명 인용 우선' 규칙의 실데이터),
    # DART = 이벤트의 원본 소스(실적·유증·계약 공시). 둘 다 실패해도 글은 정상 진행.
    if (STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict)
            and not fact_data.get("_market_event") and fact_data.get("시장") == "국내"):
        if fact_data.get("종목명"):
            try:
                reports = StockDataCollector.get_analyst_reports(fact_data["종목명"])
                if reports:
                    fact_data["증권사리포트(최근)"] = reports
                    logger.info(f"증권사 리포트 {len(reports)}건 수집: {fact_data['종목명']}")
            except Exception as e:
                logger.warning(f"증권사 리포트 수집 실패(무시): {e}")
        if fact_data.get("_code"):
            dart = StockDataCollector.get_dart_disclosures(fact_data["_code"])
            if dart:
                fact_data["최근공시(DART)"] = dart

    from generator.stock_content import generate_stock_post

    post = generate_stock_post(STOCK_TOPIC, fact_data, GOOGLE_API_KEY)
    if not post:
        logger.error(f"[{topic_name}] 원고 생성 실패 — 종료")
        sys.exit(1)

    logger.info(f"제목: {post['title']}")
    logger.info("===== 본문 =====\n" + post.get("body", "")[:500] + "...\n===== 끝 =====")

    if dry_run:
        logger.info("[DRY_RUN] 포스팅 생략 — 원고 생성만 완료")
        return

    images: list[dict] = []
    keyword = topic_name
    if isinstance(fact_data, dict) and fact_data.get("_header_keyword"):
        keyword = fact_data["_header_keyword"]
    elif STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict) and fact_data.get("종목명"):
        keyword = f"{fact_data['종목명']} 분석"

    card_cat = _CARD_CATEGORY.get(STOCK_TOPIC, "주식etf")
    card_keyword = _card_hook_keyword(keyword, fact_data, STOCK_TOPIC)
    from generator.content import extract_summary_bullets
    bullets = extract_summary_bullets(post.get("summary_text", "")) or None
    header_path = None
    # HTML/CSS 인포그래픽 우선(gov/info와 동일 시스템), 실패 시 기존 PIL 카드 폴백
    try:
        from poster.infographic_html import create_infographic_via_html

        header_path = create_infographic_via_html(
            title=post["title"], keyword=card_keyword, category=card_cat, bullets=bullets
        )
        if header_path:
            logger.info(f"HTML 인포그래픽 생성 완료: {header_path}")
    except Exception as e:
        logger.warning(f"HTML 인포그래픽 실패 — PIL 폴백: {e}")

    if not header_path:
        try:
            from poster.naver_blog import create_health_header_card

            header_path = create_health_header_card(
                title=post["title"], keyword=card_keyword, category=card_cat, bullets=bullets
            )
        except Exception as e:
            logger.warning(f"PIL 헤더 카드 생성 실패 (무시): {e}")

    if header_path:
        images.append({"local_path": header_path, "url": "", "alt_text": keyword, "label": keyword})
        logger.info(f"주식 헤더 카드 생성: {header_path}")

    # ── 섹터·테마 비교: 헤더 다음 [사진2]에 비교 인포그래픽(월부 벤치마킹) ──
    if (STOCK_TOPIC == "etf포트폴리오" and isinstance(fact_data, dict)
            and fact_data.get("_etf_content_type") in ("sector_compare_kr", "sector_compare_us")):
        try:
            targets = fact_data.get("비교대상")
            group = fact_data.get("그룹명")
            if targets and group:
                from poster.infographic_html import create_comparison_infographic

                cmp_path = create_comparison_infographic(group, targets, category=card_cat)
                if cmp_path:
                    images.append({
                        "local_path": cmp_path, "url": "",
                        "alt_text": f"{group} ETF 비교", "label": f"{group} 비교",
                    })
                    logger.info(f"비교 인포그래픽 생성: {cmp_path}")
        except Exception as e:
            logger.warning(f"비교 인포그래픽 생성 실패(무시): {e}")

    if STOCK_TOPIC == "etf포트폴리오" and isinstance(fact_data, dict):
        try:
            chart_mode = fact_data.get("_chart_mode")
            tickers = fact_data.get("_chart_tickers") or []
            labels = fact_data.get("_chart_labels") or {}
            title = fact_data.get("_chart_title") or ""
            chart_path = None
            if chart_mode == "single" and tickers:
                from generator.stock_chart import generate_price_chart

                chart_path = generate_price_chart(tickers[0], label=labels.get(tickers[0], tickers[0]), period="6mo")
            elif chart_mode == "compare" and len(tickers) >= 2:
                from generator.stock_chart import generate_comparison_chart

                chart_path = generate_comparison_chart(tickers, labels=labels, period="3mo", title=title)
            if chart_path:
                images.append({
                    "local_path": chart_path, "url": "",
                    "alt_text": title or "ETF 차트",
                    "label": title or "차트",
                })
                logger.info(f"ETF 차트 생성: {chart_path}")

            # ── 네이버금융 공식 차트(국내 상장 ETF만, [사진3]) — 가격차트 성공 시에만 ──
            # 프롬프트(etf_has_naver)와 같은 조건: kr 개별분석 + _etf_subject(코드) + 배당팩트 없음
            if (chart_path and chart_mode == "single"
                    and fact_data.get("_etf_content_type") in ("kr_individual", "kr_overseas_individual")
                    and fact_data.get("_etf_subject")
                    and not fact_data.get("연도별배당(주당USD)")):
                from generator.stock_chart import get_naver_official_chart

                etf_name = labels.get(tickers[0], tickers[0]) if tickers else "ETF"
                nv_path = get_naver_official_chart(fact_data["_etf_subject"])
                if nv_path:
                    images.append({
                        "local_path": nv_path, "url": "",
                        "alt_text": f"{etf_name} 네이버금융 실시간 차트",
                        "label": f"{etf_name} 네이버금융 차트",
                    })
                    logger.info(f"네이버금융 공식 차트 다운로드(ETF): {nv_path}")

            # ── 배당 심층 차트 2장 ([사진3] 배당성장, [사진4] 재투자 비교) ──
            # ★가격차트([사진2])가 성공했을 때만 — 실패 시 이미지 인덱스가 밀려
            #   배당 차트가 [사진2] 자리(가격차트 해석 문장)에 들어가는 캡션 불일치 방지.
            # [사진3]은 배당차트 성공이 전제이므로 배당차트 실패 시 재투자 차트도 생략.
            # 배당 차트 2장은 배당·인컴형(dividend)에만 — growth/bond는 배당데이터가 있어도
            # 구조에 배당 섹션([사진3][사진4])이 없어 삽입 안 됨(생성 낭비 방지).
            _is_div_type = fact_data.get("_etf_type", "dividend") == "dividend"
            if chart_path and chart_mode == "single" and tickers and _is_div_type and fact_data.get("연도별배당(주당USD)"):
                from generator.stock_chart import (
                    generate_dividend_history_chart,
                    generate_total_return_chart,
                )

                div_label = labels.get(tickers[0], tickers[0])
                div_path = generate_dividend_history_chart(tickers[0], label=div_label)
                if div_path:
                    images.append({
                        "local_path": div_path, "url": "",
                        "alt_text": f"{div_label} 연도별 주당 배당금 추이",
                        "label": "연도별 주당 배당금",
                    })
                    logger.info(f"배당 이력 차트 생성: {div_path}")
                    tr_path = generate_total_return_chart(tickers[0], label=div_label)
                    if tr_path:
                        images.append({
                            "local_path": tr_path, "url": "",
                            "alt_text": f"{div_label} 배당 재투자 총수익 vs 주가 비교",
                            "label": "배당 재투자 vs 주가",
                        })
                        logger.info(f"총수익 비교 차트 생성: {tr_path}")
        except Exception as e:
            logger.warning(f"ETF 차트 생성 실패 (무시): {e}")

    if STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict) and fact_data.get("_market_event"):
        # 시장 브리핑: [사진2] = 코스피 6개월 추이 (개별 종목 차트 없음)
        try:
            from generator.stock_chart import generate_price_chart

            idx_chart = generate_price_chart("^KS11", label="코스피", period="6mo")
            if idx_chart:
                images.append({
                    "local_path": idx_chart, "url": "",
                    "alt_text": "코스피 최근 6개월 추이 차트",
                    "label": "코스피 6개월 추이",
                })
                logger.info(f"코스피 지수 차트 생성: {idx_chart}")
        except Exception as e:
            logger.warning(f"코스피 지수 차트 생성 실패 (무시): {e}")
    elif STOCK_TOPIC == "종목분석" and isinstance(fact_data, dict):
        try:
            from generator.stock_chart import generate_price_chart

            stock_name = fact_data.get("종목명", "")
            chart_path = None
            if fact_data.get("시장") == "미국" and fact_data.get("티커"):
                chart_path = generate_price_chart(fact_data["티커"], label=stock_name, period="6mo")
            elif fact_data.get("시장") == "국내" and fact_data.get("_code"):
                code = fact_data["_code"]
                for suffix in (".KS", ".KQ"):
                    chart_path = generate_price_chart(f"{code}{suffix}", label=stock_name, period="6mo")
                    if chart_path:
                        break
            if chart_path:
                images.append({
                    "local_path": chart_path, "url": "",
                    "alt_text": f"{stock_name} 6개월 가격 추이 차트",
                    "label": f"{stock_name} 가격 추이",
                })
                logger.info(f"종목 가격 차트 생성: {chart_path}")

            # ── 네이버금융 공식 실시간 차트(국내 종목만) — 가격차트 성공 시에만(인덱스 밀림 방지) ──
            # 프롬프트(_stock_photo_blocks)가 has_naver_chart를 같은 조건(시장=국내+_code)으로
            # 판단해 [사진N] 자리를 미리 잡아두므로, 여기서도 같은 조건으로 삽입해야 순서가 맞는다.
            if chart_path and fact_data.get("시장") == "국내" and fact_data.get("_code"):
                from generator.stock_chart import get_naver_official_chart

                naver_chart_path = get_naver_official_chart(fact_data["_code"])
                if naver_chart_path:
                    images.append({
                        "local_path": naver_chart_path, "url": "",
                        "alt_text": f"{stock_name} 네이버금융 실시간 차트",
                        "label": f"{stock_name} 네이버금융 차트",
                    })
                    logger.info(f"네이버금융 공식 차트 다운로드: {naver_chart_path}")

            # ── [사진N] 연간 실적 추이 차트 — 가격차트 성공 + 재무 팩트 존재 시에만(인덱스 밀림 방지) ──
            if chart_path and fact_data.get("_fin_ticker"):
                from generator.stock_chart import generate_financials_chart

                fin_path = generate_financials_chart(
                    fact_data["_fin_ticker"], label=stock_name,
                    is_krw=bool(fact_data.get("_fin_is_krw")),
                )
                if fin_path:
                    images.append({
                        "local_path": fin_path, "url": "",
                        "alt_text": f"{stock_name} 연간 매출·영업이익 추이 차트",
                        "label": f"{stock_name} 연간 실적 추이",
                    })
                    logger.info(f"재무 추이 차트 생성: {fin_path}")
        except Exception as e:
            logger.warning(f"종목 가격 차트 생성 실패 (무시): {e}")

    # 실제로 준비된 이미지 수보다 큰 [사진N] 마커는 게시 불가하므로 제거,
    # 같은 번호가 중복 출현하면(줄 단독이 아닌 문장 안 삽입 포함) 첫 등장만 남기고 제거.
    # (중복 마커가 남으면 같은 이미지 인덱스에 앵커가 2개 잡혀, 그중 하나가
    #  본문 내 동일 텍스트가 표 안에도 있는 경우 커서가 표로 잘못 들어가 삽입이
    #  통째로 실패하는 사례가 실제 라이브 발행에서 확인됨)
    img_count = len(images)
    if post.get("body"):
        seen_markers: set[str] = set()

        def _strip_marker(m: "re.Match[str]") -> str:
            n = m.group(1)
            if int(n) > img_count or n in seen_markers:
                return ""
            seen_markers.add(n)
            return m.group(0)

        cleaned = re.sub(r"\[사진(\d+)\]", _strip_marker, post["body"])
        # 문장 안 마커가 제거되면 "위 [사진3]은 ~" → "위 은 ~"처럼 조사가 남아 문장이 깨진다
        # (모델이 구조 지시문을 본문에 옮겨 적은 경우) — 자연스러운 표현으로 복구.
        cleaned = re.sub(r"위\s+[은는]\s+", "위 차트는 ", cleaned)
        if cleaned != post["body"]:
            logger.info("중복/초과 [사진N] 마커 정리됨")
            post["body"] = cleaned

    post["body"], extra_subs = _append_internal_links(post["body"], history)
    post["subheadings"] = post.get("subheadings", []) + extra_subs

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
            category=blog_category,
            faq_pairs=post.get("faq_pairs", []),
            summary_text=post.get("summary_text", ""),
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)

    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return

    post_url = result.get("post_url") if result else None
    is_posted = _is_real_post_url(post_url)

    # A/S 4필드(2026-07-31 — docs/NEXT_SESSION.md §1.A): 뒷날 공식 발표(실적·지수 등)
    # 수치와 나란히 붙일 후속(A/S) 글의 원료. 발행 성공분만 추출, 실패는 null 기록으로 무해.
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
        "stock_topic": STOCK_TOPIC,
        "topic_name": topic_name,
        "blog_category": blog_category,
        "title": post["title"],
        "tags": post["tags"],
        "status": "posted" if is_posted else "failed",
        "post_url": post_url if is_posted else None,
        "images_count": len(images),
        "images_inserted": result.get("images_inserted", 0) if result else 0,
        "has_table": bool(post.get("table_str")),
        "has_faq": bool(post.get("faq_str")),
        "stock_name": (fact_data.get("종목명") or fact_data.get("이벤트")) if isinstance(fact_data, dict) else None,
        "etf_content_type": fact_data.get("_etf_content_type") if isinstance(fact_data, dict) else None,
        "etf_subject": fact_data.get("_etf_subject") if isinstance(fact_data, dict) else None,
        "ipo_mode": fact_data.get("_ipo_mode") if isinstance(fact_data, dict) else None,
        "ipo_month": fact_data.get("_ipo_month") if isinstance(fact_data, dict) else None,
        **as_fields,  # claim / claim_numbers / verify_event / verify_date
    }

    history = _load_history()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    history = [h for h in history if not (h.get("date") == today and h.get("status") == "pending")]
    history.insert(0, entry)
    _save_history(history[:300])

    if is_posted:
        logger.info(f"[{topic_name}] 포스팅 완료: {post_url}")
    else:
        logger.error(f"[{topic_name}] 포스팅 실패 — URL: {post_url}")
        sys.exit(1)


if __name__ == "__main__":
    run()
