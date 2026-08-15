# -*- coding: utf-8 -*-
"""2026-07-04 포스팅 5종 버그 회귀 테스트."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def test_title_emphasis_strip_parser():
    from generator.content import _parse_response

    raw = """TITLE: [[AI 거품론]] 속 SK하이닉스 분석
TAGS: a,b,c
---
[사진1]

본문 [[핵심]] 테스트.
"""
    parsed = _parse_response(raw)
    assert parsed
    assert "[[" not in parsed["title"]
    assert "AI 거품론" in parsed["title"]
    assert "[[핵심]]" in parsed["body"]  # 본문은 포스터 볼드용 유지
    print("OK title_emphasis_strip_parser")


def test_body_emphasis_strip_overflow():
    from generator.quality import strip_body_emphasis_markers

    body = " ".join(f"[[m{i}]]" for i in range(15))
    cleaned = strip_body_emphasis_markers(body, max_markers=10)
    assert "[[" not in cleaned
    print("OK body_emphasis_strip_overflow")


def test_sanitize_anchor():
    from generator.quality import sanitize_anchor_text

    assert sanitize_anchor_text("[[세금]] 혜택") == "세금 혜택"
    assert sanitize_anchor_text("[가운데] http://x") == "http://x"
    print("OK sanitize_anchor")


def test_info_stale_year():
    from generator.quality import validate_info_dates

    bad = validate_info_dates("2024년 6월 1일 기준 재산세", "")
    assert bad
    ok = validate_info_dates("2026년 재산세 | 0.1~0.4% 세율", "")
    assert not ok
    print("OK info_stale_year")


def test_ipo_today_deadline():
    from generator.quality import validate_ipo_date_claims

    assert validate_ipo_date_claims("오늘(3일) 마감되는 청약")
    assert not validate_ipo_date_claims("청약일 7월 2일~7월 3일")
    print("OK ipo_today_deadline")


def test_stock_dedup_pending():
    from datetime import datetime, timezone, timedelta
    from scripts import stock_post

    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    hist = [{"date": today, "status": "pending"}]
    assert stock_post._already_posted_today(hist)
    hist2 = [{"date": today, "status": "posted"}]
    assert stock_post._already_posted_today(hist2)
    hist3 = [{"date": "2020-01-01", "status": "posted"}]
    assert not stock_post._already_posted_today(hist3)
    print("OK stock_dedup_pending")


def test_chart_anchor_phrases_in_poster():
    path = os.path.join(ROOT, "poster", "naver_blog.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "_move_cursor_for_image" in src
    assert "_CHART_ANCHOR_PHRASES" in src
    assert "sanitize_anchor_text" in src
    print("OK chart_anchor_phrases_in_poster")


if __name__ == "__main__":
    test_title_emphasis_strip_parser()
    test_body_emphasis_strip_overflow()
    test_sanitize_anchor()
    test_info_stale_year()
    test_ipo_today_deadline()
    test_stock_dedup_pending()
    test_chart_anchor_phrases_in_poster()
    print("\nAll post bugfix tests passed.")
