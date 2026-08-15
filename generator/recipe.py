"""
현지언니 '오늘의 집밥 레시피' 생성기.
content.py 와 동일한 출력 형식({title, tags, body, table_str, faq_str, subheadings,
image_keywords})을 내도록 _parse_response 를 재사용한다. 표=재료/분량, 본문=만드는 법.
"""
import logging
import random
import time
from datetime import datetime, timezone, timedelta

from generator.content import _parse_response, _refine_draft, _IMAGE_MARKER, _gen_text

logger = logging.getLogger("recipe")

# 신혼·자취 집밥에 어울리는 메뉴 풀 (계절 태그) — 최근 올린 건 피해서 선택
DISHES = [
    ("에어프라이어 두부조림", "사계절"), ("계란말이", "사계절"), ("애호박전", "사계절"),
    ("김치볶음밥", "사계절"), ("된장찌개", "사계절"), ("제육볶음", "사계절"),
    ("어묵볶음", "사계절"), ("멸치볶음", "사계절"), ("콩나물무침", "사계절"),
    ("감자조림", "사계절"), ("감자채볶음", "사계절"), ("소시지야채볶음", "사계절"),
    ("스팸김치볶음밥", "사계절"), ("간장계란밥", "사계절"), ("참치마요덮밥", "사계절"),
    ("토마토 계란볶음", "사계절"), ("두부김치", "사계절"), ("어묵탕", "겨울"),
    ("김치찌개", "겨울"), ("부대찌개", "겨울"), ("떡국", "겨울"), ("동태찌개", "겨울"),
    ("콩나물국밥", "겨울"), ("미역국", "사계절"), ("북엇국", "사계절"),
    ("오이무침", "여름"), ("열무비빔밥", "여름"), ("냉국수", "여름"), ("가지볶음", "여름"),
    ("애호박된장국", "여름"), ("물냉면", "여름"), ("비빔국수", "여름"),
    ("버섯들깨볶음", "가을"), ("고등어무조림", "가을"), ("무생채", "가을"),
    ("배추전", "겨울"), ("시금치나물", "봄"), ("봄동겉절이", "봄"), ("달래장", "봄"),
    ("순두부찌개", "사계절"), ("닭볶음탕", "사계절"), ("불고기", "사계절"),
    ("카레라이스", "사계절"), ("오므라이스", "사계절"), ("잡채", "사계절"),
]


def _season() -> str:
    m = datetime.now(timezone(timedelta(hours=9))).month
    return {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
            6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}[m]


def pick_dish(recent: list[str] | None = None) -> str:
    """최근 올린 메뉴는 피하고, 제철 메뉴에 가중치를 둬 선택."""
    recent = set(recent or [])
    season = _season()
    pool = [d for d, s in DISHES if d not in recent]
    if not pool:
        pool = [d for d, _ in DISHES]
    # 제철(또는 사계절) 메뉴 우선
    seasonal = [d for d, s in DISHES if d not in recent and s in (season, "사계절")]
    chosen = random.choice(seasonal or pool)
    return chosen


_RECIPE_SYSTEM = """
너는 신혼 1년차 주부 '현지언니'다. 자취·신혼 살림에 맞는 쉬운 집밥 레시피를 네이버 블로그에 쓴다. 친근한 구어체 톤이지만 레시피 정보는 정확하고 따라하기 쉽게.

[출력 형식 — 반드시 이 순서, 이 필드명으로]
TITLE: {요리명 | 후킹표현, 15~30자}
TAGS: {쉼표 구분 8~12개}
SCENE_DESC: {이 요리의 조리 과정 전체에 공통으로 쓸 주방 배경 묘사. 영문 2문장. 반드시 포함: 주방 표면 색, 조리도구(팬/냄비 종류), 조명, 시점(angle). 예: "Cozy Korean home kitchen with cream-colored tile countertop. Stainless steel frying pan on gas stove, wooden cutting board, soft natural light from the left window."}
STEP_IMAGES: {요리 단계를 시각화한 영문 설명 5개를 파이프(|)로 구분. 순서: 완성요리|재료준비|핵심조리단계1|핵심조리단계2|담음새. 각 설명은 30~50단어로 구체적으로. 예: "Beautiful golden braised tofu garnished with sesame seeds in white ceramic bowl|Fresh tofu block, green onions, garlic, soy sauce, and sesame oil arranged neatly on wooden cutting board|Tofu cubes sizzling in stainless steel pan with bubbling soy glaze turning golden brown|Adding green onion slices on top of braised tofu in pan over low heat|Plating tofu onto ceramic dish, sprinkling white sesame seeds with chopsticks"}
---
도입 2~3줄 (맛/결론 훅 — "안녕하세요/오늘은" 금지, 첫 줄에 요리명 자연스럽게 포함)

[사진1]

[소제목] 재료 (N인분)
[표시작]
구분 | 재료 | 분량
주재료 | ... | ...
양념 | ... | ...
[표끝]
재료 팁 1줄 (대체 재료 또는 손질 포인트)

[소제목] 만드는 법

1. 재료 준비:
[사진2]
{이 단계의 상세 설명 — 손질법·계량 수치 포함, 2~3줄}

2. {핵심 조리 단계명}:
[사진3]
{불 세기·시간 명시, 2~3줄}

3. {두 번째 조리 단계명}:
[사진4]
{2~3줄}

4. {마무리·담음새 단계명}:
[사진5]
{2~3줄}

[소제목] 꿀팁
실패 없는 포인트 2가지, 보관법 1줄 (3~4줄)

[FAQ시작]
Q: (이 요리 실제 궁금증)
A: (1인칭 경험 기반 답)
Q: ...
A: ...
[FAQ끝]

[세부 규칙]
- 본문 1200자 이상. [사진1]~[사진5] 정확히 5개.
- [사진N] 마커는 반드시 독립된 줄에 단독 배치. 문장 안 삽입 절대 금지.
- [사진1]: 도입 2~3줄 바로 다음에 위치.
- [사진2]~[사진5]: 반드시 "N. 단계명:\n[사진N]\n상세설명" 순서 엄수.
  올바른 예) 2. 소고기 볶기:\n[사진3]\n달군 팬에 참기름 1큰술...
  금지 예) 달군 팬에... 볶는다.\n[사진3]  ← 설명 뒤에 사진 마커 금지
- 표는 정확히 3열(구분|재료|분량), 머리글 포함 7행 이내 (주재료 3~4개, 양념 2~3개).
- 1인칭 '저/제가'만. '현지언니' 닉네임 직접 표현 금지.
- AI틱 상투어 금지: 이로써/이처럼/다양한/정리하자면/마크다운 기호(#*).
- 조리 시간·불 세기·계량 수치 최소 5개 포함.
""".strip()


