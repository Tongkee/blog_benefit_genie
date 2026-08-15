# -*- coding: utf-8 -*-
"""테크 뉴스 주제 동일성 판정 (2026-07-31 신설).

배경 — 왜 필요한가:
  '갤럭시 Z 폴드8' 글이 2주에 8건 나갔다(7/15·18·19·23·25·27·31×2). 중복 방지가
  약했던 게 아니라 **작동한 적이 없었다**. scripts/tech_post.py의 `_topic_overused`가
  *뉴스 헤드라인*을 *과거 블로그 제목*과 토큰 완전일치로 비교하는데,

    ① 어휘 공간이 다르다 — 언론사는 "삼성 폴더블 사전예약서", 블로그는 "갤럭시 Z 폴드8".
    ② 한국어 형태론을 못 넘는다 — `갤럭시Z폴드8`은 1토큰, `갤럭시`+`폴드8`은 2토큰이라
       불일치. 조사도 마찬가지(`가격` ≠ `가격은`).

  실측 재현 결과 7/31 두 글, 7/25 vs 7/23 두 글 모두 토큰 교집합이 **공집합**이었다.

해법: 표면형이 아니라 **엔티티**로 비교한다. 공백·조사·특수문자를 지운 정규화 문자열에
별칭(alias)을 substring 매칭해 안정적인 토픽 키를 뽑는다.
"""
import re

# 같은 대상을 가리키는 표기 변형 → 대표 키
# (정규화 후 substring 매칭이므로 띄어쓰기·조사는 신경 쓰지 않아도 된다)
ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "갤럭시폴더블": ("갤럭시z폴드", "갤럭시z플립", "갤럭시폴드", "갤럭시플립",
                "폴드8", "플립8", "갤럭시z8", "삼성폴더블", "폴더블신제품"),
    "갤럭시s": ("갤럭시s26", "갤럭시s25", "갤럭시울트라"),
    "갤럭시워치": ("갤럭시워치", "갤워치"),
    "아이폰": ("아이폰18", "아이폰17", "아이폰에어", "iphone"),
    "애플워치": ("애플워치", "applewatch"),
    "에어팟": ("에어팟", "airpods"),
    "픽셀": ("픽셀스마트폰", "구글픽셀"),
    "맥북": ("맥북", "macbook"),
    "그래픽카드": ("rtx", "지포스", "그래픽카드"),
    "로봇청소기": ("로봇청소기", "로보락"),
    "제습기": ("제습기",),
    "공기청정기": ("공기청정기",),
    "tv": ("삼성tv", "oled tv", "qled"),
    "전기차": ("아이오닉", "기아ev", "테슬라", "전기차"),
    "챗gpt": ("챗gpt", "chatgpt", "gpt"),
    "제미나이": ("제미나이", "gemini"),
}


def normalize(s: str) -> str:
    """공백·조사·특수문자 제거 + 소문자화. 형태론 차이를 흡수한다."""
    return re.sub(r"[^가-힣A-Za-z0-9]", "", str(s or "")).lower()


def topic_key(*parts: str) -> str:
    """헤드라인·제목·시드에서 안정적인 주제 키를 만든다.

    엔티티가 잡히면 그 대표 키를, 못 잡으면 정규화 문자열의 앞부분을 쓴다
    (후자는 완전한 동일성 판정은 못 하지만 최소한 표면형 변형에는 견딘다).
    """
    blob = normalize(" ".join(p for p in parts if p))
    for key, aliases in ENTITY_ALIASES.items():
        if any(a in blob for a in aliases):
            return key
    # 폴백: 의미 있는 한글 명사 덩어리 하나
    m = re.findall(r"[가-힣]{2,}", " ".join(p for p in parts if p))
    return normalize(m[0]) if m else (blob[:12] or "misc")


def same_topic(a_parts: tuple, b_parts: tuple) -> bool:
    """두 글이 같은 주제인가."""
    return topic_key(*a_parts) == topic_key(*b_parts)


def count_recent(topic: str, history: list, days: int, today: str) -> int:
    """최근 N일간 같은 topic_key로 발행된 건수."""
    from datetime import date, timedelta
    try:
        cut = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    except Exception:
        return 0
    n = 0
    for h in history:
        if not isinstance(h, dict) or h.get("status") != "posted":
            continue
        if str(h.get("date") or "") < cut:
            continue
        k = h.get("topic_key") or topic_key(h.get("title") or "", h.get("seed") or "")
        if k == topic:
            n += 1
    return n
