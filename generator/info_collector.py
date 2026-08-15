"""
info 카테고리 팩트 수집기.
봇 차단 없는 공식 API만 사용:
  1. Naver News 검색 API (최신 뉴스·공고 헤드라인)
  2. 공공데이터포털(data.go.kr) — 금융/세금/보험/부동산 구조화 데이터
  3. 금융감독원(fin.fss.or.kr) 금융상품 공시 API

수집된 팩트 블록은 Gemini 프롬프트 앞에 주입 → hallucination 최소화.
"""
import html
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("info_collector")

KST = timezone(timedelta(hours=9))
_TODAY = datetime.now(KST).strftime("%Y년 %m월 %d일")


# ──────────────────────────────────────────────
# 1. Naver News 검색 API
# ──────────────────────────────────────────────

def _fetch_naver_news(keyword: str, display: int = 5) -> list[dict]:
    """Naver 뉴스 검색 API로 최신 기사 헤드라인 수집.
    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 필요.
    없으면 빈 리스트 반환(하드 실패 없음).
    """
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    try:
        query = urllib.parse.quote(keyword)
        url = f"https://openapi.naver.com/v1/search/news.json?query={query}&display={display}&sort=date"
        req = urllib.request.Request(url, headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items", [])
        results = []
        for item in items:
            # <b>태그 제거 + &quot; 등 HTML 엔티티 복원 (그대로 두면 본문에 리터럴 노출)
            title = html.unescape(item.get("title", "").replace("<b>", "").replace("</b>", ""))
            desc = html.unescape(item.get("description", "").replace("<b>", "").replace("</b>", ""))
            pub_date = item.get("pubDate", "")
            link = item.get("originallink") or item.get("link") or ""
            results.append({"title": title, "desc": desc, "date": pub_date, "link": link})
        logger.info(f"Naver 뉴스 수집: {keyword!r} → {len(results)}건")
        return results
    except Exception as e:
        logger.warning(f"Naver 뉴스 수집 실패: {e}")
        return []


# ──────────────────────────────────────────────
# 2. 금융감독원 금융상품 공시 API
#    (예적금·대출 금리 공시, API키 불필요)
# ──────────────────────────────────────────────

def _fetch_fss_deposit_rates(top_n: int = 5) -> list[dict]:
    """금융감독원 예금 금리 공시 API (인증키 없이 사용 가능한 공개 엔드포인트).
    실패 시 빈 리스트.
    """
    FSS_KEY = os.getenv("FSS_API_KEY", "")
    if not FSS_KEY:
        return []
    try:
        url = (
            "https://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json"
            f"?auth={FSS_KEY}&topFinGrpNo=020000&pageNo=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        products = data.get("result", {}).get("baseList", [])[:top_n]
        results = []
        for p in products:
            results.append({
                "상품명": p.get("fin_prdt_nm", ""),
                "은행": p.get("kor_co_nm", ""),
                "최고금리": p.get("max_intr_rate", ""),
            })
        logger.info(f"FSS 예금 금리 수집: {len(results)}건")
        return results
    except Exception as e:
        logger.warning(f"FSS 금리 수집 실패: {e}")
        return []


def _fetch_fss_annuity_products(top_n: int = 5) -> list[dict]:
    """금융감독원 연금저축 상품 비교 공시 (finlife, 기존 FSS_API_KEY 재사용).
    보험 카테고리 '연금' 키워드 글에 실상품·수익률 팩트 제공(무근거 수치 방지).
    보험사(050000) 우선, 비면 은행(020000) 폴백. 실패 시 빈 리스트."""
    FSS_KEY = os.getenv("FSS_API_KEY", "")
    if not FSS_KEY:
        return []
    for grp in ("050000", "020000"):
        try:
            url = (
                "https://finlife.fss.or.kr/finlifeapi/annuitySavingProductsSearch.json"
                f"?auth={FSS_KEY}&topFinGrpNo={grp}&pageNo=1"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            products = data.get("result", {}).get("baseList", [])[:top_n]
            results = []
            for p in products:
                name = p.get("fin_prdt_nm", "")
                if not name:
                    continue
                results.append({
                    "회사": p.get("kor_co_nm", ""),
                    "상품명": name,
                    "연금종류": p.get("pnsn_kind_nm", ""),
                    "수익률(%)": p.get("avg_prft_rate", ""),
                })
            if results:
                logger.info(f"FSS 연금저축 상품 수집: {len(results)}건 (grp={grp})")
                return results
        except Exception as e:
            logger.warning(f"FSS 연금저축 수집 실패(grp={grp}): {e}")
    return []


# ──────────────────────────────────────────────
# 3. 공공데이터포털 — 카테고리별 API 매핑
# ──────────────────────────────────────────────

_PUBLIC_DATA_KEY = lambda: os.getenv("PUBLIC_DATA_KEY", "")


def _fetch_public_data(endpoint: str, params: dict) -> dict:
    """공공데이터포털 REST API 공통 호출. PUBLIC_DATA_KEY 필요."""
    key = _PUBLIC_DATA_KEY()
    if not key:
        return {}
    try:
        params["serviceKey"] = key
        params["_type"] = "json"
        qs = urllib.parse.urlencode(params, safe="+")
        url = f"{endpoint}?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"공공데이터포털 호출 실패 ({endpoint}): {e}")
        return {}


# ──────────────────────────────────────────────
# 4. 카테고리별 팩트 블록 생성
# ──────────────────────────────────────────────

def _build_fact_block(category: str, keyword: str) -> str:
    """카테고리 + 키워드로 팩트 블록 문자열 생성. Gemini 프롬프트 앞에 주입."""
    from generator.source_refs import INFO_OFFICIAL_SOURCES, GOV_OFFICIAL_SOURCES, format_sources_block

    lines: list[str] = [f"[실시간 팩트 데이터 — {_TODAY} 기준]"]

    # 공통: Naver 뉴스 최신 기사 (있을 경우)
    news = _fetch_naver_news(keyword, display=6)
    if news:
        lines.append(f"\n◆ 최신 뉴스 ({keyword})")
        for n in news:
            lines.append(f"  · {n['date'][:16]} | {n['title']}")
            if n.get("desc"):
                lines.append(f"    → {n['desc'][:80]}")

    # 카테고리별 추가 데이터
    if category == "금융재테크":
        rates = _fetch_fss_deposit_rates(top_n=3)
        if rates:
            lines.append("\n◆ 최신 예금 금리 공시 (금융감독원)")
            for r in rates:
                lines.append(f"  · {r['은행']} {r['상품명']}: 최고 {r['최고금리']}%")

    # 연금 관련 키워드(보험·금융재테크)엔 금감원 연금저축 공시 — 실상품·수익률 팩트
    if category in ("보험", "금융재테크") and "연금" in keyword:
        annuities = _fetch_fss_annuity_products(top_n=5)
        if annuities:
            lines.append("\n◆ 연금저축 상품 공시 (금융감독원 금융상품한눈에)")
            for a in annuities:
                rate = f" | 수익률 {a['수익률(%)']}%" if a.get("수익률(%)") else ""
                lines.append(f"  · {a['회사']} {a['상품명']} ({a['연금종류']}){rate}")

    if category == "세금절세":
        lines.append("\n◆ 계산 힌트: 연소득 구간별(3천·5천·7천만원) 공제·환급액 시뮬레이션, 한도·공제율은 팩트만 사용")

    if category == "부동산주거":
        lines.append("\n◆ 계산 힌트: 소득인정액·기준임대료·자기부담금(30%) 공식으로 구간별 지원액 시뮬레이션")

    if category == "gov":
        lines.append(format_sources_block(GOV_OFFICIAL_SOURCES))
    elif category in INFO_OFFICIAL_SOURCES:
        lines.append(format_sources_block(INFO_OFFICIAL_SOURCES[category]))

    if not lines[1:]:  # 뉴스/데이터 없으면 빈 블록 반환
        return ""

    lines.append(f"\n위 팩트를 바탕으로 2026년 기준 글을 작성하라.")
    return "\n".join(lines) + "\n\n"


# ──────────────────────────────────────────────
# 공개 인터페이스
# ──────────────────────────────────────────────

def collect_info_facts(category: str, keyword: str) -> str:
    """info 카테고리 팩트 수집 메인 함수.
    반환: Gemini 프롬프트 앞에 붙일 팩트 블록 문자열 (수집 실패 시 빈 문자열).
    """
    try:
        block = _build_fact_block(category, keyword)
        if block:
            logger.info(f"팩트 블록 생성 완료: {len(block)}자")
        return block
    except Exception as e:
        logger.warning(f"팩트 수집 전체 실패 (무시): {e}")
        return ""
