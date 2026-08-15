"""현지언니 WP favicon (512px PNG) — poster/wp_assets/hyunji-favicon.png 생성."""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install Pillow")

OUT = Path(__file__).resolve().parent / "hyunji-favicon.png"
BG = (47, 111, 79)  # --hj-accent #2f6f4f
FG = (255, 255, 255)
SIZE = 512

img = Image.new("RGB", (SIZE, SIZE), BG)
draw = ImageDraw.Draw(img)
# 둥근 모서리 느낌 — 원형 마스크
mask = Image.new("L", (SIZE, SIZE), 0)
md = ImageDraw.Draw(mask)
md.ellipse((8, 8, SIZE - 8, SIZE - 8), fill=255)
img.putalpha(mask)

# 글자 "현" — 시스템 한글 폰트 폴백
font = None
for fp in (
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
):
    p = Path(fp)
    if p.exists():
        font = ImageFont.truetype(str(p), 280)
        break
if font is None:
    font = ImageFont.load_default()

text = "현"
bbox = draw.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1] - 10), text, fill=FG, font=font)

# RGBA → PNG (흰 배경 합성 for WP site icon)
bg = Image.new("RGB", (SIZE, SIZE), BG)
bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
bg.save(OUT, "PNG")
print(f"Wrote {OUT}")
