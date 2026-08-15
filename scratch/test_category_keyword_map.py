# -*- coding: utf-8 -*-
"""블로그 카테고리 ↔ 키워드 풀 매핑 회귀 테스트 (오프라인).

2026-07-31 실사고 재발 방지:
  카테고리명을 쉼표→가운뎃점으로 리네임(e47cbb3)했는데 keyword.py의 매핑 표만
  옛 이름을 키로 갖고 있었다. 조회가 빗나가면 조용히 '청소정리'(살림 청소 풀)로
  폴백해서, 고CPC 4개 카테고리가 통째로 살림 키워드를 뽑았다.
  → '베란다 청소, 최대 3,600만원 경비 처리로 세금 아끼는 법' 등 없는 제도를
    지어낸 글 4건이 실제로 발행됐다.

실행: python scratch/test_category_keyword_map.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator.keyword import (CATEGORIES, _SEASON,  # noqa: E402
                               blog_category_keyword_cats)

# 각 파이프라인이 실제로 넘기는 값 (scripts/*.py의 BLOG_CATEGORY / INFO_CAT_MAP)
LIVE = {
    "금융·재테크": "금융재테크",
    "세금·절세": "세금절세",
    "보험": "보험",
    "부동산·주거": "부동산주거",
    "정부지원·혜택": "정부지원혜택",
}


def test_live_categories_map_to_own_pool():
    """운영 중인 5개 카테고리는 반드시 자기 이름의 키워드 풀로 간다."""
    for blog_cat, expected in LIVE.items():
        got = blog_category_keyword_cats(blog_cat)
        assert got == [expected], f"{blog_cat} -> {got} (기대: [{expected}])"


def test_no_silent_fallback_to_cleaning_pool():
    """★핵심: 미등록 이름이 살림 풀로 조용히 떨어지면 안 된다 — 예외로 끊는다."""
    for bad in ["없는카테고리", "금융/재테크x", ""]:
        try:
            got = blog_category_keyword_cats(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r}가 예외 없이 {got}로 매핑됨 — 조용한 폴백 부활")


def test_separator_variants_all_resolve():
    """쉼표·가운뎃점·공백 차이를 흡수해야 한다(리네임 재발 대비)."""
    for a, b in [("금융·재테크", "금융, 재테크"), ("세금·절세", "세금,절세"),
                 ("부동산·주거", "부동산, 주거"), ("정부지원·혜택", "정부지원, 혜택")]:
        assert blog_category_keyword_cats(a) == blog_category_keyword_cats(b), f"{a} != {b}"


def test_no_household_keywords_in_highcpc_pools():
    """고CPC 풀에 살림·청소 키워드가 섞여 있으면 안 된다."""
    household = set(CATEGORIES["청소정리"]["keywords"])
    for v in _SEASON.values():
        household |= set(v)
    for blog_cat, cat_id in LIVE.items():
        pool = set(CATEGORIES[cat_id]["keywords"])
        overlap = pool & household
        assert not overlap, f"{blog_cat} 풀에 살림 키워드 혼입: {sorted(overlap)}"


def test_season_keywords_only_reach_cleaning_category():
    """시즌 키워드(난방비·대청소·곰팡이)는 살림 트랙 전용이다."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "generator", "keyword.py"), encoding="utf-8").read()
    # _SEASON을 붙이는 지점은 '청소정리' 조건 안에만 있어야 한다
    for line in src.splitlines():
        if "_SEASON.get(month" in line and "cat_pool = cat_pool +" in line:
            assert "청소정리" in src[max(0, src.find(line) - 200):src.find(line)], \
                "시즌 키워드가 카테고리 조건 없이 주입되고 있음"


def test_cross_track_dedup_sees_all_categories():
    """중복 검사는 블로그 단위여야 한다 — 카테고리별 파일만 보면 교차 중복을 놓친다.

    ★삭제분(status='deleted')은 집계에서 빠지는 게 맞다(2026-07-31 33건 삭제).
    그래서 특정 키워드를 하드코딩하지 않고, 여러 트랙의 이력이 실제로 합쳐지는지를 본다.
    """
    import glob
    import json
    import os

    from generator.keyword import recent_keywords_all_tracks
    kws = recent_keywords_all_tracks(days=3650)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    seen_files = 0
    for pat in ("data/info_*_history.json", "data/gov_history.json"):
        for path in glob.glob(os.path.join(root, pat)):
            rows = json.load(open(path, encoding="utf-8"))
            posted = {r.get("keyword") for r in rows
                      if isinstance(r, dict) and r.get("status") == "posted" and r.get("keyword")}
            if not posted:
                continue
            seen_files += 1
            missing = posted - kws
            assert not missing, f"{os.path.basename(path)}의 발행분이 누락: {sorted(missing)[:3]}"
    assert seen_files >= 3, f"트랙 이력이 {seen_files}개만 잡힘 — 합산이 안 되고 있다"
    assert len(kws) > 40, f"전 트랙 이력이 제대로 안 모임({len(kws)}개)"


def test_pool_capacity_covers_30_days():
    """하루 1건×30일을 버티려면 카테고리당 풀이 30개 이상이어야 한다.

    2026-07-31 실사고: 풀 18~20개로 하루 4슬롯을 돌려 5일이면 소진됐고,
    소진되면 `fresh = cat_pool` 폴백이 30일 중복 게이트를 스스로 꺼버렸다.
    """
    for blog_cat, cat_id in LIVE.items():
        n = len(CATEGORIES[cat_id]["keywords"])
        assert n >= 30, f"{blog_cat} 풀 {n}개 — 30일을 못 버틴다(30개 이상 필요)"


def test_pool_exhaustion_fails_closed():
    """풀이 소진되면 재사용으로 열지 말고 예외로 끊어야 한다."""
    from generator.keyword import KeywordPoolExhausted, pick_keyword_for_blog_category
    everything = set(CATEGORIES["보험"]["keywords"])
    try:
        pick_keyword_for_blog_category("보험", exclude=everything)
    except KeywordPoolExhausted:
        return
    raise AssertionError("풀 소진인데 예외 없이 키워드를 반환했다(중복 발행 위험)")


def test_discontinued_never_picked():
    """종료·폐지 제도는 키워드로 뽑히면 안 된다."""
    from generator.official_facts import discontinued_names
    from generator.keyword import pick_keyword_for_blog_category
    dead = discontinued_names()
    assert dead, "종료 제도 목록이 비어 있다"
    for blog_cat in LIVE:
        for _ in range(5):
            k = pick_keyword_for_blog_category(blog_cat)["keyword"]
            assert not any(d in k for d in dead), f"{blog_cat}에서 종료 제도 키워드 선정: {k}"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[OK  ] {name}")
            except AssertionError as e:
                fails += 1
                print(f"[FAIL] {name}: {e}")
    print("PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
