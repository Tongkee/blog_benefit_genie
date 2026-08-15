"""WP 주제 풀 주간 자동 갱신 (2026-07-19, 사용자 지시 — 매일 1건 전환에 따른 소진 대응).

미발행 주제가 MIN_UNPOSTED(21) 미만이면, 잔여가 적은 허브부터 Gemini 검색 그라운딩으로
신규 주제를 리서치해 data/wp_topic_pool_extra.json에 추가한다(회당 최대 MAX_NEW).
- facts는 검색 근거가 확인된 수치만(불확실 수치는 넣지 않음 — 규칙 3-3과 동일 철학)
- 기존 keyword/slug와 중복 금지, deep_content가 그대로 쓰는 _t() 필드 구조로 저장
실행: EC2 주 1회(run_wp_refresh.sh). 수동: python -m scripts.wp_topic_refresh
"""
import json
import logging
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from generator.content import _gen_text
from generator.wp_topics import TOPICS, HUB_BY_WEEKDAY, hub_display

EXTRA_PATH = os.path.join(ROOT, "data", "wp_topic_pool_extra.json")
HIST_PATH = os.path.join(ROOT, "data", "wp_post_history.json")
# 2026-07-20 사용자 지시(발행량 확대 준비): 총량 게이트(구 MIN_UNPOSTED=21)에서 '허브별 목표
# 버퍼'로 전환 — 카테고리마다 미발행 재고를 TARGET_PER_HUB까지 채우되 회당 허브별 상한
# MAX_NEW_PER_HUB(주 5~10종). 발행량을 늘리려면 풀부터 커야 한다(REPUBLISH 365일 제약).
TARGET_PER_HUB = int(os.environ.get("WP_TARGET_PER_HUB", "30"))    # 허브별 미발행 버퍼 목표
MAX_NEW_PER_HUB = int(os.environ.get("WP_MAX_NEW_PER_HUB", "8"))   # 회당 허브별 상한
MAX_NEW_TOTAL = int(os.environ.get("WP_MAX_NEW_TOTAL", "42"))      # 회당 총 상한(API·시간 보호)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wp_topic_refresh")

