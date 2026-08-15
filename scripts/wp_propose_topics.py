"""
주간 주제 제안 생성기 — 풀 자동 확장의 절반(제안), 나머지 절반(검토·머지)은 사람/Claude 세션.

Gemini + Google 검색 그라운딩으로 '검색 검증된' 신규 주제를 _t() 코드 형태로 제안하고
마크다운(이슈 본문)을 파일로 출력한다. 워크플로가 GitHub 이슈로 등록.

원칙: 수치는 검색으로 확인된 것만, 출처는 "수치 — 법령·문서" 형식 (WP_PIPELINE §0·§3).
사용: python -m scripts.wp_propose_topics [출력경로=proposal.md]
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import GOOGLE_API_KEY, DATA_DIR
from generator.wp_topics import TOPICS, CATEGORY_HUBS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_propose_topics")

KST = timezone(timedelta(hours=9))
N_PER_HUB = 2  # 허브당 제안 수


def _pool_summary() -> str:
    by_hub: dict[str, list[str]] = {}
    for t in TOPICS.values():
        by_hub.setdefault(t["hub_id"], []).append(t["keyword"])
    lines = []
    for hid, hub in CATEGORY_HUBS.items():
        kws = by_hub.get(hid, [])
        lines.append(f"- {hid} ({hub['name']} — {hub['desc']}): {len(kws)}개 = {', '.join(kws)}")
    return "\n".join(lines)


def _prompt() -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return f"""너는 한국 생활금융 블로그 '현지언니'(hyunjiunni.com)의 콘텐츠 기획자다.
2030 신혼·1인가구 대상 심층분석 칼럼의 신규 주제를 제안하라. 오늘: {today}.

[현재 주제 풀 — 중복 금지]
{_pool_summary()}

[작업 절차 — 반드시 이 순서로]
1. 허브마다 후보 주제를 떠올린 뒤, **주제마다 Google 검색을 먼저 실행**해 {today[:4]}년 현재
   제도가 살아있는지·핵심 수치가 무엇인지 확인하라. 검색 없이 쓴 수치는 전부 오류로 간주된다.
2. 검색으로 확인된 주제만 남겨 허브(hub_id)당 {N_PER_HUB}개씩 제안 (총 {N_PER_HUB * len(CATEGORY_HUBS)}개 목표,
   확인 실패한 주제는 버리고 개수가 줄어도 된다).

[품질 기준 — 하나라도 어기면 그 주제는 제외]
- facts에 **구체적 숫자 수치(원·%·날짜·한도) 최소 3개** 포함. "다양한", "장기", "가능", "필요" 같은
  모호한 값 금지 — 숫자가 없는 항목은 쓰지 마라.
- 위 기존 풀에 있는 제도의 재탕·변형 금지 (예: 청년도약계좌·ISA·IRP 세액공제는 이미 있음).
- 폐지·마감된 제도 금지 (참고: 청년도약계좌 신규가입은 2025-12-31 종료됨 — 이런 것을 검색으로 걸러내는 게 네 역할).
- sources는 "어떤 수치 — 근거 법령·공식 문서명" 형식 + 공식기관 URL(기관 홈이 아니라 해당 안내 페이지).
- 검색량이 있을 실용 키워드(신청/조건/계산/비교/환급) + 계절성(향후 1~3개월 수요) 우선.

[출력 형식]
아래 항목 형식만, ```python 코드펜스 하나에 전부. `def _t` 정의나 `topics = {{` 래퍼를 쓰지 말고
딕셔너리 항목들만 출력하라(그대로 TOPICS에 붙여넣을 수 있게):

    "topic_id_snake": _t(
        "키워드(검색어형)",
        "english-slug",
        "hub_id",
        {{ "항목": "수치·설명(연도 명시)", ... }},   # facts 5개 이상
        [("수치", "라벨"), ...],                    # key_stats 3~4개
        [("어떤 수치 — 근거 법령·공식 문서명", "공식 URL"), ...],
        ["네이버중복회피키워드"],
    ),

5. 코드펜스 뒤에 주제별 한 줄씩 '검증 메모'(어떤 검색결과에서 수치를 확인했는지 출처 URL)를 붙여라."""


def generate() -> str | None:
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=GOOGLE_API_KEY)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=_prompt(),
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                temperature=0.4,
            ),
        )
        return (getattr(resp, "text", "") or "").strip() or None
    except Exception as e:
        logger.error(f"제안 생성 실패: {e}")
        return None


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "proposal.md"
    body = generate()
    if not body:
        sys.exit(1)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    header = (
        f"# 주제 제안 {today} (자동 생성 — 검토 필요)\n\n"
        f"현재 풀 {len(TOPICS)}개. 아래 제안은 Gemini+Google 검색 그라운딩으로 생성됨.\n\n"
        f"**검토 절차**: ① 수치를 출처 URL에서 재확인 ② 이상 없으면 `generator/wp_topics.py`에 붙여넣기 "
        f"③ 로컬 `python -c \"from generator.wp_topics import TOPICS\"` 임포트 확인 후 커밋.\n"
        f"Claude Code 세션에서 \"주제 제안 이슈 검토해줘\"라고 하면 검증·머지까지 자동 진행.\n\n---\n\n"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + body)
    logger.info(f"제안 저장: {out_path} ({len(body)}자)")


if __name__ == "__main__":
    main()
