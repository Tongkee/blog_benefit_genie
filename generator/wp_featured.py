"""
워드프레스 대표 이미지(썸네일) 생성 — 일러스트+타이틀 조합 (2026-07-10 사용자 확정).

poster/illustration.py(Imagen 4 Fast 플랫벡터)를 배경으로 쓰고,
하단 그라디언트 + 글 제목 + 카테고리 칩을 PIL로 오버레이한다.
1200×675(16:9) — WP 썸네일·OG 이미지 겸용.

본문은 텍스트 심층분석 유지(이미지 정책) — 대표 이미지만 생성.
"""
import io
import logging
import os
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger("wp_featured")

W, H = 1200, 675
_PAD = 56

# 허브별 액센트(카테고리 칩·폴백 배경)
_HUB_COLOR = {
    "pension-tax": (45, 106, 79),      # 딥그린
    "loan-credit": (30, 90, 150),      # 블루
    "insurance-risk": (192, 108, 50),  # 앰버
    "tax-refund": (109, 76, 160),      # 퍼플
    "housing-plan": (32, 122, 122),    # 틸
    "policy-benefit": (170, 70, 85),   # 로즈
}
_DEFAULT_COLOR = (45, 106, 79)

_FONT_CANDIDATES = [
    # Linux (GH Actions·EC2)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    # Windows (로컬)
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap_title(draw: ImageDraw.ImageDraw, title: str, font, max_w: int, max_lines: int = 2) -> list[str]:
    """제목을 폭 기준 최대 2줄로 감싸고 넘치면 말줄임."""
    words = title.split()
    lines, cur = [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    leftover = len(lines) == max_lines and draw.textlength(" ".join(words), font=font) > max_w * max_lines
    if leftover:
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _fallback_bg(hub_id: str) -> Image.Image:
    """일러스트 실패 시 — 액센트 색 대각 그라디언트 배경."""
    base = _HUB_COLOR.get(hub_id, _DEFAULT_COLOR)
    dark = tuple(max(0, c - 45) for c in base)
    img = Image.new("RGB", (W, H))
    for y in range(H):
        t = y / H
        row = tuple(round(base[i] * (1 - t) + dark[i] * t) for i in range(3))
        for_line = Image.new("RGB", (W, 1), row)
        img.paste(for_line, (0, y))
    return img


def build_featured_image(title: str, keyword: str, category: str, hub_id: str,
                         api_key: str = "") -> str | None:
    """대표 이미지 PNG 생성 → 임시파일 경로. 실패해도 폴백 배경으로 항상 생성."""
    bg = None
    try:
        from poster.illustration import generate_editorial_illustration
        p = generate_editorial_illustration(keyword, category, api_key=api_key, width=W)
        if p:
            bg = Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
            os.unlink(p)
    except Exception as e:
        logger.warning(f"일러스트 생성 실패 — 그라디언트 폴백: {e}")
    if bg is None:
        bg = _fallback_bg(hub_id)

    # 하단 다크 그라디언트(제목 가독성)
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        t = max(0.0, (y / H - 0.42) / 0.58)
        grad.putpixel((0, y), round(215 * (t ** 1.4)))
    overlay = Image.new("RGB", (W, H), (16, 20, 24))
    bg = Image.composite(overlay, bg, grad.resize((W, H)))

    d = ImageDraw.Draw(bg)
    accent = _HUB_COLOR.get(hub_id, _DEFAULT_COLOR)

    # 카테고리 칩 (좌상단)
    chip_f = _font(30)
    chip_t = category.strip() or "생활금융"
    tw = d.textlength(chip_t, font=chip_f)
    chip_h = 52
    d.rounded_rectangle([_PAD, _PAD, _PAD + tw + 44, _PAD + chip_h], radius=chip_h // 2, fill=accent)
    d.text((_PAD + 22, _PAD + chip_h / 2), chip_t, font=chip_f, fill=(255, 255, 255), anchor="lm")

    # 제목 (하단, 최대 2줄)
    title_f = _font(62)
    lines = _wrap_title(d, title.strip(), title_f, W - _PAD * 2)
    line_h = 82
    brand_h = 46
    y = H - _PAD - brand_h - line_h * len(lines)
    for ln in lines:
        # 얇은 그림자 → 가독성
        d.text((_PAD + 2, y + 2), ln, font=title_f, fill=(0, 0, 0))
        d.text((_PAD, y), ln, font=title_f, fill=(255, 255, 255))
        y += line_h
    # 브랜드 마크
    brand_f = _font(28)
    d.text((_PAD, H - _PAD - 14), "현지언니 · hyunjiunni.com", font=brand_f,
           fill=(235, 238, 240), anchor="lm")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    bg.save(tmp.name, "PNG")
    tmp.close()
    logger.info(f"대표 이미지 생성: {title!r} → {tmp.name}")
    return tmp.name
