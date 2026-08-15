"""
HTML/CSS 템플릿 + Playwright 스크린샷으로 고품질 인포그래픽 생성.
가로로 긴 캔버스(1600×900), 중앙 900×900이 썸네일 크롭 영역 — 제목은 항상 그 안에.

썸네일 가독성 최우선 재설계(2026-07-04, 실물 피드백):
- 다크 그라디언트 배경 + 흰색 초대형 제목(최대 2줄, 라인당 실측 폭 기준 90~165px)
  → 150px 축소 썸네일에서도 제목이 읽히는 것이 목표.
- 크롭 영역(가운데 900×900) 안에는 핵심 키워드·작은 브랜드·카테고리 칩만.
  차트 막대 장식은 저투명도 배경 요소로 깔림(텍스트가 항상 위).
- 불릿 날개(오른쪽 작은 요약 텍스트)는 제거(2026-07-05 피드백) — 본문 표시 크기에서
  읽히지 않고 헤더 바로 아래 요약블록과 중복이라 제목 중심 구성만 유지.
- 카테고리별 강조색 시스템(빨강/보라/파랑 등)은 유지.
"""
import asyncio
import json
import logging
import os
import tempfile
from html import escape

logger = logging.getLogger(__name__)

# ── 썸네일 후킹 문구 다양화(2026-07-11 사용자 피드백) ──
# 문제: 카테고리 고정 keyword가 그대로 카드 문구가 돼 "공모주 캘린더"×3, "OO 분석" 반복
#       + 단어 덜어내기 폴백이 "지금 사도"처럼 어중간하게 끊김.
# 해결: LLM이 제목에서 완결형 후킹 문구(6~18자)를 뽑되, 최근 사용 문구와 겹치지 않게.
_THUMB_HISTORY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "thumb_history.json"
)
_THUMB_KEEP = 40


def _load_thumb_history() -> list[str]:
    try:
        with open(_THUMB_HISTORY, encoding="utf-8") as f:
            return list(json.load(f))[-_THUMB_KEEP:]
    except Exception:
        return []


