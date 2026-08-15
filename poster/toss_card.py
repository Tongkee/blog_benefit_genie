"""토스 실계좌 '인증 카드' 이미지 생성 — 실데이터 대시보드형(2026-07-22).
토스 API는 화면 캡처를 주지 않으므로, 실계좌 값을 깔끔한 카드로 렌더한다.
숫자는 전부 실데이터(fetch_holdings). 계좌번호 등 식별정보는 아예 안 쓴다.
"""
import os
import tempfile

_FONT_CANDS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]
_FONT_REG = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]

W, H = 1200, 675
INK = (17, 24, 39)
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
ACCENT = (42, 120, 214)
UP = (211, 47, 47)     # 한국식: 상승=빨강
DOWN = (25, 118, 210)  # 하락=파랑


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("원", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _font(cands, size):
    from PIL import ImageFont
    p = next((f for f in cands if os.path.exists(f)), None)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()


def render_account_card(holdings: dict, fx: float, period_label: str) -> str | None:
    """holdings=fetch_holdings() 원본, fx=USD/KRW 환율(float). 카드 PNG 경로 반환."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 12], fill=ACCENT)  # 상단 액센트 바

        f_brand = _font(_FONT_CANDS, 30)
        f_label = _font(_FONT_REG, 26)
        f_big = _font(_FONT_CANDS, 74)
        f_mid = _font(_FONT_CANDS, 40)
        f_row = _font(_FONT_REG, 30)
        f_row_b = _font(_FONT_CANDS, 30)
        f_foot = _font(_FONT_REG, 22)

        pv_usd = _num(holdings.get("marketValue", {}).get("amount", {}).get("usd"))
        pur_usd = _num(holdings.get("totalPurchaseAmount", {}).get("usd"))
        pl = holdings.get("profitLoss", {})
        # 앱은 '차감 전' 수익률을 표시 → rate(비용차감전)로 맞춤(2026-07-22)
        pl_usd = _num(pl.get("amount", {}).get("usd"))
        rate = _num(pl.get("rate")) * 100
        col = UP if rate >= 0 else DOWN
        sign = "+" if rate >= 0 else ""

        # 헤더
        d.text((60, 44), "현지언니 실계좌 인증", font=f_brand, fill=INK)
        d.text((60, 86), period_label, font=f_label, fill=MUTED)

        # 총 평가금액(원화 크게 + 달러)
        d.text((60, 150), "총 평가금액", font=f_label, fill=MUTED)
        krw = f"{pv_usd * fx:,.0f}원" if fx else "-"
        d.text((60, 186), krw, font=f_big, fill=INK)
        d.text((62, 280), f"(${pv_usd:,.2f})", font=f_mid, fill=MUTED)

        # 손익 배지
        d.text((640, 150), "누적 손익(수익률)", font=f_label, fill=MUTED)
        d.text((640, 186), f"{sign}{rate:.2f}%", font=f_big, fill=col)
        pl_krw = f"{pl_usd * fx:+,.0f}원" if fx else ""
        d.text((642, 280), f"({pl_krw})", font=f_mid, fill=col)

        d.line([60, 350, W - 60, 350], fill=LINE, width=2)

        # 총 매입금액
        d.text((60, 372), "총 매입금액", font=f_label, fill=MUTED)
        pur_krw = f"{pur_usd * fx:,.0f}원" if fx else "-"
        d.text((240, 370), f"{pur_krw}  (${pur_usd:,.2f})", font=f_row_b, fill=INK)

        # 보유종목 상위 5 (평가액순) — 앱처럼 원화 평가액 + 차감전 수익률
        d.text((60, 424), "주요 보유 종목", font=f_label, fill=MUTED)
        items = sorted(holdings.get("items", []),
                       key=lambda it: _num(it.get("marketValue", {}).get("amount")), reverse=True)[:5]
        y = 458
        for it in items:
            nm = (it.get("name") or it.get("symbol") or "")[:16]
            r = _num(it.get("profitLoss", {}).get("rate")) * 100
            rc = UP if r >= 0 else DOWN
            rs = "+" if r >= 0 else ""
            amt = _num(it.get("marketValue", {}).get("amount"))
            val = f"{amt * fx:,.0f}원" if fx else f"${amt:,.0f}"
            d.text((60, y), nm, font=f_row_b, fill=INK)
            d.text((330, y), val, font=f_row, fill=MUTED)
            d.text((770, y), f"{rs}{r:.2f}%", font=f_row_b, fill=rc)
            y += 31

        # 푸터
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y.%m.%d")
        d.line([60, H - 60, W - 60, H - 60], fill=LINE, width=1)
        d.text((60, H - 48), f"토스증권 Open API 실계좌 데이터 · {today} 기준 · 개인 기록(투자 권유 아님)",
               font=f_foot, fill=MUTED)

        out = os.path.join(tempfile.gettempdir(), "toss_account_card.png")
        img.save(out, "PNG")
        return out
    except Exception:
        return None
