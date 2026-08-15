"""발행 이력 A/S 4필드 추출기 (2026-07-31 신설 — docs/NEXT_SESSION.md §1.A).

발행 시점에 글의 핵심 주장·수치·확인 예정 이벤트를 구조화 저장한다.
3~4주 뒤 공식 발표(고시·세법 개정 등)가 나오면 "기존 글 수치 / 이번 발표 수치"를
나란히 제시하는 A/S 후속 글의 원료가 된다(메르 벤치마크: A/S 유형 14%).

설계 원칙(인수인계서 지시):
- 판정 문장은 만들지 않는다 — claim은 글이 이미 말한 사실의 재진술 1문장.
  나중에 A/S 글을 쓸 때도 숫자 쌍만 나란히 제시하고 맞았다/틀렸다 판정은 쓰지 않는다.
- claim_numbers의 수치는 참조 텍스트(본문+표+요약)에 실제로 등장해야 통과 —
  LLM 출력을 믿지 않고 코드로 대조한다. claim에 참조 텍스트에 없는 수치가 있으면
  날조 신호로 보고 추출 전체를 버린다.
- 출처(source)는 본문에 명시된 것만(URL·기관명·고시번호). URL 지어내기 금지.
- 추출 실패는 발행을 막지 않는다 — 어떤 경우에도 예외를 밖으로 내지 않고
  4필드 null(EMPTY_FIELDS)로 반환한다.
- A/S 발행측 게이트(추후 구현): 수치 쌍이 구조화 저장된 entry만 후보로 삼고,
  기존 수치·새 수치 중 하나라도 없으면 스킵한다. 여기서는 저장만 담당.
"""
import calendar
import json
import logging
import re

logger = logging.getLogger("as_fields")

EMPTY_FIELDS = {
    "claim": None,
    "claim_numbers": None,
    "verify_event": None,
    "verify_date": None,
}

_SYSTEM = (
    "너는 블로그 글에서 '나중에 공식 발표로 검증할 수 있는 사실'을 구조화하는 추출기다.\n"
    "판단·전망·추천 문장은 만들지 않는다. 글에 이미 있는 사실만 재진술한다.\n"
    "반드시 JSON 객체 하나만 출력한다. 설명·마크다운 코드펜스 금지."
)

_PROMPT = """다음 블로그 글에서 아래 4가지를 추출해 JSON으로만 답하라.

{{
  "claim": "글의 핵심 주장 1문장 — 글에 이미 있는 사실의 재진술. 핵심 수치를 포함할 것",
  "claim_numbers": [{{"value": "claim에 쓰인 수치를 글의 표기 그대로(단위 포함)", "source": "글에 명시된 그 수치의 출처(URL·기관명·고시번호). 글에 출처가 없으면 null"}}],
  "verify_event": "이 글의 수치가 바뀔 수 있어 나중에 확인해야 할 공식 이벤트 1개 (예: '2026년 8월 기준 중위소득 고시 발표'). 마땅한 것이 없으면 null",
  "verify_date": "그 이벤트 확인 예정일 YYYY-MM-DD (일 단위가 불명확하면 YYYY-MM). 근거 없으면 null"
}}

규칙:
- value는 글의 표기 그대로 적는다(임의 반올림·환산·재계산 금지). 최대 5개.
- source에 URL을 지어내지 마라. 글에 없는 출처면 null로 둔다.
- verify_event는 고시·세법 개정·실적 발표처럼 시점이 특정되는 공식 이벤트만.
  '시장 상황 변화' 같은 모호한 것은 null.
- claim에 '전망된다', '~할 것 같다' 같은 예측 표현을 넣지 마라.

[제목]
{title}

[본문]
{body}
"""

_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")


def _num_tokens(text: str) -> set:
    """콤마 제거 후 숫자 토큰 집합. '1,230,834원'→{'1230834'}, '6.51%'→{'6.51'}."""
    return set(_NUM_TOKEN_RE.findall((text or "").replace(",", "")))


def _parse_json(raw: str) -> dict:
    """모델 응답에서 JSON 객체 추출 — 코드펜스·앞뒤 잡설 허용."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON 객체 없음")
    return json.loads(s[start:end + 1])


def _norm_verify_date(v) -> "str | None":
    """YYYY-MM-DD 그대로, YYYY-MM은 말일로 정규화, 그 외 형식은 버림."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    m = re.fullmatch(r"(\d{4})-(\d{2})", v)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
    return None


def validated_fields(raw: dict, ref_text: str) -> dict:
    """LLM 추출 결과를 참조 텍스트와 대조해 정제. 실패 유형별 처리:
    - claim의 수치가 참조 텍스트에 없음 → 날조 신호, 전체 폐기(EMPTY_FIELDS)
    - claim_numbers 개별 쌍의 수치가 참조 텍스트에 없음 → 그 쌍만 제거
    - verify_date 형식 불량 → null
    """
    ref_nums = _num_tokens(ref_text)

    claim = raw.get("claim")
    claim = claim.strip() if isinstance(claim, str) and claim.strip() else None
    if claim and not (_num_tokens(claim) <= ref_nums):
        bad = sorted(_num_tokens(claim) - ref_nums)
        logger.warning(f"A/S claim에 본문에 없는 수치 {bad} — 추출 전체 폐기")
        return dict(EMPTY_FIELDS)

    pairs = []
    for p in (raw.get("claim_numbers") or [])[:5]:
        if not isinstance(p, dict):
            continue
        value = p.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        toks = _num_tokens(value)
        if not toks or not (toks <= ref_nums):
            logger.warning(f"A/S 수치 {value!r} 본문 대조 실패 — 쌍 제거")
            continue
        source = p.get("source")
        source = source.strip() if isinstance(source, str) and source.strip() else None
        pairs.append({"value": value, "source": source})

    verify_event = raw.get("verify_event")
    verify_event = (verify_event.strip()
                    if isinstance(verify_event, str) and verify_event.strip() else None)

    return {
        "claim": claim,
        "claim_numbers": pairs or None,
        "verify_event": verify_event,
        "verify_date": _norm_verify_date(raw.get("verify_date")),
    }


def extract_as_fields(api_key: str, title: str, body: str, extra_text: str = "") -> dict:
    """발행 글에서 A/S 4필드 추출. 어떤 실패에도 예외 없이 4필드 dict를 반환한다.

    extra_text: 수치가 본문 밖(표·요약블록)에 있는 트랙은 그 텍스트를 함께 넘겨
    대조 기준(참조 텍스트)에 포함시킨다.
    """
    try:
        from generator.content import _gen_text
        ref_text = f"{title}\n{body}\n{extra_text}"
        prompt = _PROMPT.format(title=title, body=(f"{body}\n{extra_text}")[:7000])
        raw = _gen_text(api_key, prompt, _SYSTEM,
                        max_output_tokens=1000, temperature=0.1)
        fields = validated_fields(_parse_json(raw), ref_text)
        n = len(fields["claim_numbers"] or [])
        logger.info(f"A/S 필드 추출: claim={'있음' if fields['claim'] else '없음'} · "
                    f"수치 {n}쌍 · verify_date={fields['verify_date']}")
        return fields
    except Exception as e:
        logger.warning(f"A/S 필드 추출 실패(발행에는 무해 — null 기록): {e}")
        return dict(EMPTY_FIELDS)