def _save_thumb_phrase(phrase: str) -> None:
    try:
        hist = _load_thumb_history()
        hist.append(phrase)
        os.makedirs(os.path.dirname(_THUMB_HISTORY), exist_ok=True)
        with open(_THUMB_HISTORY, "w", encoding="utf-8") as f:
            json.dump(hist[-_THUMB_KEEP:], f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.warning(f"썸네일 문구 이력 저장 실패(무시): {e}")


def _hook_phrase(title: str, keyword: str, category: str) -> str | None:
    """제목 기반 완결형 후킹 문구 생성. 실패 시 None(기존 폴백 사용)."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return None
    import re as _re
    recent = _load_thumb_history()
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        avoid = "\n".join(f"- {p}" for p in recent[-15:]) or "(없음)"
        base_prompt = (
            f"네이버 블로그 썸네일 카드에 크게 들어갈 문구를 만든다.\n"
            f"글 제목: {title}\n카테고리: {category} / 핵심 키워드: {keyword}\n\n"
            "규칙:\n"
            "1. **공백 포함 18자 이내** — 매우 짧게. 연도·월(2026년 7월 등)은 절대 넣지 마라.\n"
            "   좋은 예(길이 감각): '펩트론 낙폭, 기회일까'(12자), 'VTI 하나로 미국 전부'(12자).\n"
            "2. 반드시 완결된 구절 — '지금 사도'처럼 어중간하게 끊긴 표현 금지. 말줄임표 금지.\n"
            "3. 이 글만의 구체 내용(종목명·숫자·판단 포인트)이 드러나고 클릭하고 싶게.\n"
            "4. 아래 최근 사용 문구들과 패턴·어미가 겹치지 않게:\n"
            f"{avoid}\n"
            "5. 과장·거짓 금지(제목에 없는 수익률 창작 금지).\n"
            "6. 주식 글에서 매수·매도 단정 권유 표현 금지('매수 찬스', '지금 사라' 등) —\n"
            "   질문형('사도 될까?')이나 분석형('핵심 포인트 3가지')으로.\n"
            "문구 한 줄만 출력."
        )
        prompt = base_prompt
        for attempt in range(2):
            resp = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
            line = next((l.strip().strip('"\'') for l in (getattr(resp, "text", "") or "").splitlines()
                         if l.strip()), "")
            # 후처리: 연도·월 접두 제거(모델이 자꾸 붙임)
            line = _re.sub(r"^\s*\d{4}년\s*(\d{1,2}월)?[\s,·:]*", "", line).strip(" ,·")
            if 4 <= len(line) <= 22 and "…" not in line and line not in recent:
                _save_thumb_phrase(line)
                return line
            logger.info(f"후킹 문구 검증 탈락(시도 {attempt + 1}: {line!r})")
            prompt = base_prompt + f"\n\n[재시도] 직전 출력 '{line}'은(는) {len(line)}자로 규칙 위반. 15자 이내로 더 짧게."
    except Exception as e:
        logger.warning(f"후킹 문구 생성 실패 — 폴백: {e}")
    return None

W = 1600  # 캔버스 폭(가로로 김)
H = 900   # 캔버스 높이 — 썸네일 크롭은 가운데 900×900(x: (W-H)/2 ~ (W+H)/2)

_STYLES: dict[str, dict] = {
    "금융재테크": {
        # PIL 폴백용 보존
        "bg":          "linear-gradient(145deg, #071543 0%, #0D2B7E 45%, #1055BE 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0D1B3E",
        "card_border": "#1E78FF",
        "badge":       "현지언니  생활금융",
        "footer":      "금융·재테크 총정리",
        # 라이트 스타일
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "금융·재테크",
        "icons":     ["💰", "🏦", "💳", "📈"],
        "cta":       "지금 바로 확인해보세요!",
        "sub_below": "핵심 가이드 총정리",
    },
    "세금절세": {
        "bg":          "linear-gradient(145deg, #3D0C00 0%, #7A1500 45%, #C43800 100%)",
        "accent":      "#FFD740",
        "tag_color":   "#2D0900",
        "card_border": "#FF6D00",
        "badge":       "현지언니  세금·절세",
        "footer":      "세금·절세 총정리",
        "color":     "#C62828",
        "bg_light":  "#FFF4F2",
        "label":     "세금·절세",
        "icons":     ["📋", "💹", "📊", "💡"],
        "cta":       "놓치지 말고 확인하세요!",
        "sub_below": "절세 전략 총정리",
    },
    "보험": {
        "bg":          "linear-gradient(145deg, #00222E 0%, #00474F 45%, #006064 100%)",
        "accent":      "#80FFEA",
        "tag_color":   "#00222E",
        "card_border": "#00BFA5",
        "badge":       "현지언니  보험 가이드",
        "footer":      "보험 핵심 정리",
        "color":     "#00695C",
        "bg_light":  "#EDFAFA",
        "label":     "보험 가이드",
        "icons":     ["🛡️", "💊", "📝", "✅"],
        "cta":       "보험료 아끼는 방법 확인!",
        "sub_below": "보험 핵심 총정리",
    },
    "부동산주거": {
        "bg":          "linear-gradient(145deg, #0D0028 0%, #2D0076 45%, #5500CC 100%)",
        "accent":      "#CCFF90",
        "tag_color":   "#0D0028",
        "card_border": "#AA00FF",
        "badge":       "현지언니  부동산·주거",
        "footer":      "부동산·주거 총정리",
        "color":     "#4527A0",
        "bg_light":  "#F4EEFF",
        "label":     "부동산·주거",
        "icons":     ["🏠", "📜", "🔑", "✅"],
        "cta":       "꼭 알아야 할 핵심 정보!",
        "sub_below": "부동산 정보 총정리",
    },
    "정부지원혜택": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "정부지원",
        "icons":     ["🏛️", "💰", "📋", "✅"],
        "cta":       "혜택 놓치지 마세요!",
        "sub_below": "정부지원 혜택 총정리",
    },
    "gov": {
        "bg":          "linear-gradient(145deg, #0A1428 0%, #0D2B7E 45%, #1565C0 100%)",
        "accent":      "#FFD232",
        "tag_color":   "#0A1428",
        "card_border": "#2196F3",
        "badge":       "현지언니  정부지원",
        "footer":      "정부지원 혜택 총정리",
        "color":     "#1357C0",
        "bg_light":  "#EEF3FF",
        "label":     "정부지원",
        "icons":     ["🏛️", "💰", "📋", "✅"],
        "cta":       "혜택 놓치지 마세요!",
        "sub_below": "정부지원 혜택 총정리",
    },
    "tech": {
        "bg":          "linear-gradient(150deg, #0A0F1E 0%, #142E5C 40%, #00ACC1 100%)",
        "accent":      "#26E6C3",
        "tag_color":   "#05080F",
        "card_border": "#26C6DA",
        "badge":       "형수의테크공장",
        "brand":       "형수의테크공장",
        "footer":      "최신 테크 총정리",
        "color":     "#0277BD",
        "bg_light":  "#E8F6FB",
        "label":     "IT·테크",
        "icons":     ["📱", "💻", "⚡", "🔌"],
        "cta":       "최신 소식 확인하세요!",
        "sub_below": "형수의테크공장",
    },
    "health": {
        "bg":          "linear-gradient(145deg, #071A07 0%, #1B5E20 45%, #2E7D32 100%)",
        "accent":      "#B9F6CA",
        "tag_color":   "#071A07",
        "card_border": "#4CAF50",
        "badge":       "현지언니  건강·의료",
        "footer":      "건강 정보 총정리",
        "color":     "#1B5E20",
        "bg_light":  "#EDFAF5",
        "label":     "건강·의료",
        "icons":     ["❤️", "🏥", "💊", "✅"],
        "cta":       "건강 정보 확인하세요!",
        "sub_below": "건강 정보 총정리",
    },
    "주식분석": {
        "bg":          "linear-gradient(145deg, #3D0A08 0%, #7A1510 45%, #C4341D 100%)",
        "accent":      "#FFB199",
        "tag_color":   "#3D0A08",
        "card_border": "#E74C3C",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "주식 분석",
        "color":     "#C0392B",
        "bg_light":  "#FFEEEA",
        "label":     "주식분석",
        "icons":     ["📈", "🔍", "💹", "✅"],
        "cta":       "오늘의 종목 확인하세요!",
        "sub_below": "종목 심층 분석",
    },
    "공모주": {
        "bg":          "linear-gradient(145deg, #23073D 0%, #4B1580 45%, #7B2FC4 100%)",
        "accent":      "#E0B3FF",
        "tag_color":   "#23073D",
        "card_border": "#8E44AD",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "공모주 캘린더",
        "color":     "#7B2FA0",
        "bg_light":  "#F7EEFA",
        "label":     "공모주",
        "icons":     ["🎟️", "📅", "💰", "✅"],
        "cta":       "청약 일정 확인하세요!",
        "sub_below": "공모주 캘린더",
    },
    "주식etf": {
        "bg":          "linear-gradient(145deg, #06213D 0%, #0E4B80 45%, #1878C4 100%)",
        "accent":      "#A8DBFF",
        "tag_color":   "#06213D",
        "card_border": "#2980B9",
        "badge":       "현지언니  주식 인사이트",
        "footer":      "ETF 인사이트",
        "color":     "#1F6FAE",
        "bg_light":  "#EAF4FC",
        "label":     "ETF",
        "icons":     ["📊", "💼", "📈", "✅"],
        "cta":       "핵심 ETF 확인하세요!",
        "sub_below": "ETF 인사이트",
    },
}
_DEFAULT = _STYLES["금융재테크"]


# 크롭 영역(900px) 안에서 제목이 쓸 수 있는 실제 폭. 좌우 24px 여유.
_TITLE_SAFE_PX = 850


def _char_units(text: str) -> float:
    """Noto Sans KR 기준 대략적인 문자 폭(em 단위) 추정. 한글/CJK≈1.0em, 영문/숫자는 더 좁음."""
    u = 0.0
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F or 0x4E00 <= o <= 0x9FFF or ch in "…％":
            u += 1.0
        elif ch == " ":
            u += 0.30
        elif ch.isdigit():
            u += 0.62
        elif ch.isupper():
            u += 0.74
        else:
            u += 0.55
    return max(u, 0.5)


def _layout_title(text: str) -> tuple[list[str], int]:
    """
    제목을 1~2줄로 배치하고 폰트 크기(px)를 결정.
    목표: 크롭 폭의 80%+ 를 채우는 초대형 폰트(90px+), 150px 축소에서도 판독 가능.
    """
    one_line_font = _TITLE_SAFE_PX / _char_units(text)
    words = text.split()

    # 한 줄로도 충분히 크면 한 줄 유지
    if one_line_font >= 104 or len(words) <= 1:
        if len(words) <= 1 and one_line_font < 88 and len(text) > 8:
            # 공백 없는 긴 덩어리 → 글자 단위로 반 나눔
            mid = len(text) // 2
            lines = [text[:mid], text[mid:]]
        else:
            lines = [text]
    else:
        # 두 줄 분할: 양쪽 줄 폭이 가장 균형 잡히는 공백 위치 선택
        best_lines, best_max = [text], _char_units(text)
        for i in range(1, len(words)):
            l1, l2 = " ".join(words[:i]), " ".join(words[i:])
            m = max(_char_units(l1), _char_units(l2))
            if m < best_max:
                best_max, best_lines = m, [l1, l2]
        lines = best_lines

    max_units = max(_char_units(ln) for ln in lines)
    font = int(_TITLE_SAFE_PX / max_units)
    font = max(72, min(font, 170))  # 하한 72는 안전장치 — 키워드 절단 로직상 실제론 85px+
    return lines, font


def _build_html(display_title: str, bullets: list[str] | None, style: dict) -> str:
    bg_dark   = style["bg"]          # 구 PIL 카드의 다크 그라디언트 재활용
    accent    = style["accent"]
    tag_color = style["tag_color"]
    label     = style["label"]
    brand     = style.get("brand", "현지언니")  # 블로그 브랜드 — 계정별 누출 방지(형수 vs 현지언니)
    icons     = style.get("icons", ["💡", "📌", "✅", "🔑"])

    lines, tf = _layout_title(display_title)
    title_html = "<br>".join(escape(ln) for ln in lines)

    # ── 배경 장식: 저투명도 차트 막대(카테고리 색) — 텍스트 뒤에 깔리는 분위기 요소 ──
    bar_heights = [22, 34, 28, 46, 38, 58, 50, 72, 62, 84, 74, 92, 82, 96]
    bars_html = "".join(
        f'<div class="bar" style="height:{h}%;"></div>' for h in bar_heights
    )

    # 불릿 날개 제거(2026-07-05 사용자 피드백): 21px 텍스트는 본문 표시 크기에서
    # 읽히지 않고, 같은 내용이 헤더 바로 아래 요약블록에 크게 나와 중복 — 제목 중심 유지.
    # (bullets 인자는 호출부 호환을 위해 유지하되 렌더하지 않음)
    _ = bullets

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900&display=swap');

*{{margin:0;padding:0;box-sizing:border-box;}}
body{{width:{W}px;height:{H}px;overflow:hidden;}}

.wrap{{
  position:relative;
  width:{W}px;height:{H}px;
  background:{bg_dark};
  font-family:'Noto Sans KR','Malgun Gothic','맑은 고딕',sans-serif;
  overflow:hidden;
}}

/* 카테고리 색 인지용 하단 액센트 바 — 축소돼도 색 정체성이 남는다 */
.edge{{
  position:absolute;left:0;right:0;bottom:0;height:18px;
  background:{accent};
}}

/* ── 배경 장식(저투명도) — 텍스트 아래 레이어 ── */
.glow{{
  position:absolute;
  left:50%;top:44%;transform:translate(-50%,-50%);
  width:1100px;height:700px;border-radius:50%;
  background:radial-gradient(closest-side, rgba(255,255,255,.10), transparent 70%);
  pointer-events:none;
}}
.bars{{
  position:absolute;left:0;right:0;bottom:18px;height:46%;
  display:flex;align-items:flex-end;gap:34px;
  padding:0 60px;
  opacity:.13;
  pointer-events:none;
}}
.bar{{
  flex:1;
  background:linear-gradient(to top, {accent}, transparent 130%);
  border-radius:10px 10px 0 0;
}}
/* 카테고리 아이콘 — 크롭 바깥 왼쪽 날개, 전체보기 전용 장식 */
.sideicon{{
  position:absolute;
  left:40px;top:50%;transform:translateY(-50%);
  font-size:260px;line-height:1;
  opacity:.12;
  pointer-events:none;user-select:none;
}}

/* ── 크롭 안전영역(가운데 900×900) 안: 칩 + 초대형 제목 + 브랜드만 ── */
.center{{
  position:absolute;
  left:{(W - H) // 2}px;width:{H}px;top:0;height:{H}px;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:34px;
  padding:0 24px 30px;
}}
.chip{{
  background:{accent};
  color:{tag_color};
  font-size:30px;font-weight:800;
  padding:10px 34px;
  border-radius:999px;
  letter-spacing:.5px;
}}
.title{{
  font-size:{tf}px;font-weight:900;
  color:#FFFFFF;
  line-height:1.14;
  letter-spacing:-2px;
  text-align:center;
  word-break:keep-all;
  white-space:nowrap;
  text-shadow:0 4px 24px rgba(0,0,0,.45);
}}
.underline{{
  width:150px;height:12px;border-radius:6px;
  background:{accent};
}}
/* 검색바 목업 — 검색 유도(벤치마킹: 너부리 스타일). 하단 크롭 안전영역. */
.searchbar{{
  position:absolute;
  left:50%;bottom:60px;transform:translateX(-50%);
  display:flex;align-items:stretch;
  border-radius:12px;overflow:hidden;
  box-shadow:0 8px 24px rgba(0,0,0,.35);
  max-width:600px;
}}
.sb-text{{
  background:#FFFFFF;color:#2A2A2A;
  padding:16px 26px;font-size:27px;font-weight:700;
  white-space:nowrap;
}}
.sb-btn{{
  background:{accent};color:{tag_color};
  padding:16px 26px;font-size:27px;font-weight:800;
  white-space:nowrap;
}}

</style>
</head>
<body>
<div class="wrap">
  <div class="glow"></div>
  <div class="bars">{bars_html}</div>
  <div class="sideicon">{icons[0] if icons else "💡"}</div>

  <div class="center">
    <div class="chip">{escape(label)}</div>
    <div class="title">{title_html}</div>
    <div class="underline"></div>
  </div>

  <div class="searchbar">
    <span class="sb-text">{escape(brand)} {escape(label)}</span>
    <span class="sb-btn">🔍 검색</span>
  </div>

  <div class="edge"></div>
</div>
</body>
</html>"""


async def _pw_screenshot(html: str) -> bytes:
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
        )
        try:
            ctx = await browser.new_context(
                viewport={"width": W, "height": H},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=18000)
            await page.wait_for_timeout(400)
            data = await page.screenshot(
                clip={"x": 0, "y": 0, "width": W, "height": H},
                type="png",
            )
            return data
        finally:
            await browser.close()


