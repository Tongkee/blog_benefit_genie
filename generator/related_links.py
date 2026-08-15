"""네이버 정보성 글 내부링크(관련글) 선정 — 관련성·최신순·중복제외 (2026-07-24 개선).

배경(블로그 통계 분석): 방문당 조회 ≈ 1글(회유 약함) + 검색 자산 축적 필요. 기존 각 스크립트의
_append_internal_links는 `history[:2]`(가장 오래된 2개 '고정')라 ①관련성 없음 ②매번 같은 글만 링크
③최신 글 미노출. → 같은 블로그 카테고리 '최신' 글 우선 + 최대 3개 + 자기 자신 제외로 교체.

네이버 렌더: '함께 보면 좋은 글' 소제목 + 바 URL(가운데정렬) = 네이버가 썸네일·제목 링크카드로 렌더.
"""
from __future__ import annotations


import re


def _norm(u) -> str:
    return (u or "").split("?")[0].rstrip("/")


def _norm_cat(s) -> str:
    """카테고리명 정규화 — 구분자(쉼표·가운뎃점·공백) 차이를 흡수.

    ★2026-07-31: 카테고리를 쉼표에서 가운뎃점으로 리네임한 뒤에도 이력에는 옛 이름
    ('정부지원, 혜택')이 그대로 남아, 현재 이름('정부지원·혜택')과 문자열 비교가
    전부 실패했다. 그 결과 같은 카테고리 우선 로직이 죽고 **모든 글이 똑같은
    최신글 3개**를 링크하고 있었다(관련성 0). keyword.py와 같은 종류의 사고.
    """
    return re.sub(r"[\s,·・･、/]+", "", str(s or ""))


def related_links(history: list, blog_category: str | None = None,
                  current_url: str | None = None, current_title: str | None = None,
                  limit: int = 3, blog_id: str | None = None) -> list:
    """관련글 후보를 최신순·관련우선·중복/자기제외/동일블로그 한정으로 최대 limit개."""
    if not blog_id:
        from config import NAVER_BLOG_ID
        blog_id = NAVER_BLOG_ID
    
    cur_u = _norm(current_url)
    cand, seen = [], set()
    for h in reversed(history):  # 최신 발행 우선(기존은 오래된 것 고정)
        if h.get("status") != "posted" or not h.get("post_url") or not h.get("title"):
            continue
        u = _norm(h.get("post_url"))
        if not u or u == cur_u or u in seen:
            continue
        if blog_id and f"blog.naver.com/{blog_id.lower()}" not in u.lower():
            # 다른 블로그(이전 계정 등)의 글은 내부 링크 추천에서 제외
            continue
        if current_title and h.get("title") == current_title:
            continue
        seen.add(u)
        cand.append(h)
    want = _norm_cat(blog_category)
    same = [h for h in cand if want and _norm_cat(h.get("blog_category")) == want]
    same_urls = {_norm(h["post_url"]) for h in same}
    rest = [h for h in cand if _norm(h["post_url"]) not in same_urls]
    return (same + rest)[:limit]


def append_related(body: str, history: list, blog_category: str | None = None,
                   current_url: str | None = None, current_title: str | None = None,
                   limit: int = 3, blog_id: str | None = None) -> tuple:
    """(body + '함께 보면 좋은 글' 블록, 추가소제목) — 기존 _append_internal_links 대체용."""
    picked = related_links(history, blog_category, current_url, current_title, limit, blog_id=blog_id)
    if not picked:
        return body, []
    txt = "\n\n함께 보면 좋은 글\n"
    for r in picked:
        txt += f"\n[가운데] {r['post_url']}"
    return body + txt + "\n", ["함께 보면 좋은 글"]
