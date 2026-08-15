# -*- coding: utf-8 -*-
"""아침 증시 브리핑 생성 — 무지개로그 포맷 그대로 실험 (2026-07-29 사용자 지시).

원칙:
- 수치는 전부 market_brief 수집값(결정론). LLM은 '해석 문장'만 쓰고, 섹션별 2문장 이내
  + 국내 착지 1문장. 개연 화법(~가능성이 있습니다/~로 해석됩니다) 강제.
- 벤치마크 골격(docs/BENCHMARK_무지개로그.md): 인사 서론 → 지표 섹션(수치줄→팩트→해석→
  국내 착지) → 국내 증시 예상 → 핵심 포인트 요약 → 마무리.
- 모바일 호흡: 한 문장을 10~20자(중앙값 13자) 의미 단위로 줄분할 + 문장 묶음 사이 빈 줄.
  분할은 결정론 함수 _split_breath()가 수행(LLM에 맡기면 일관성 없음).
- 색상 대신 1단계는 🔺(상승)/🔻(하락) + [[볼드]]로 등락 대비 — SE ONE 글자색 자동화가
  뚫리면 2단계에서 빨강/파랑 전환.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("morning_brief")
KST = timezone(timedelta(hours=9))

_WEEKDAY = "월화수목금토일"


def _split_breath(sent: str, target: int = 14, maxlen: int = 22) -> list[str]:
    """문장을 어절 경계에서 10~20자 줄로 분할 — 벤치마크 중앙값 13자."""
    words = sent.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) > maxlen or (len(cur) >= target and len(cand) > target):
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [sent]


def _breathe(text: str) -> str:
    """여러 문장 → 문장별 줄분할 + 문장 사이 빈 줄."""
    # 마침표·물음표 뒤에서만 문장 분리 — '~주요 경제지표'의 '요'를 문장 끝으로 오인 방지
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    blocks = ["\n".join(_split_breath(s)) for s in sents]
    return "\n\n".join(blocks)


def _llm_interpretations(data: list[dict], one_liner: str, headlines: list[str], api_key: str) -> dict:
    """섹션별 해석·국내착지 문장 생성(수치는 입력값 참조만, 새 수치 창작 금지)."""
    from generator.content import _gen_text  # 모델 폴백 재사용
    rows = "\n".join(f"- {d['name']}: {d['price_str']} {d['pct_str']}" for d in data)
    heads = "\n".join(f"- {h}" for h in headlines[:10]) or "(없음)"
    prompt = (
        "너는 아침 증시 브리핑 작가다. 아래 '확정 수치'와 밤사이 헤드라인을 근거로, 지표별 해석을 JSON으로 써라.\n"
        f"[확정 수치]\n{rows}\n[밤사이 헤드라인]\n{heads}\n[시장 한 줄]\n{one_liner}\n\n"
        "요구사항:\n"
        "1. 각 지표 키(지표명 그대로)에 대해 {\"fact\": 움직임의 원인·배경 1문장, \"impact\": 국내 증시·업종·종목 연결 1문장}.\n"
        "   impact는 '국내에서는 ~' 류로 시작해 관련 업종/대표 종목을 짚어라(예: 반도체→삼성전자·SK하이닉스).\n"
        "2. \"intro_hook\": 서론용 핵심 특징 1문장(따옴표 강조용, 예: '지수는 혼조, 유가는 급락, 반도체는 조정').\n"
        "3. \"domestic\": '국내 증시 예상' 섹션 3~4문장 — 전일 코스피 흐름과 오늘 관전 포인트.\n"
        "4. \"points\": 투자자 핵심 포인트 3개(각 1~2문장, 📌 없이 문장만).\n"
        "5. 전부 존댓말. 해석·전망은 개연 화법(~가능성이 있습니다/~로 보입니다/~단정하기는 어렵습니다)만. "
        "확정 수치에 없는 숫자를 만들지 마라. 이모지 금지(구조가 이미 이모지를 씀).\n"
        "출력: JSON만. 코드펜스 없이."
    )
    txt = _gen_text(api_key, prompt, "증시 브리핑 해석 작가. JSON만 출력.",
                    max_output_tokens=4000, temperature=0.6)
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)


def build_morning_brief(data: list[dict], api_key: str) -> dict | None:
    """{title, body, tags, subheadings} — 포스터에 그대로 전달할 본문(마커 포함)."""
    from generator.market_brief import market_one_liner
    from scripts.market_review import _collect_headlines
    now = datetime.now(KST)
    date_str = f"{now.month}월 {now.day}일({_WEEKDAY[now.weekday()]})"
    one = market_one_liner(data)
    try:
        headlines = _collect_headlines()
    except Exception:
        headlines = []
    try:
        interp = _llm_interpretations(data, one, headlines, api_key)
    except Exception as e:
        logger.error(f"해석 생성 실패: {e.__class__.__name__}: {e}")
        return None

    kospi = next((d for d in data if "코스피" in d["name"]), None)
    body_parts: list[str] = []

    # ── 서론 (벤치마크 100% 패턴) ──
    hook = one or str(interp.get("intro_hook", "")).rstrip(".")  # 결정론 한줄 우선(짧은 구 형태 보장)
    intro = (
        "안녕하세요. 😊\n\n"
        + _breathe(f"오늘도 글로벌 주요 경제지표를 바탕으로 {date_str} 국내 증시가 어떤 영향을 받을 가능성이 있는지 함께 살펴보겠습니다.")
        + "\n\n" + _breathe("오늘 장 시작 전 확인된 글로벌 시장은") + f"\n[[\"{hook}\"]]\n" + "이라는 특징을 보였습니다."
        + "\n\n" + _breathe("한 가지 재료만 시장을 움직이는 것이 아닌 만큼 각각의 의미를 차근차근 살펴보겠습니다.") + " 📊"
    )
    body_parts.append(intro)

    # ── 지표 섹션 ──
    subheadings: list[str] = []
    us3 = [d for d in data if d["name"] in ("나스닥", "S&P500", "다우존스")]
    rest = [d for d in data if d not in us3 and "코스피" not in d["name"]]

    def _sec(title: str, rows: list[dict]) -> str:
        # 소제목은 '본문 그 줄 자체'가 텍스트로 들어가고 subheadings 리스트 매칭으로 스타일됨
        parts = [f"[구분선]\n{title}"]
        for d in rows:
            arrow = "🔺" if d["up"] else "🔻"
            parts.append(f"✅ [[{d['name']}]] {d['price_str']} [[{arrow} {d['pct_str']}]]")
            it = interp.get(d["name"], {}) if isinstance(interp.get(d["name"]), dict) else {}
            block = " ".join(x for x in (it.get("fact", ""), it.get("impact", "")) if x)
            if block:
                parts.append(_breathe(block))
        return "\n\n".join(parts)

    if us3:
        subheadings.append("🌎 미국 증시 마감")
        body_parts.append(_sec("🌎 미국 증시 마감", us3))
    for d in rest:
        title = f"{d['emoji']} {d['name']}"
        subheadings.append(title)
        body_parts.append(_sec(title, [d]))

    # ── 국내 증시 예상 ──
    subheadings.append("🇰🇷 오늘 국내 증시는?")
    dom = ["[구분선]\n🇰🇷 오늘 국내 증시는?"]
    if kospi:
        arrow = "🔺" if kospi["up"] else "🔻"
        dom.append(f"✅ [[코스피 전일 마감]] {kospi['price_str']} [[{arrow} {kospi['pct_str']}]]")
    if interp.get("domestic"):
        dom.append(_breathe(str(interp["domestic"])))
    body_parts.append("\n\n".join(dom))

    # ── 🧮 오늘의 계산 (2026-07-31 §1.C — 코드 계산·화이트리스트 게이트) ──
    # 매일 같은 템플릿에 숫자만 갈아끼우는 코너에 '매일 다른 계산 1건'을 넣는다.
    # 계산은 calc_slot 코드가 전부 하고 LLM은 관여하지 않는다(산수 오류 원천 차단).
    try:
        from generator.calc_slot import build_calc_section
        calc_sec = build_calc_section(data)
        if calc_sec:
            subheadings.append("🧮 오늘의 계산")
            body_parts.append(calc_sec)
    except Exception as e:
        logger.warning(f"계산 슬롯 생략(무해): {e}")

    # ── 핵심 포인트 + 마무리 (벤치마크 100% 패턴) ──
    subheadings.append("💙 투자자가 꼭 기억해야 할 핵심 포인트 🌈")
    pts = ["[구분선]\n💙 투자자가 꼭 기억해야 할 핵심 포인트 🌈"]
    for p in (interp.get("points") or [])[:4]:
        pts.append("📌 " + _breathe(str(p)))
    closing = _breathe("시장이 흔들릴수록 공포에 따른 충동적인 매매는 경계하는 것이 좋겠습니다. "
                       "오늘도 각자의 원칙 안에서 차분한 하루 보내시길 바랍니다.")
    pts.append(closing + " 💙")
    body_parts.append("\n\n".join(pts))

    title = f"📊 {date_str} 증시 전망 | {one or '오늘 장 전 체크포인트'} 총정리"
    if len(title) > 48:
        title = f"📊 {date_str} 증시 전망 | 장 전 필수 체크 총정리"
    return {
        "title": title,
        "body": "\n\n".join(body_parts),
        "tags": ["증시전망", "미국증시", "코스피", "나스닥", "환율", "아침브리핑", "주식초보"],
        "subheadings": subheadings,
    }