def create_infographic_via_html(
    title: str,
    keyword: str = "",
    category: str = "금융재테크",
    bullets: list[str] | None = None,
) -> str | None:
    """
    HTML/CSS + Playwright 인포그래픽(1600×900, 가운데 900×900이 썸네일 크롭 영역).
    다크 배경 + 초대형 흰 제목(최대 2줄) — 썸네일 가독성 최우선. 실패 시 None 반환.
    """
    import re

    style = _STYLES.get(category, _DEFAULT)

    # 1순위: LLM 후킹 문구(제목 맞춤·완결형·최근 문구와 중복 회피 — 2026-07-11)
    display = _hook_phrase(title, keyword, category)
    if not display:
        display = keyword.strip() if keyword and keyword.strip() else title.split("|")[0].strip()
        # 썸네일엔 핵심 키워드만: 앞머리 날짜("2026년 7월 4일" 등)와 괄호 부연은 제거
        display = re.sub(r"^\s*\d{4}년\s*\d{1,2}월(\s*\d{1,2}일)?[\s,·:~-]*", "", display)
        display = re.sub(r"\([^)]*\)", "", display).strip(" ,·|-") or display
        # 말줄임표(…) 금지 — 뒤 단어를 통째로 덜어내고, 자르다 어중간하게 끝나면
        # ("지금 사도" 사례, 2026-07-11) 미완결 꼬리 단어까지 마저 덜어낸다.
        truncated = False
        if len(display) > 22:
            words = display.split()
            while len(words) > 1 and len(" ".join(words)) > 22:
                words.pop()
                truncated = True
            _dangling = {"지금", "사도", "할", "더", "그", "이", "및", "vs", "대비", "관련"}
            while truncated and len(words) > 1 and words[-1].rstrip("?!.,") in _dangling:
                words.pop()
            display = " ".join(words).rstrip(" ,·")

    # 자르기는 _build_html의 _short_bullet(단어경계+말줄임표)이 담당하므로 여기선 개수만 제한
    clean_bullets = (bullets or [])[:4] or None
    html = _build_html(display, clean_bullets, style)

    try:
        screenshot = asyncio.run(_pw_screenshot(html))
    except RuntimeError as e:
        logger.warning(f"asyncio 루프 충돌 — HTML 인포그래픽 스킵: {e}")
        return None
    except Exception as e:
        logger.warning(f"Playwright 스크린샷 실패: {e}")
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(screenshot)
    tmp.close()
    logger.info(f"HTML 인포그래픽 생성: {display!r} [{category}] → {tmp.name}")
    return tmp.name


