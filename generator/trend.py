"""
주간 트렌딩 주제 수집 및 캐싱
- 매주 월요일 Google News RSS에서 수집 → data/trend_cache.json에 7일간 캐시
- 블로그 키워드에 트렌딩 요소를 자연스럽게 연결하는 각도 제안
"""
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "trend_cache.json"
)
_CACHE_TTL_DAYS = 1

# 생활/살림 관련 키워드 필터 — 이 단어 포함 뉴스 우선
_LIFE_KEYWORDS = re.compile(
    r"생활|절약|살림|집값|부동산|전세|월세|물가|장보기|마트|육아|요리|음식|건강|다이어트|"
    r"날씨|계절|이사|인테리어|가전|가구|결혼|신혼|청소|정리|수납"
)
_SKIP = re.compile(
    r"북한|무기|전쟁|핵|테러|사망|사고|화재|범죄|살인|마약|자살|부고|피해|사건|정치|선거|"
    r"트럼프|바이든|푸틴|시진핑|네타냐후|총리|의원|여당|야당|검찰|기소|법원|판결|외교|국방|"
    r"대통령|국회|정당|총선|대선|시장|도지사|장관|수석|참모|의혹|비리|부패|탄핵"
)


def _fetch_google_news(limit: int = 20) -> list[str]:
    """Google News RSS에서 트렌딩 헤드라인 수집"""
    try:
        r = requests.get(
            "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        root = ElementTree.fromstring(r.content)
        topics: list[str] = []
        life_topics: list[str] = []

        for item in root.findall(".//item/title"):
            title = (item.text or "").strip()
            if not title or _SKIP.search(title):
                continue
            title = re.sub(r"\s+-\s+\S+$", "", title).strip()
            if len(title) < 5:
                continue
            if _LIFE_KEYWORDS.search(title):
                life_topics.append(title)
            else:
                topics.append(title)

        # 생활 관련 뉴스 우선 배치
        combined = life_topics + topics
        return combined[:limit]
    except Exception as e:
        logger.warning(f"Google News RSS 수집 실패: {e}")
        return []


def _load_cache() -> dict | None:
    """캐시 파일 로드. 없거나 만료된 경우 None 반환."""
    try:
        if not os.path.exists(_CACHE_PATH):
            return None
        with open(_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
        age_days = (datetime.now(KST) - cached_at).days
        if age_days >= _CACHE_TTL_DAYS:
            logger.info(f"트렌드 캐시 만료 ({age_days}일 경과)")
            return None
        return cache
    except Exception as e:
        logger.warning(f"트렌드 캐시 로드 실패: {e}")
        return None


def _save_cache(trends: list[str]):
    """트렌드 목록을 캐시 파일에 저장"""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        cache = {
            "cached_at": datetime.now(KST).isoformat(),
            "trends": trends,
        }
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"트렌드 캐시 저장 ({len(trends)}개)")
    except Exception as e:
        logger.warning(f"트렌드 캐시 저장 실패: {e}")


def get_weekly_trends() -> list[str]:
    """
    7일 캐시된 트렌딩 주제 반환.
    캐시 없거나 만료 시 Google News RSS에서 새로 수집.
    """
    cache = _load_cache()
    if cache and cache.get("trends"):
        trends = cache["trends"]
        logger.info(f"트렌드 캐시 사용 ({len(trends)}개, {cache.get('cached_at', '')[:10]})")
        return trends

    logger.info("트렌드 새로 수집 중...")
    trends = _fetch_google_news(limit=20)
    if trends:
        _save_cache(trends)
    return trends


# 카테고리별 트렌드 연결 힌트 매핑
_TREND_CONNECTORS: dict[str, list[str]] = {
    "신혼살림기초": [
        "요즘 신혼부부들이 많이 찾는",
        "물가 오른 요즘 알뜰하게 준비하는",
        "최근 뜨는 신혼 트렌드",
    ],
    "청소정리": [
        "요즘 날씨에 특히 중요한",
        "최근 유행하는 청소법",
        "시간 아끼는 요즘 트렌드",
    ],
    "요리식비": [
        "물가 오른 요즘 식비 절약",
        "요즘 유행하는 간단 요리",
        "SNS에서 화제인 레시피",
    ],
    "절약재테크": [
        "물가 상승 시대 절약법",
        "요즘 핫한 절약 트렌드",
        "최근 화제된 생활비 절약",
    ],
    "인테리어": [
        "요즘 뜨는 인테리어 트렌드",
        "최근 유행하는 집 꾸미기",
        "SNS에서 핫한 인테리어",
    ],
    "쇼핑정보": [
        "요즘 핫한 추천 제품",
        "최근 품절 대란 템",
        "SNS에서 화제인 살림템",
    ],
}


def suggest_trend_angle(keyword: str, trends: list[str], category: str = "") -> str:
    """
    키워드에 트렌딩 요소를 연결하는 각도 제안.
    글 생성 시 Gemini에게 힌트로 제공할 짧은 문자열 반환.
    트렌드가 없거나 연결이 어색하면 빈 문자열 반환.
    """
    if not trends:
        return ""

    # 생활/살림 관련 트렌드만 필터
    life_trends = [t for t in trends if _LIFE_KEYWORDS.search(t)][:3]
    if not life_trends:
        life_trends = trends[:2]

    connectors = _TREND_CONNECTORS.get(category, ["요즘 화제인"])
    connector = connectors[0] if connectors else "요즘 화제인"

    trend_summary = ", ".join(life_trends[:2])
    angle = f"{connector} '{keyword}' — 관련 트렌드: {trend_summary}"
    logger.info(f"트렌드 각도 제안: {angle}")
    return angle
