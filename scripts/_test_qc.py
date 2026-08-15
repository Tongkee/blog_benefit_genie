"""publish_qc 회귀 테스트 (경량 assert, 외부 의존 없음).
실행: python scripts/_test_qc.py  →  전부 통과면 'QC TESTS OK'.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from generator.publish_qc import (  # noqa: E402
    check_wp_html, check_naver_text, check_caption, verdict, _CLICHE)

n = 0


def ok(cond, msg):
    global n
    n += 1
    assert cond, "FAIL: " + msg


# ── WP: 마커/h4 = FAIL ──
iss, _ = check_wp_html("<h2>x</h2><p>**굵게** 문장</p><h4>깊음</h4>\n*   불릿" + "가" * 1600)
ok(verdict(iss) == "FAIL", "마커+h4 FAIL")
ok(any("h4" in m for _, m in iss), "h4 감지")

# ── WP: 깨끗한 긴 글 = OK ──
clean = "<h2>제목</h2>" + "<p>" + "정상 문장이에요. " * 200 + "</p>"
iss, met = check_wp_html(clean, expect_images=False)
ok(verdict(iss) == "OK", f"clean OK (got {iss})")

# ── WP: 이미지 기대인데 0장 = WARN ──
iss, _ = check_wp_html(clean, expect_images=True)
ok(verdict(iss) == "WARN" and any("이미지 0" in m for _, m in iss), "이미지0 WARN")

# ── WP: 계층 역전(h3 먼저) = WARN ──
iss, _ = check_wp_html("<h3>먼저</h3>" + "<p>" + "글자 " * 500 + "</p>")
ok(any("계층 역전" in m for _, m in iss), "계층역전 WARN")

# ── WP: 본문 과소 = WARN ──
iss, _ = check_wp_html("<h2>x</h2><p>짧아요</p>")
ok(any("과소" in m for _, m in iss), "과소 WARN")

# ── 상투어: 해요체 변형 감지(2026-07-24 핵심) ──
for s in ["확인하는 것이 중요해요", "하는 게 좋아요", "신청하시면 돼요", "도움이 돼요"]:
    ok(_CLICHE.search(s) is not None, f"해요체 상투어 감지: {s}")
# '-합니다체'도 여전히
ok(_CLICHE.search("확인하는 것이 중요합니다") is not None, "합니다체 상투어")

# ── 네이버: 이미지 0 = FAIL(에디터 유실) ──
iss, _ = check_naver_text("정상 본문 " * 200, img_count=0, table_count=1)
ok(verdict(iss) == "FAIL" and any("이미지 0" in m for _, m in iss), "네이버 이미지0 FAIL")
# 이미지 있으면 OK
iss, _ = check_naver_text("정상 본문 " * 200, img_count=3, table_count=1)
ok(verdict(iss) == "OK", "네이버 이미지 有 OK")
# 마커 누출 FAIL
ok(verdict(check_naver_text("**굵게** 누출" * 100)[0]) == "FAIL", "네이버 마커 FAIL")

# ── 캡션 ──
ok(verdict(check_caption("설거지 훅 [075] 정보는 댓글에")[0]) == "OK", "캡션 OK")
ok(verdict(check_caption("**굵게** [[링크]]")[0]) == "FAIL", "캡션 마커 FAIL")

print(f"QC TESTS OK ({n} assertions)")