# ─────────────────────────────────────────────────────────────
# 비교 인포그래픽 (섹터·테마 ETF 항목별 비교 카드) — 월부 벤치마킹(2026-07-05)
# 밋밋한 텍스트 표 대신 '한눈에 비교되는 디자인 카드'로. 본문 [사진2]에 삽입.
# ─────────────────────────────────────────────────────────────

_CMP_ROWS = [
    ("성격", "성격", "text"),
    ("배당수익률(%)", "배당수익률", "pct_high"),   # 높을수록 강조(초록)
    ("총보수(%)", "총보수", "pct_low"),            # 낮을수록 강조(초록)
    ("3개월수익률(%)", "3개월 수익률", "pct_high"),
    ("지급주기", "배당 주기", "text"),
]


async def _pw_screenshot_element(html: str, width: int = 1080) -> bytes:
    """HTML의 .cardwrap 요소만 스크린샷(높이 가변) — 본문 삽입용 인포그래픽."""
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
        )
        try:
            ctx = await browser.new_context(
                viewport={"width": width, "height": 900}, device_scale_factor=2
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="networkidle", timeout=18000)
            await page.wait_for_timeout(350)
            el = await page.query_selector(".cardwrap")
            data = await (el.screenshot(type="png") if el else page.screenshot(type="png"))
            return data
        finally:
            await browser.close()


