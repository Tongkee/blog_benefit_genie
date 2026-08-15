"""Unit tests for stock posting bug fixes (category match, footer prompt)."""
import os
import re
import sys

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _norm_category_label(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _pick_category_label(available: list[str], category_name: str) -> str | None:
    if not category_name or not available:
        return None
    target = _norm_category_label(category_name)
    cleaned = [a.strip() for a in available if a and a.strip()]
    for label in cleaned:
        if _norm_category_label(label) == target:
            return label
    low = category_name.strip().lower()
    for label in cleaned:
        if label.strip().lower() == low:
            return label
    for label in cleaned:
        ln = label.strip()
        if category_name in ln or ln in category_name:
            return label
    return None


def test_category_pick():
    opts = ["정부지원, 혜택", "건강, 다이어트", "주식", "ETF", "주식분석", "공모주"]
    assert _pick_category_label(opts, "ETF") == "ETF"
    assert _pick_category_label(opts, "주식분석") == "주식분석"
    assert _pick_category_label(opts, "공모주") == "공모주"
    assert _pick_category_label(["정부지원, 혜택", "ETF"], "ETF") == "ETF"
    assert _pick_category_label(opts, "없는카테고리") is None
    print("OK category_pick")


def test_stock_content_no_coupang_footer():
    path = os.path.join(ROOT, "generator", "stock_content.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "footer = \"이 리뷰가" not in src
    assert "마지막 줄 '이 리뷰가" not in src
    assert "공식 자료·증권사" in src
    print("OK stock_content_no_coupang_footer")


def test_header_card_no_truncation_in_source():
    path = os.path.join(ROOT, "poster", "naver_blog.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "_STOCK_CARD_CATS" in src
    assert "category not in _STOCK_CARD_CATS" in src
    print("OK header_card_stock_skip_truncation")


def test_divider_skip_in_source():
    path = os.path.join(ROOT, "poster", "naver_blog.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "quotation_vertical" in src or "모바일에서 2줄" in src
    assert '"─" * 12' in src
    print("OK divider_skip")


if __name__ == "__main__":
    test_category_pick()
    test_stock_content_no_coupang_footer()
    test_header_card_no_truncation_in_source()
    test_divider_skip_in_source()
    print("\nAll stock fix tests passed.")
