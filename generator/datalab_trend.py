"""
네이버 데이터랩 검색어트렌드 API — 실시간 키워드 트렌드 점수
타겟 독자층: 30대 여성 (gender=f, ages=["5"] = 30-34세)
12시간 캐시로 API 쿼터 절약 (1000/일 제한)
"""
import json
import logging
import os
import random
import time
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

_DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"
_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "datalab_cache.json"
)
_CACHE_TTL_HOURS = 12


def _load_cache() -> dict[str, float]:
    try:
        if not os.path.exists(_CACHE_PATH):
            return {}
        with open(_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        cached_at_str = data.get("cached_at", "")
        if not cached_at_str:
            return {}
        cached_at = datetime.fromisoformat(cached_at_str)
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=KST)
        age_hours = (datetime.now(KST) - cached_at).total_seconds() / 3600
        if age_hours >= _CACHE_TTL_HOURS:
            logger.info(f"데이터랩 캐시 만료 ({age_hours:.1f}h 경과) — 재수집")
            return {}
        return data.get("scores", {})
    except Exception as e:
        logger.warning(f"데이터랩 캐시 로드 실패: {e}")
        return {}


def _save_cache(scores: dict[str, float]):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        existing_path = _CACHE_PATH
        existing_scores: dict = {}
        if os.path.exists(existing_path):
            try:
                with open(existing_path, encoding="utf-8") as f:
                    existing_scores = json.load(f).get("scores", {})
            except Exception:
                pass
        existing_scores.update(scores)
        data = {
            "cached_at": datetime.now(KST).isoformat(),
            "scores": existing_scores,
        }
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"데이터랩 캐시 저장 실패: {e}")


def _query_batch(
    keywords: list[str],
    client_id: str,
    client_secret: str,
) -> dict[str, float]:
    """최대 5개 키워드 배치 조회 → {keyword: 7일평균점수}"""
    now = datetime.now(KST)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    keyword_groups = [
        {"groupName": kw, "keywords": [kw]}
        for kw in keywords[:5]
    ]

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": keyword_groups,
        "device": "mo",
        "gender": "f",
        "ages": ["5"],  # 30-34세
    }

    try:
        resp = requests.post(
            _DATALAB_URL,
            json=body,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()

        scores: dict[str, float] = {}
        for group_result in result.get("results", []):
            group_name = group_result.get("title", "")
            data_points = group_result.get("data", [])
            if data_points:
                avg = sum(d.get("ratio", 0) for d in data_points) / len(data_points)
                scores[group_name] = round(avg, 2)
            else:
                scores[group_name] = 0.0
        return scores
    except Exception as e:
        logger.warning(f"데이터랩 API 배치 오류 ({keywords}): {e}")
        return {}


def get_keyword_trends(keywords: list[str]) -> dict[str, float]:
    """
    키워드 목록의 트렌드 점수 반환 (30대 여성, 7일 평균).
    캐시된 점수 우선 사용, 없는 키워드만 API 조회.
    Returns: {keyword: score} — score 높을수록 검색량 많음 (0~100)
    """
    if not keywords:
        return {}

    # 환경 변수 직접 로드 (순환 import 방지)
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        logger.debug("NAVER_CLIENT_ID/SECRET 미설정 — 데이터랩 스킵")
        return {}

    cache = _load_cache()
    uncached = [kw for kw in keywords if kw not in cache]

    if uncached:
        logger.info(f"데이터랩 API 조회: {len(uncached)}개 키워드 (30대 여성)")
        new_scores: dict[str, float] = {}
        for i in range(0, len(uncached), 5):
            batch = uncached[i : i + 5]
            batch_scores = _query_batch(batch, client_id, client_secret)
            new_scores.update(batch_scores)
            if i + 5 < len(uncached):
                time.sleep(0.3)  # rate limit 방지

        if new_scores:
            _save_cache(new_scores)
            cache.update(new_scores)
            logger.info(
                f"데이터랩 신규 점수: "
                + ", ".join(f"{k}={v}" for k, v in sorted(new_scores.items(), key=lambda x: -x[1])[:5])
            )

    return {kw: cache.get(kw, 0.0) for kw in keywords}


def pick_trending_keyword(keywords: list[str], top_n: int = 3) -> str | None:
    """
    키워드 목록에서 트렌딩 상위 top_n 중 랜덤 1개 반환.
    API 불가 또는 모든 점수가 0이면 None 반환 (caller가 random fallback 처리).
    """
    if not keywords:
        return None

    scores = get_keyword_trends(keywords[:20])  # 쿼터 절약: 최대 20개만 조회
    if not scores or all(v == 0.0 for v in scores.values()):
        logger.debug("데이터랩 점수 없음 — 랜덤 fallback")
        return None

    sorted_kws = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    top = sorted_kws[:top_n]
    chosen = random.choice(top)
    logger.info(
        f"[DataLab 트렌딩] 선택: {chosen!r} (점수 {scores.get(chosen, 0):.1f}) "
        f"| TOP{top_n}: {[(k, scores.get(k, 0)) for k in top]}"
    )
    return chosen