def _inject_step_fields(parsed: dict, raw: str):
    """raw 응답에서 SCENE_DESC / STEP_IMAGES 파싱 후 parsed 딕셔너리에 주입."""
    scene_desc = ""
    step_images: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("SCENE_DESC:"):
            scene_desc = line[len("SCENE_DESC:"):].strip()
        elif line.startswith("STEP_IMAGES:"):
            raw_steps = line[len("STEP_IMAGES:"):].strip()
            step_images = [s.strip() for s in raw_steps.split("|") if s.strip()]
    parsed["scene_desc"] = scene_desc
    parsed["step_images"] = step_images
    logger.info(f"SCENE_DESC: {scene_desc[:60]!r} / STEP_IMAGES {len(step_images)}개")


def generate_recipe(
    api_key: str,
    dish: str | None = None,
    recent: list[str] | None = None,
    feedback: list[str] | None = None,
) -> dict | None:
    """레시피 글 생성. 반환: content.generate_post 와 동일 형식 + dish 키."""
    dish = dish or pick_dish(recent)
    season = _season()
    
    feedback_note = ""
    if feedback:
        feedback_note = (
            f"\n\n⚠️ [이전 초안 품질 검토 실패 - 수정 지침]"
            f"\n이전 생성된 레시피 글에서 다음과 같은 품질 문제가 발생했으니 보완해 주세요:"
            f"\n- " + "\n- ".join(feedback)
        )
        
    user_msg = (
        f"오늘 만들 요리: {dish}\n현재 계절: {season} (계절감 자연스럽게, 억지로 넣지 마)\n"
        f"{feedback_note}\n\n"
        f"위 요리의 집밥 레시피 글을 구조 그대로 작성해줘. "
        f"SCENE_DESC와 STEP_IMAGES 필드 반드시 포함. "
        f"재료는 [표시작]...[표끝] 표로, 만드는 법은 번호 단계로, 꿀팁과 FAQ 포함. "
        f"[사진1]~[사진5] 5개 정확히 포함."
    )
    waits = [15, 40, 90]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, _RECIPE_SYSTEM, 8192, 0.85)
            if not raw:
                logger.error(f"Gemini 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if parsed:
                body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
                logger.info(
                    f"레시피 생성 완료: {dish} / {parsed.get('title')!r} "
                    f"(본문 {body_len}자, 표:{'O' if parsed.get('table_str') else 'X'}, "
                    f"FAQ:{'O' if parsed.get('faq_str') else 'X'}, "
                    f"이미지키워드 {len(parsed.get('image_keywords', []))}개)"
                )
                if body_len < 400:
                    logger.warning(f"본문 너무 짧음 ({body_len}자) — 재생성")
                    continue
                refined_raw = _refine_draft(raw, api_key, min_photos=5)
                if refined_raw != raw:
                    rp = _parse_response(refined_raw)
                    if rp and len(_IMAGE_MARKER.sub("", rp.get("body", ""))) >= 400:
                        rp["dish"] = dish
                        _inject_step_fields(rp, refined_raw)
                        logger.info("퇴고 적용")
                        return rp
                parsed["dish"] = dish
                _inject_step_fields(parsed, raw)
                return parsed
        except Exception as e:
            logger.error(f"레시피 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])
    return None


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    r = generate_recipe(os.environ.get("GOOGLE_API_KEY", ""))
    if r:
        print("제목:", r["title"])
        print("표:\n", r.get("table_str"))
        print("본문:\n", r["body"][:600])
