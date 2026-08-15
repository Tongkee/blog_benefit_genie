"""
에디토리얼 일러스트 생성 (Imagen 4.0 Fast) — 두번째스물하나 벤치마킹(2026-07-06).

지루한 정보성 글에 주제 맞춤 플랫 벡터 일러스트를 넣어 엔게이지먼트↑.
gov/info가 'Pexels 스톡사진이 주제와 무관'해서 본문 사진을 버렸던 문제를,
'항상 주제에 맞는' AI 일러스트로 정면 해결(§7 이미지 정책과 정합).

핵심 리스크=일관성: 약한 프롬프트면 포토리얼·깨진 텍스트로 드리프트함(실측).
→ STYLE을 앞·지배적으로 두고 텍스트/사진/차트를 강하게 금지(3연속 검증 통과).
"""
import io
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

# 실측으로 확정한 안정 스타일(플랫 벡터 강제 + 텍스트/사진/차트 금지)
_STYLE = (
    "Flat 2D vector illustration, clean minimal editorial style, soft pastel color palette, "
    "simple rounded shapes, thick smooth outlines, gentle shadows, cheerful trustworthy mood. "
    "STRICTLY NOT a photograph, NOT realistic, NOT 3D render. "
    "Absolutely NO text, NO letters, NO numbers, NO words, NO signage, "
    "NO charts with labels, NO documents with writing."
)

_CAT_LABEL = {
    "금융재테크": "금융·재테크", "세금절세": "세금·절세", "보험": "보험",
    "부동산주거": "부동산·주거", "정부지원혜택": "정부지원", "gov": "정부지원",
    "tech": "IT·테크",
}


def _scene_for(keyword: str, category: str, api_key: str) -> str:
    """주제를 상징하는 영어 장면 한 문장(글자·문서·차트 금지). 실패 시 템플릿 폴백."""
    fallback = (
        f"Scene: one or two friendly cheerful Korean people with simple symbolic objects "
        f"representing the topic, warm and helpful mood."
    )
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        # 미등록 카테고리는 한글 라벨 그대로 통과(WP 허브명 '연금·절세' 등, 2026-07-17)
        cat = _CAT_LABEL.get(category, category or "생활정보")
        prompt = (
            f"한국 생활정보 블로그 글의 삽화 장면을 짓는다. 주제: '{keyword}' (카테고리: {cat}).\n"
            "이 주제를 상징하는 '플랫 벡터 일러스트' 장면을 영어 한 문장으로 묘사하라.\n"
            "규칙: 친근한 사람 1~2명 + 주제를 '직접' 상징하는 간단한 사물만. "
            "주제와 무관한 소품·배경·직업·장소는 절대 넣지 말 것(주제 어긋남 금지). "
            "글자·문서·차트·표·간판은 절대 넣지 말 것. 밝고 안전한 분위기.\n"
            "'Scene:'으로 시작하는 영어 한 문장만 출력(설명 금지)."
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite", contents=prompt
        )
        txt = (getattr(resp, "text", "") or "").strip().splitlines()
        line = next((l.strip() for l in txt if l.strip()), "")
        if line and "scene" in line.lower() and len(line) < 400:
            return line
    except Exception as e:
        logger.warning(f"일러스트 장면 생성 실패 — 템플릿 폴백: {e}")
    return fallback


def generate_editorial_illustration(
    keyword: str, category: str = "금융재테크", api_key: str = "",
    width: int = 1080,
) -> str | None:
    """주제 맞춤 플랫 벡터 일러스트 PNG 생성 → 임시파일 경로. 실패 시 None."""
    api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types as gtypes
        scene = _scene_for(keyword, category, api_key)
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_images(
            model="imagen-4.0-fast-generate-001",
            prompt=f"{_STYLE} {scene}",
            config=gtypes.GenerateImagesConfig(
                number_of_images=1, aspect_ratio="16:9", output_mime_type="image/png",
            ),
        )
        b = resp.generated_images[0].image.image_bytes
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(b)).convert("RGB")
        h = round(width * 9 / 16)
        img = img.resize((width, h), PILImage.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        img.save(tmp.name, "PNG")
        tmp.close()
        logger.info(f"에디토리얼 일러스트 생성: {keyword!r} [{category}] → {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.warning(f"에디토리얼 일러스트 생성 실패(무시): {e}")
        return None