_HUB_THEMES = {
    "pension-tax": "연금·절세 설계 (ISA·연금저축·IRP·퇴직연금·비과세 제도)",
    "insurance-risk": "보험·리스크 설계 (실손·정기·암·운전자·보험 리모델링)",
    "loan-credit": "대출·신용 전략 (주담대·전세대출·신용점수·대환·중도상환)",
    "tax-refund": "세금·환급 가이드 (연말정산·종소세·양도세·증여·공제)",
    "policy-benefit": "제도·복지 해설 (정부지원금·바우처·청년·신혼부부 정책)",
    "housing-plan": "주거·청약 전략 (청약·특공·전세안전·재개발·주거 지원)",
}


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _gen_topic(hub_id: str, existing_kw: list[str], api_key: str) -> dict | None:
    prompt = (
        f"한국 금융·생활정보 블로그의 '{_HUB_THEMES[hub_id]}' 허브에 넣을 심층분석 글 주제 1개를 "
        "검색으로 리서치해서 만들어라.\n"
        f"[이미 있는 주제 — 겹치면 안 됨]\n{', '.join(existing_kw[:60])}\n\n"
        "요구사항:\n"
        "- 2026년 한국 기준 검색 수요가 있는 실용 주제(제도·상품·전략). 뉴스성 아닌 에버그린.\n"
        "- facts: 검색으로 확인된 핵심 수치·조건 5~8개(키: 한글 짧은 라벨). "
        "★확인 안 되는 수치는 절대 넣지 말 것 — 넣은 값은 전부 근거가 있어야 한다.\n"
        "- key_stats: facts 중 대표 수치 4개, [값, 라벨] 쌍.\n"
        "- sources: 실제 공식 출처 2개, [설명, URL] 쌍(law.go.kr·nts.go.kr·기관 공식 등).\n"
        "- slug: 영문 소문자-하이픈 3~5단어.\n"
        "JSON 한 개만 출력:\n"
        '{"keyword": "…", "slug": "…", "facts": {…}, "key_stats": [[값,라벨]×4], '
        '"sources": [[설명,URL]×2], "naver_overlap": ["…","…"]}'
    )
    raw = _gen_text(api_key, prompt, "너는 금융 콘텐츠 리서처다. 검색 근거 수치만 쓰고 JSON만 출력한다.",
                    4096, 0.6, use_search=True)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        t = json.loads(m.group(0))
    except Exception:
        return None
    slug = str(t.get("slug", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,6}", slug):
        return None
    if not (t.get("keyword") and isinstance(t.get("facts"), dict) and len(t["facts"]) >= 4):
        return None
    t["slug"], t["hub_id"] = slug, hub_id
    return t


def run():
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        logger.error("GOOGLE_API_KEY 없음")
        return
    posted = set(_load(HIST_PATH, {}).keys())
    extra = _load(EXTRA_PATH, {})
    # TOPICS는 import 시 extra 풀이 이미 병합돼 있어(base+extra) 허브별 미발행 잔여를 정확히 센다.
    hubs = list(HUB_BY_WEEKDAY.values())
    unposted_by_hub = {h: sum(1 for tid, m in TOPICS.items()
                              if m["hub_id"] == h and tid not in posted) for h in hubs}
    # 허브별 부족분 = (목표 버퍼 - 잔여), 회당 허브 상한으로 클램프
    deficit = {h: min(MAX_NEW_PER_HUB, max(0, TARGET_PER_HUB - unposted_by_hub[h])) for h in hubs}
    total_need = min(MAX_NEW_TOTAL, sum(deficit.values()))
    logger.info(f"주제 풀 총 {len(TOPICS)} | 허브별 미발행 "
                + ", ".join(f"{hub_display(h)[:6]}={unposted_by_hub[h]}(+{deficit[h]})" for h in hubs)
                + f" | 이번 회 보충 목표 {total_need}")
    if total_need == 0:
        logger.info("전 허브 목표 버퍼 충족 — 보충 없음")
        return
    existing_kw = [t["keyword"] for t in TOPICS.values()]
    existing_slugs = {t["slug"] for t in TOPICS.values()}
    added_by_hub = {h: 0 for h in hubs}
    added = 0
    attempts = 0
    max_attempts = total_need * 3 + 6
    while added < total_need and attempts < max_attempts:
        # 아직 부족분이 남은 허브 중 '잔여(기존+이번 추가)가 가장 적은' 허브부터
        cand = [h for h in hubs if added_by_hub[h] < deficit[h]]
        if not cand:
            break
        hub = min(cand, key=lambda h: unposted_by_hub[h] + added_by_hub[h])
        attempts += 1
        t = _gen_topic(hub, existing_kw, api_key)
        if not t or t["slug"] in existing_slugs or t["keyword"] in existing_kw:
            continue
        tid = re.sub(r"[^a-z0-9]+", "_", t["slug"])
        if tid in TOPICS or tid in extra:
            continue
        t["auto"] = True
        extra[tid] = t
        existing_kw.append(t["keyword"])
        existing_slugs.add(t["slug"])
        added_by_hub[hub] += 1
        added += 1
        logger.info(f"신규 주제 +[{hub_display(hub)}] {t['keyword']} ({t['slug']}) "
                    f"[{added}/{total_need}]")
        # 중간 저장(장시간 실행 중 크래시·타임아웃 대비 진행분 보존)
        json.dump(extra, open(EXTRA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if added:
        json.dump(extra, open(EXTRA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        by_hub = ", ".join(f"{hub_display(h)[:6]}+{added_by_hub[h]}" for h in hubs if added_by_hub[h])
        logger.info(f"저장: +{added}개 ({by_hub}) → {EXTRA_PATH}")
    else:
        logger.warning(f"보충 목표 {total_need}이나 유효 신규 0개 (중복·검증 탈락) — 다음 회 재시도")


if __name__ == "__main__":
    run()