def _fmt_val(raw, kind: str) -> str:
    if raw is None or str(raw).strip() in ("", "-", "None"):
        return "-"
    if kind in ("pct_high", "pct_low"):
        try:
            return f"{float(raw):g}%"
        except (ValueError, TypeError):
            return str(raw)
    return str(raw)


def _build_compare_html(group_name: str, tickers: list, targets: dict, style: dict) -> str:
    accent = style["accent"]
    color = style.get("color", "#1357C0")
    label = style.get("label", "ETF")
    n = len(tickers)
    W = 1080

    # 강조(초록) 대상 셀 계산: pct_high=최댓값, pct_low=최솟값
    best: dict = {}
    for key, _, kind in _CMP_ROWS:
        if kind not in ("pct_high", "pct_low"):
            continue
        vals = []
        for t in tickers:
            v = targets.get(t, {}).get(key)
            try:
                vals.append((float(v), t))
            except (ValueError, TypeError):
                pass
        if vals:
            best[key] = (max if kind == "pct_high" else min)(vals)[1]

    # 헤더 행(ETF 티커)
    head_cols = "".join(
        f'<th class="etf">{escape(t)}<span class="etfname">'
        f'{escape(str(targets.get(t, {}).get("이름", ""))[:16])}</span></th>'
        for t in tickers
    )
    # 데이터 행
    body_rows = ""
    for key, disp, kind in _CMP_ROWS:
        if not any(targets.get(t, {}).get(key) not in (None, "", "-") for t in tickers):
            continue
        cells = ""
        for t in tickers:
            raw = targets.get(t, {}).get(key)
            val = _fmt_val(raw, kind)
            hot = " hot" if best.get(key) == t else ""
            cells += f'<td class="v{hot}">{escape(val)}</td>'
        body_rows += f'<tr><td class="lbl">{escape(disp)}</td>{cells}</tr>'

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}}
body{{width:{W}px;background:#fff;}}
.cardwrap{{width:{W}px;padding:38px 36px 34px;background:#fff;}}
.chip{{display:inline-block;background:{accent};color:{style.get('tag_color','#0D1B3E')};
  font-size:26px;font-weight:800;padding:8px 26px;border-radius:999px;margin-bottom:16px;}}
.htitle{{font-size:46px;font-weight:900;color:#1A1A1A;letter-spacing:-1.5px;margin-bottom:6px;line-height:1.2;}}
.hsub{{font-size:25px;color:#888;font-weight:500;margin-bottom:26px;}}
table{{width:100%;border-collapse:separate;border-spacing:0;border-radius:16px;overflow:hidden;
  box-shadow:0 4px 22px rgba(0,0,0,.08);}}
th,td{{padding:20px 14px;text-align:center;font-size:27px;border-bottom:1px solid #EEE;}}
thead th{{background:{color};color:#fff;font-size:30px;font-weight:900;padding:22px 12px;}}
th.etf .etfname{{display:block;font-size:18px;font-weight:500;color:rgba(255,255,255,.8);margin-top:4px;}}
td.lbl{{background:#F6F8FC;font-weight:800;color:#333;font-size:25px;text-align:left;padding-left:24px;width:210px;}}
td.v{{font-weight:700;color:#2A2A2A;}}
td.v.hot{{background:#E3FBEE;color:#0C8A44;font-weight:900;}}
tbody tr:last-child td{{border-bottom:none;}}
.foot{{margin-top:18px;font-size:21px;color:#AAA;text-align:right;}}
</style></head><body>
<div class="cardwrap">
  <span class="chip">{escape(label)} 비교</span>
  <div class="htitle">{escape(group_name)} 한눈에 비교</div>
  <div class="hsub">초록 = 항목별 가장 유리한 값 · 야후파이낸스 마지막 거래일 기준</div>
  <table>
    <thead><tr><th class="lblhead"></th>{head_cols}</tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
  <div class="foot">현지언니 · 수치는 시점따라 변동</div>
</div></body></html>"""


def create_comparison_infographic(group_name: str, targets: dict, category: str = "주식etf") -> str | None:
    """섹터·테마 ETF 비교 인포그래픽(월부 스타일). targets={티커:{지표..}}. 실패 시 None."""
    if not targets or len(targets) < 2:
        return None
    style = _STYLES.get(category, _DEFAULT)
    tickers = list(targets.keys())[:4]
    html = _build_compare_html(group_name, tickers, targets, style)
    try:
        png = asyncio.run(_pw_screenshot_element(html))
    except Exception as e:
        logger.warning(f"비교 인포그래픽 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    logger.info(f"비교 인포그래픽 생성: {group_name} ({len(tickers)}종) → {tmp.name}")
    return tmp.name


# ─────────────────────────────────────────────────────────────
# 개념 카드 인포그래픽 (핵심 N가지 '한눈에 보기') — 두번째스물하나 벤치마킹(2026-07-06)
# 지루한 텍스트 대신 번호배지+라벨+한줄설명의 디자인 카드로. 요약 불릿을 재사용해
# 자동 생성(모델 추가출력 불필요). 본문 [사진2]에 삽입.
# ─────────────────────────────────────────────────────────────

def _parse_concept_items(bullets: list[str]) -> list[tuple[str, str]]:
    """요약 불릿('✓ 라벨: 내용' / '· 라벨: 내용')을 (라벨, 설명) 쌍으로 분해.
    콜론이 없으면 앞 몇 어절을 라벨로. 빈 항목은 스킵."""
    import re
    items: list[tuple[str, str]] = []
    for b in bullets or []:
        s = re.sub(r"^[\s✓✔☑√❤·•▪●◦・\-–\*①-⑳]+", "", str(b)).strip()
        if not s:
            continue
        m = re.match(r"\s*([^:：]{1,20})[:：]\s*(.+)$", s)
        if m:
            label, desc = m.group(1).strip(), m.group(2).strip()
        else:
            words = s.split()
            label = " ".join(words[:2])[:14]
            desc = s
        if label:
            items.append((label, desc[:60]))
    return items


def _build_concept_html(headline: str, items: list[tuple[str, str]], style: dict) -> str:
    accent = style["accent"]
    color = style.get("color", "#1357C0")
    bg_light = style.get("bg_light", "#EEF3FF")
    label = style.get("label", "핵심")
    tag_color = style.get("tag_color", "#0D1B3E")
    W = 1080

    rows = ""
    for i, (lbl, desc) in enumerate(items, 1):
        rows += (
            f'<div class="row">'
            f'<div class="num">{i}</div>'
            f'<div class="txt"><div class="lbl">{escape(lbl)}</div>'
            f'<div class="desc">{escape(desc)}</div></div>'
            f'</div>'
        )

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}}
body{{width:{W}px;background:#fff;}}
.cardwrap{{width:{W}px;padding:40px 40px 34px;background:#fff;}}
.chip{{display:inline-block;background:{accent};color:{tag_color};
  font-size:26px;font-weight:800;padding:9px 28px;border-radius:999px;margin-bottom:18px;}}
.htitle{{font-size:47px;font-weight:900;color:#1A1A1A;letter-spacing:-1.5px;
  margin-bottom:30px;line-height:1.22;}}
.htitle b{{color:{color};}}
.row{{display:flex;align-items:flex-start;gap:24px;background:{bg_light};
  border-radius:18px;padding:26px 30px;margin-bottom:16px;}}
.num{{flex:none;width:62px;height:62px;border-radius:50%;background:{color};color:#fff;
  font-size:34px;font-weight:900;display:flex;align-items:center;justify-content:center;
  box-shadow:0 4px 12px rgba(0,0,0,.14);}}
.txt{{padding-top:2px;}}
.lbl{{font-size:32px;font-weight:900;color:#1A1A1A;letter-spacing:-1px;margin-bottom:6px;}}
.desc{{font-size:27px;font-weight:500;color:#555;line-height:1.4;}}
.foot{{margin-top:20px;font-size:21px;color:#AAA;text-align:right;}}
</style></head><body>
<div class="cardwrap">
  <span class="chip">{escape(label)} 핵심</span>
  <div class="htitle">한눈에 보는 <b>핵심 {len(items)}가지</b></div>
  {rows}
  <div class="foot">현지언니 · 자세한 내용은 본문 참고</div>
</div></body></html>"""


def create_concept_infographic(bullets: list[str], category: str = "금융재테크",
                               headline: str = "") -> str | None:
    """요약 불릿을 '핵심 N가지' 개념 카드로 렌더(두번째스물하나 벤치마킹). 실패 시 None."""
    items = _parse_concept_items(bullets)
    if len(items) < 2:  # 2줄 미만이면 카드 실익 없음
        return None
    items = items[:4]
    style = _STYLES.get(category, _DEFAULT)
    html = _build_concept_html(headline, items, style)
    try:
        png = asyncio.run(_pw_screenshot_element(html))
    except Exception as e:
        logger.warning(f"개념 카드 인포그래픽 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    logger.info(f"개념 카드 인포그래픽 생성: {len(items)}항목 [{category}] → {tmp.name}")
    return tmp.name


# ─────────────────────────────────────────────────────────────
# 실사진 배경 헤더카드 (테크티노 벤치마크) — 실제 뉴스/스톡 사진 위에 굵은 훅 텍스트 오버레이.
# 대표 썸네일용. 그라디언트 카드(브랜드 누출/복제 인상)와 달리 '사진+한 줄 훅'으로 클릭 유도.
# ─────────────────────────────────────────────────────────────

def create_photo_header_card(photo_path: str, title: str, keyword: str = "",
                             category: str = "tech") -> str | None:
    """photo_path(로컬 실사진)를 배경으로 깔고 하단에 굵은 훅 텍스트를 얹은 1080x1080 헤더카드.
    실패 시 None(호출부가 원본 실사진으로 폴백)."""
    import base64
    import re as _re
    try:
        with open(photo_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception as e:
        logger.warning(f"헤더카드 배경 사진 읽기 실패: {e}")
        return None
    mime = "image/png" if photo_path.lower().endswith(".png") else "image/jpeg"
    bg_uri = f"data:{mime};base64,{b64}"

    style = _STYLES.get(category, _DEFAULT)
    accent = style["accent"]
    tag_color = style.get("tag_color", "#05080F")
    label = style.get("label", "IT·테크")

    # 훅 문구: 제목 기반 완결형(6~18자). 실패 시 제목 앞부분.
    display = _hook_phrase(title, keyword, category)
    if not display:
        display = _re.sub(r"^\s*\d{4}년\s*\d{0,2}월?\s*", "", title).split("|")[0].strip()
        display = _re.sub(r"\([^)]*\)", "", display).strip(" ,·|-")
        # 단어 중간 절단 방지 — 20자 넘으면 통째 단어를 덜어낸다('모니터 시'처럼 끊기지 않게).
        if len(display) > 20:
            words = display.split()
            while len(words) > 1 and len(" ".join(words)) > 20:
                words.pop()
            display = " ".join(words).rstrip(" ,·")
    lines, tf = _layout_title(display)
    tf = max(60, min(int(tf * 1.05), 150))
    title_html = "<br>".join(escape(ln) for ln in lines)

    W = 1080
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
.cardwrap{{position:relative;width:{W}px;height:{W}px;overflow:hidden;
  font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:#111;}}
.bg{{position:absolute;inset:0;background:url('{bg_uri}') center/cover no-repeat;}}
.shade{{position:absolute;inset:0;
  background:linear-gradient(180deg, rgba(0,0,0,.18) 0%, rgba(0,0,0,0) 38%, rgba(0,0,0,.55) 72%, rgba(0,0,0,.86) 100%);}}
.content{{position:absolute;left:56px;right:56px;bottom:64px;
  display:flex;flex-direction:column;align-items:flex-start;gap:22px;}}
.chip{{background:{accent};color:{tag_color};font-size:34px;font-weight:800;
  padding:10px 34px;border-radius:999px;letter-spacing:.5px;}}
.title{{color:#FFFFFF;font-size:{tf}px;font-weight:900;line-height:1.12;
  letter-spacing:-2px;word-break:keep-all;text-shadow:0 4px 22px rgba(0,0,0,.55);}}
.title b{{color:{accent};}}
.bar{{position:absolute;left:0;right:0;bottom:0;height:16px;background:{accent};}}
</style></head><body>
<div class="cardwrap">
  <div class="bg"></div><div class="shade"></div>
  <div class="content">
    <div class="chip">{escape(label)}</div>
    <div class="title">{title_html}</div>
  </div>
  <div class="bar"></div>
</div></body></html>"""

    try:
        png = asyncio.run(_pw_screenshot_element(html, width=W))
    except Exception as e:
        logger.warning(f"사진 헤더카드 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    logger.info(f"사진 헤더카드 생성: {display!r} → {tmp.name}")
    return tmp.name


# ─────────────────────────────────────────────────────────────
# 형수의테크공장 전용 텍스트 헤더카드 — 실사진·일러스트 모두 실패 시 최후 폴백.
# 현지언니 검색바형 인포그래픽 레이아웃과 완전히 구분되는 좌정렬 '테크 뉴스' 카드
# (2026-07-17 사용자 피드백: 검색바형 카드가 tech에 폴백으로 쓰이던 것 폐기).
# ─────────────────────────────────────────────────────────────

def create_tech_header_card(title: str, keyword: str = "") -> str | None:
    """검색바 없는 다크 '테크 뉴스' 헤더카드(1080×1080). 실패 시 None."""
    import re as _re

    style = _STYLES["tech"]
    accent = style["accent"]
    label = style.get("label", "IT·테크")
    brand = style.get("brand", "형수의테크공장")

    display = _hook_phrase(title, keyword, "tech")
    if not display:
        display = _re.sub(r"^\s*\d{4}년\s*\d{0,2}월?\s*", "", title).split("|")[0].strip()
        display = _re.sub(r"\([^)]*\)", "", display).strip(" ,·|-")
        if len(display) > 20:
            words = display.split()
            while len(words) > 1 and len(" ".join(words)) > 20:
                words.pop()
            display = " ".join(words).rstrip(" ,·")
    lines, tf = _layout_title(display)
    tf = max(64, min(int(tf * 0.95), 132))
    title_html = "<br>".join(escape(ln) for ln in lines)

    CW = 1080
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@500;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
.cardwrap{{position:relative;width:{CW}px;height:{CW}px;overflow:hidden;
  font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:#0B0F16;}}
/* 배경: 은은한 회로 그리드 + 코너 네온 글로우 — 검색바형 카드와 다른 정체성 */
.grid{{position:absolute;inset:0;opacity:.55;background:
  repeating-linear-gradient(0deg, rgba(38,230,195,.05) 0 1px, transparent 1px 90px),
  repeating-linear-gradient(90deg, rgba(38,230,195,.05) 0 1px, transparent 1px 90px);}}
.glow{{position:absolute;right:-260px;top:-260px;width:720px;height:720px;border-radius:50%;
  background:radial-gradient(closest-side, rgba(38,230,195,.22), transparent 70%);}}
.toprow{{position:absolute;left:64px;right:64px;top:64px;
  display:flex;align-items:center;justify-content:space-between;}}
.brand{{color:#FFFFFF;font-size:36px;font-weight:800;letter-spacing:-.5px;}}
.brand i{{display:inline-block;width:16px;height:16px;border-radius:50%;
  background:{accent};margin-right:14px;}}
.chip{{border:2px solid {accent};color:{accent};font-size:28px;font-weight:800;
  padding:8px 26px;border-radius:999px;letter-spacing:.5px;}}
.content{{position:absolute;left:64px;right:64px;top:50%;transform:translateY(-52%);
  display:flex;flex-direction:column;align-items:flex-start;gap:34px;}}
.title{{color:#FFFFFF;font-size:{tf}px;font-weight:900;line-height:1.16;
  letter-spacing:-2px;text-align:left;word-break:keep-all;}}
.accentbar{{width:120px;height:10px;border-radius:5px;background:{accent};}}
.caption{{position:absolute;left:64px;bottom:70px;color:#8B98A8;
  font-size:30px;font-weight:500;letter-spacing:.5px;}}
.edge{{position:absolute;left:0;right:0;bottom:0;height:14px;background:{accent};}}
</style></head><body>
<div class="cardwrap">
  <div class="grid"></div><div class="glow"></div>
  <div class="toprow">
    <span class="brand"><i></i>{escape(brand)}</span>
    <span class="chip">{escape(label)}</span>
  </div>
  <div class="content">
    <div class="accentbar"></div>
    <div class="title">{title_html}</div>
  </div>
  <div class="caption">오늘의 테크 소식, 쉽게 풀어드립니다</div>
  <div class="edge"></div>
</div></body></html>"""

    try:
        png = asyncio.run(_pw_screenshot_element(html, width=CW))
    except Exception as e:
        logger.warning(f"테크 헤더카드 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    logger.info(f"테크 헤더카드 생성: {display!r} → {tmp.name}")
    return tmp.name


# ─────────────────────────────────────────────────────────────
# 형수의테크공장 섹션 미니카드(1080×360 배너) — 실사진이 없는 본문 [사진N] 슬롯의
# 최종 보증 폴백(2026-07-27). 소제목 텍스트 기반이라 오프토픽이 원천 불가능하고,
# 헤더 텍스트 카드와 같은 다크+회로그리드 브랜드 정체성을 유지한다.
# LLM 호출 없음(_hook_phrase 미사용 — 추가 비용·thumb_history 오염 방지, 소제목은 이미 짧음).
# ─────────────────────────────────────────────────────────────

_TECH_SECTION_ACCENTS = ("#26E6C3", "#5B8CFF", "#FFB86B")  # 슬롯마다 악센트 로테이션


def create_tech_section_card(title: str, accent: str = "", index: int = 0) -> str | None:
    """섹션 소제목을 얹은 미니 브랜드 배너 카드(1080×360).
    accent 미지정 시 index 기반 로테이션. 성공 시 임시 PNG 경로, 실패 시 None."""
    import re as _re

    style = _STYLES["tech"]
    accent = accent or _TECH_SECTION_ACCENTS[index % len(_TECH_SECTION_ACCENTS)]
    brand = style.get("brand", "형수의테크공장")
    label = style.get("label", "IT·테크")

    display = _re.sub(r"\s+", " ", (title or "")).strip(" ,·|—-")
    if not display:
        return None
    if len(display) > 26:  # 배너 2줄 한계 — 소제목은 보통 8~20자라 거의 안 걸림
        words = display.split()
        while len(words) > 1 and len(" ".join(words)) > 26:
            words.pop()
        display = " ".join(words).rstrip(" ,·")
    lines, tf = _layout_title(display)
    tf = max(44, min(int(tf * 0.52), 76))  # 배너 높이(360px)에 맞게 재클램프
    title_html = "<br>".join(escape(ln) for ln in lines)

    W, HN = 1080, 360
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@500;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
.cardwrap{{position:relative;width:{W}px;height:{HN}px;overflow:hidden;
  font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:#0B0F16;}}
.grid{{position:absolute;inset:0;opacity:.5;background:
  repeating-linear-gradient(0deg, {accent}0D 0 1px, transparent 1px 64px),
  repeating-linear-gradient(90deg, {accent}0D 0 1px, transparent 1px 64px);}}
.glow{{position:absolute;right:-180px;top:-180px;width:460px;height:460px;border-radius:50%;
  background:radial-gradient(closest-side, {accent}38, transparent 70%);}}
.side{{position:absolute;left:0;top:0;bottom:0;width:14px;background:{accent};}}
.inner{{position:absolute;left:64px;right:64px;top:50%;transform:translateY(-50%);
  display:flex;flex-direction:column;align-items:flex-start;gap:20px;}}
.meta{{display:flex;align-items:center;gap:18px;}}
.brand{{color:#8B98A8;font-size:24px;font-weight:700;letter-spacing:-.3px;}}
.brand i{{display:inline-block;width:11px;height:11px;border-radius:50%;
  background:{accent};margin-right:10px;}}
.chip{{border:2px solid {accent};color:{accent};font-size:20px;font-weight:800;
  padding:4px 18px;border-radius:999px;letter-spacing:.5px;}}
.title{{color:#FFFFFF;font-size:{tf}px;font-weight:900;line-height:1.18;
  letter-spacing:-1.5px;text-align:left;word-break:keep-all;}}
</style></head><body>
<div class="cardwrap">
  <div class="grid"></div><div class="glow"></div><div class="side"></div>
  <div class="inner">
    <div class="meta"><span class="brand"><i></i>{escape(brand)}</span><span class="chip">{escape(label)}</span></div>
    <div class="title">{title_html}</div>
  </div>
</div></body></html>"""

    try:
        png = asyncio.run(_pw_screenshot_element(html, width=W))
    except Exception as e:
        logger.warning(f"섹션 미니카드 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    logger.info(f"섹션 미니카드 생성: {display!r} (accent {accent}) → {tmp.name}")
    return tmp.name
