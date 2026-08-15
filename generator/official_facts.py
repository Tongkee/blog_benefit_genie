"""법정 고시값 정적 DB 주입기 (2026-07-19 신설, 사용자 승인 — 오류 원천 차단 설계).

배경: 2026-07-19 점검에서 오류 3건(청약 가점·중위소득·세율 구간)의 공통 원인이
'모델이 학습 기억으로 고시값을 추정'하는 것으로 확정. 검증기(LLM)도 같은 한계를 보임.
→ 해결은 프롬프트가 아니라 구조: 검증된 고시값을 생성 시 항상 팩트로 주입해
   기억에 의존할 일 자체를 없앤다.

- DB: data/official_facts_2026.json (검증값만 수록, verified/next_review 메타 포함)
- 주입: lookup_block(keyword, extra_terms) → 트리거 매칭 항목을 팩트 블록 문자열로
- 갱신: next_review 경과 항목은 quality_audit가 주간 이슈에 리마인드
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("official_facts")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "official_facts_2026.json")
KST = timezone(timedelta(hours=9))


def _load_raw() -> dict:
    try:
        return json.load(open(_DB_PATH, encoding="utf-8"))
    except Exception as e:
        logger.warning(f"고시값 DB 로드 실패: {e}")
        return {}


def _load() -> dict:
    """트리거 매칭용 항목만 — 메타·종료목록 제외."""
    db = _load_raw()
    return {k: v for k, v in db.items() if not k.startswith("_")}


def lookup_block(keyword: str, extra_terms: str = "") -> str:
    """키워드(+카테고리 등 부가 문자열)에 트리거가 걸리는 고시값을 팩트 블록으로 반환.
    매칭 없으면 빈 문자열."""
    text = f"{keyword} {extra_terms}"
    hits = []
    for name, entry in _load().items():
        if any(t in text for t in entry.get("triggers", [])):
            lines = [f"■ {k}: {v}" for k, v in entry.get("facts", {}).items()]
            src = entry.get("source", "")
            hits.append(f"[{name}] (출처: {src}, 검증 {entry.get('verified', '')})\n" + "\n".join(lines))
    block = ""
    if hits:
        logger.info(f"고시값 DB 주입: {len(hits)}개 항목 매칭 ({keyword!r})")
        block = ("[법정 고시값 — 아래 값은 공식 검증본이다. 관련 수치는 반드시 이 값을 문자 그대로 사용하고, "
                 "여기 없는 고시값은 학습 기억으로 추정하지 마라]\n" + "\n\n".join(hits) + "\n\n")
    # ★종료·폐지 제도는 트리거와 무관하게 항상 주입한다(2026-07-31).
    # 전수 점검에서 최대 오류 유형이 '이미 끝난 제도를 현행처럼 안내'였다.
    # 청년희망적금·신혼부부 취득세 감면처럼 신청 방법·취급 은행까지 안내한 글이 나왔다.
    return block + discontinued_block()


def discontinued_block() -> str:
    """종료·폐지 제도 경고 블록 — 항상 주입."""
    d = _load_raw().get("_discontinued") or {}
    items = d.get("items") or {}
    if not items:
        return ""
    lines = [f"■ {k}: {v}" for k, v in items.items()]
    return ("[★종료·폐지 제도 — 아래는 2026년 현재 신규 신청·가입이 불가능하다. "
            "현행 제도처럼 서술하거나 신청 방법·취급 기관을 안내하지 마라. "
            "글의 주제로 삼는 것도 금지. 언급이 꼭 필요하면 '종료된 제도'임을 명시하라]\n"
            + "\n".join(lines) + "\n\n")


def discontinued_names() -> list[str]:
    """종료·폐지 제도명 목록 — 키워드 선정에서 배제하는 데 쓴다."""
    return list((_load_raw().get("_discontinued") or {}).get("items") or {})


def terminated_mentions(text: str) -> list[str]:
    """본문이 종료 제도를 '현행처럼' 언급하는지 검사 — 발행 게이트용.

    제도명이 나오면서 '종료/폐지/일몰/불가' 같은 단서가 근처에 없으면 위반으로 본다.
    """
    d = _load_raw().get("_discontinued") or {}
    bad = []
    this_year = datetime.now(KST).year
    for name, desc in (d.get("items") or {}).items():
        idx = text.find(name)
        if idx < 0:
            continue
        window = text[max(0, idx - 120): idx + 200]
        if any(w in window for w in ("종료", "폐지", "일몰", "신규 가입 불가", "가입 불가",
                                     "신청 불가", "시행 전", "유예", "더 이상", "시행 예정")):
            continue
        # ★미래 시행 제도(2026-07-31 밤): '가상자산 과세는 2027년 1월 1일 시행'처럼
        # 항목 설명의 **미래 연도**를 창에 명시했으면 올바른 맥락으로 본다.
        # 과거 연도·올해는 허용하지 않는다 — '2025년부터 시행되며 2026년 5월 첫 신고'
        # 같은 오류 서술(실사고 224347483368)은 여전히 차단된다.
        fut_years = [y for y in re.findall(r"(20\d{2})", str(desc)) if int(y) > this_year]
        if any(y in window for y in fut_years):
            continue
        bad.append(name)
    return bad


def overdue_reviews() -> list[str]:
    """재검토 기한이 지난 항목 이름 목록 — 주간 품질 감사가 갱신 리마인드에 사용."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [name for name, e in _load().items()
            if e.get("next_review", "9999-12-31") < today]
