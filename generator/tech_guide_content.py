"""PC 유입 특화 심층 가이드 생성기 (2026-07-19 신설, 사용자 승인).

형수의테크공장의 하우투 트랙 — 뉴스형(수명 2~3일)과 달리 검색에 오래 남는 에버그린.
전문가 컨셉: 10년차 IT 엔지니어가 원리부터 해결까지 설명하는 길고 상세한 글(2,600~3,500자).
PC 앞에서 검색하는 주제(윈도우 오류·AI 도구)라 PC 유입·긴 체류를 정조준한다.

구조 마커는 tech_content와 동일([소제목]/[표시작]/[FAQ시작]/[요약시작]/{{음영}})
→ poster.naver_blog가 그대로 처리.

★2026-07-28 구조 전면 수리(첫 발행 2건 224360142080·224360032924 사용자 "최악" 피드백 — §7 0-t):
- 목차는 모델이 쓰지 않는다 — _finalize_guide_structure가 실제 [소제목] 목록으로 결정론 재구성.
  (모델 자유 서술 목차가 소제목과 불일치 + 목차 항목 텍스트가 FAQ·미니소제목 앵커/스타일링
  첫 매치를 가로채 FAQ가 글 상단에 삽입되고 목차 일부만 볼드되는 실사고의 근본원인)
- 목차에서 '자주 묻는 질문'은 제외 — poster FAQ 앵커("자주 묻는 질문" 정확일치 첫 매치)와
  목차 리스트 항목이 충돌해 FAQ가 목차 아래로 끌려오는 배선 사고 차단.
- [[미니 소제목]] 폐지 — 소제목급 문구는 [소제목]으로 승격(파서가 잔여 [[…]] 단독줄도 승격).
- 소제목 번호(①②·N.) 금지 + 결정론 제거(프롬프트 위반 시에도 스트립).
- 본문 "N. " 줄 → 원형숫자 리터럴 정규화(§7 0-r)를 가이드 경로에도 이식
  ('1. 설명… 1. 2.' 번호 재시작 실사고 차단. 공백 없는 '1.항목'·'1)' 변형까지 커버).
- 소제목급 짧은 문구가 평문단으로 노출되면 [소제목]으로 결정론 승격(목차에도 자동 반영).
- 목차 항목 = 본문 [구분선] 직후 줄에서 재수집 → 목차와 실제 소제목 불일치가 구조적으로 불가능.
- 표는 소제목 바로 아래 배치 금지(앵커=소제목 텍스트가 목차 항목과 부분일치 충돌) —
  섹션 첫 문단 뒤로 결정론 이동.
"""
import logging
import re
import time

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER
from generator.quality import banmal_gate

logger = logging.getLogger("tech_guide")

GUIDE_BODY_MIN = 2400      # prose 하한(마커 제외) — "길고 상세하게" 지시
GUIDE_BODY_TARGET = 2800

# 소제목 앞 번호 제거: ①~⑳ / "1." "1)" / 전각 숫자 변형 (공백 유무 무관)
_HEAD_NUM_RE = re.compile(r"^\s*(?:[①-⑳]|[0-9０-９]{1,2}\s*[.)．])\s*")
# [[미니 소제목]] 단독줄 → [소제목] 승격(인라인 [[ ]]는 건드리지 않음 — poster가 평문화)
_MINI_LINE_RE = re.compile(r"^\[\[(.{2,40}?)\]\]$")
# 줄머리 아라비아 번호("1. " "2)" "1.항목") → 원형숫자 리터럴(§7 0-r). 소수점("1.5배")은 제외.
# ★[ \t]만 허용(\s 금지): MULTILINE에서 \s*는 앞 빈 줄까지 먹어 번호 줄이 앞 문단에 달라붙는다.
_STEP_NUM_RE = re.compile(r"^([ \t]*)([0-9０-９]{1,2})\s*[.)．]\s*(?=[^\s\d])")
_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
# 승격 후보에서 배제할 줄머리(불릿·번호·마커·FAQ·요약 체크)
_NOT_HEAD_PREFIX = ("·", "•", "[", "✔", "✓", "-", ">", "#", "Q:", "Q.", "A:", "A.")
# 문장 종결로 끝나면 소제목이 아니라 짧은 문장 — 승격 대상에서 제외
_SENT_TAIL = ("니다", "세요", "어요", "에요", "예요", "아요", "해요", "죠", "요", "다", "임", "함", "죵")
_HANGUL_RE = re.compile(r"[가-힣]")

_GUIDE_SYSTEM = """너는 네이버 블로그 '형수의테크공장'의 심층 가이드 작가야.
페르소나: 10년차 IT 엔지니어 '형수' — 증상만 알려주는 블로그와 달리 '왜 이런 문제가 생기는지'
원리부터 설명하고, 실무에서 검증한 순서로 해결한다. 전문적이되 초보자도 따라올 수 있게
용어는 첫 등장에서 한 줄 풀이. 말투는 차분한 전문가 존댓말(과장·호들갑 금지, 반말 종결 금지).

[글 성격 — 반드시 지켜라]
- 에버그린 하우투: 뉴스가 아니다. 유행 문구·날짜 의존 표현 최소화(버전 표기는 OK).
- ★검색으로 확인된 사실만: 메뉴 경로·명령어·설정명은 검색 근거가 있을 때만 구체적으로.
  확인 안 되면 "버전에 따라 위치가 다를 수 있다"고 일반화하라. 지어낸 메뉴 경로는 최악의 오류다.
- 명령어·코드는 한 줄씩 별도 줄에(따라 치기 쉽게).

[구조 — 이 순서 그대로. ★목차와 [구분선]은 절대 쓰지 마라 — 시스템이 자동 생성·삽입한다]
[사진1]
(도입 2~3줄: 이 문제/주제로 고생하는 상황 공감 + 이 글에서 얻는 것 명시)
[요약시작]
✔ (핵심 결론·가장 효과 큰 해결책 1줄)
✔ (소요 시간·난이도 1줄)
✔ (이 글 범위 1줄)
[요약끝]
[소제목] (첫 섹션 — 왜 이런 문제가 생기나: 원인·원리 해설, 전문가 시각 4~6문장)
[소제목] (본문 섹션 2~4개 — 해결/활용 방법. ★소주제 하나당 [소제목] 하나로 분리하라.
'수식 자동 생성'·'데이터 정리'처럼 소제목급 주제를 평문단 첫 줄로 쓰지 말 것 — 반드시 [소제목].
섹션 안 단계 나열은 ① ② ③ 원형숫자로 줄을 시작하고, 단계마다 '무엇을-어디서-왜' 1~3문장.
가장 효과 큰 방법부터. 전문가 팁·최적화·예방법도 이 안에 별도 [소제목] 섹션으로)
[소제목] 실전 체크리스트
· (그래도 안 될 때 점검 항목 — ★명사형으로 짧게, "~입니다" 금지, 한 줄 25자 이내)
· (…4~6개)
[소제목] 자주 묻는 질문
[FAQ시작]
Q: (실제 검색되는 질문)
A: (두괄식 2~3문장)
Q: … / A: … (총 3쌍)
[FAQ끝]
(마무리 2줄: 핵심 재강조 + 관련 글 예고 톤. "도움이 되길 바랍니다" 류 상투어 금지)

[작성 원칙]
0. ★모바일 가독성 최우선(WRITING_SYSTEM §6): 한 문단은 2~3줄 이내로 짧게 끊고, 문단 사이에는
   반드시 빈 줄을 둔다. 원인 해설(4~6문장)·단계 설명(1~3문장)이 길어도 한 덩어리로 붙여 쓰지 말고
   2~3문장마다 빈 줄로 문단을 나눠 벽글(wall of text)을 피한다. ※포스터는 '빈 줄(\n\n)' 기준으로만
   문단을 분리하므로, 빈 줄이 없으면 모바일에서 통짜 벽글로 렌더된다 — 빈 줄 삽입을 절대 빠뜨리지 마라.
1. 본문(마커 제외) 2,600~3,500자 — 본문 섹션 3~5개, 각 섹션을 깊게. 같은 문장 반복으로 늘리기 금지.
2. 표는 필요할 때만 1개(설정값 비교·방법 비교 등 3열, 셀 20자 이내). 억지 표 금지.
   ★[표시작]은 소제목 바로 다음 줄에 두지 말고, 섹션 첫 문단(산문) 뒤에 배치하라.
3. 불릿(·)은 체크리스트 등 나열에서만. ★모든 불릿은 명사형 종결·핵심만(전 파이프라인 공통).
4. ★소제목 텍스트에 번호 금지: ①·1.·01 등 어떤 번호도 붙이지 마라(목차·단계 번호와 혼동).
   ★본문 줄을 '1. ' '2. ' 아라비아 번호로 시작하지 마라 — 단계·순서 나열은 반드시 ① ② ③
   원형숫자(에디터 자동 목록화로 번호가 '1.'부터 재시작하는 사고 방지).
5. {{음영}}은 글 전체 3~5곳(핵심 문장만). [[미니 소제목]] 마커는 쓰지 마라 — 소구분도 [소제목]으로.
6. 금지: 안녕하세요/이처럼/이로써/혁신적인/탁월한/극대화/마크다운/이모지 남용/근거 없는 버전·수치.
7. ★교과서체 종결 상투어 금지(2026-07-24 추가 — 뉴스 트랙엔 있었으나 이 가이드 트랙만 누락돼
   'AI CLI' 글에 상투어 12회): '~하는 것이 중요합니다/좋습니다', '~하시면 됩니다', '도움이 되길
   바랍니다'로 문장·문단을 반복해 맺지 마라(한 글 1~2회 이내). 구체적 조건·수치·결과로 맺어라.

[출력 형식]
TITLE: {검색 키워드가 앞에 오는 제목, 결론·범위 암시, 32자 이내}
TAGS: {태그1},…,{태그7}
IMAGE_KEYWORDS: tech guide
IMAGE_LABELS: {키워드}
---
{본문}
"""

# 목차에서 제외할 소제목: '목차' 자신 + FAQ 헤딩(poster FAQ 앵커가 "자주 묻는 질문" 텍스트
# 첫 매치라 목차에 같은 문구가 있으면 FAQ가 목차 아래(글 상단)로 끌려오는 배선 사고 — §7 0-t)
_TOC_EXCLUDE = ("목차", "자주 묻는 질문")


def _circle_rep(m: "re.Match[str]") -> str:
    """'1. ' → '① ' (1~20 범위 밖은 원문 유지)."""
    n = int(m.group(2).translate(_FW_DIGITS))
    return f"{m.group(1)}{chr(0x2460 + n - 1)} " if 1 <= n <= 20 else m.group(0)


def _pre_normalize_raw(raw: str) -> str:
    """파싱 전 원문 정규화 — 반드시 '줄 단위'로만 처리해 문단 사이 빈 줄을 보존한다.
    ★content._parse_response의 'N. '→원형숫자 치환은 `^\\s*`가 앞의 빈 줄까지 삼켜
    번호 줄이 직전 문단에 달라붙는다(모바일 벽글 + 번호 리스트 재시작의 동반 원인).
    가이드 트랙은 여기서 먼저 ①로 바꿔 그 치환이 아무것도 못 잡게 만든다.
    같은 이유로 [[미니 소제목]] 승격도 여기서 줄 단위로 수행한다."""
    out: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        m = _MINI_LINE_RE.match(s)
        if m and m.group(1).strip():
            out.append(f"[소제목] {m.group(1).strip()}")
            continue
        out.append(_STEP_NUM_RE.sub(_circle_rep, ln, count=1) if s and not s.startswith("[") else ln)
    return "\n".join(out)


def _ensure_header_marker(parsed: dict) -> None:
    """본문 최상단 [사진1] 1개를 보장. poster의 헤더카드 경로(is_header_top = 첫 이미지 +
    빈 앵커)가 이 마커에 의존해서, 모델이 빠뜨리면 헤더 카드가 아예 삽입되지 않는다
    (2026-07-28 실생성에서 모델이 실제로 누락 — 프롬프트만으로는 보장 안 됨)."""
    body = re.sub(r"(?m)^\s*\[사진1\]\s*$\n?", "", parsed.get("body", "")).lstrip()
    parsed["body"] = "[사진1]\n" + body


def _heading_line_idx(lines: list[str]) -> list[int]:
    """본문 라인 리스트에서 소제목 줄(=[구분선] 직후 첫 비어있지 않은 줄) 인덱스를 문서 순서로."""
    out: list[int] = []
    for i, ln in enumerate(lines):
        if ln.strip() != "[구분선]":
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].strip():
                out.append(j)
                break
    return out


def _strip_heading_numbers(parsed: dict) -> None:
    """소제목 줄 앞 번호(①②·N.·1) 등)를 본문에서 직접 제거(§5 '소제목 번호 금지')."""
    lines = parsed.get("body", "").splitlines()
    for j in _heading_line_idx(lines):
        s = lines[j].strip()
        ns = _HEAD_NUM_RE.sub("", s).strip()
        if ns and ns != s:
            lines[j] = ns
    parsed["body"] = "\n".join(lines)


def _normalize_step_numbers(parsed: dict) -> None:
    """본문 줄머리 '1. '/'2)' → 원형숫자 리터럴(§7 0-r 패턴의 가이드 경로 이식).
    소제목 줄·마커 줄은 제외하고, 소수점('1.5배')은 정규식 자체가 배제한다."""
    lines = parsed.get("body", "").splitlines()
    heads = set(_heading_line_idx(lines))
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("[") or i in heads:
            continue
        lines[i] = _STEP_NUM_RE.sub(_circle_rep, ln, count=1)
    parsed["body"] = "\n".join(lines)


def _promote_orphan_subheads(parsed: dict) -> int:
    """소제목급 짧은 문구가 평문단으로 노출된 블록을 [구분선]+제목줄로 승격(라이브 결함 4).
    오탐(명령어·경로·짧은 문장)을 막기 위해 보수적 조건만 통과시킨다."""
    body = parsed.get("body", "")
    if "[구분선]" not in body:
        return 0
    blocks = body.split("\n\n")
    first_sec = next((i for i, b in enumerate(blocks) if b.strip().startswith("[구분선]")), None)
    if first_sec is None:
        return 0
    faq_at = next((i for i, b in enumerate(blocks) if "[FAQ삽입]" in b), len(blocks))
    promoted = 0
    for i in range(first_sec + 1, min(faq_at, len(blocks) - 1)):
        s = blocks[i].strip()
        if "\n" in s or not (4 <= len(s) <= 25):
            continue
        if s.startswith(_NOT_HEAD_PREFIX) or s[0].isdigit() or "①" <= s[0] <= "⑳":
            continue
        if s[-1] in ".!?~,;:…" or s.endswith(_SENT_TAIL):
            continue
        if len(_HANGUL_RE.findall(s)) < 2 or any(c in s for c in "/\\|="):
            continue          # 순수 ASCII 명령어·경로 줄(sfc /scannow 등) 보호
        prev, nxt = blocks[i - 1].strip(), blocks[i + 1].strip()
        if prev.startswith("[") or nxt.startswith("[") or nxt.startswith("· ") or len(nxt) < 30:
            continue
        blocks[i] = "[구분선]\n" + s
        promoted += 1
    if promoted:
        parsed["body"] = "\n\n".join(blocks)
        logger.info(f"평문 노출 소제목 {promoted}건 → [소제목] 승격")
    return promoted


def _sync_subheadings(parsed: dict) -> None:
    """subheadings를 본문 소제목 줄에서 재수집 — 목차·스타일링 대상이 실제 소제목과 항상 일치."""
    lines = parsed.get("body", "").splitlines()
    subs: list[str] = []
    for j in _heading_line_idx(lines):
        s = lines[j].strip()
        if s and s not in subs:
            subs.append(s)
    if parsed.get("faq_str") and "자주 묻는 질문" not in subs:
        subs.append("자주 묻는 질문")
    parsed["subheadings"] = subs


def _toc_items_in_body(body: str) -> list[str]:
    """본문에 실제로 박힌 목차 불릿 항목 텍스트(검증용)."""
    m = re.search(r"(?m)^목차\s*$\n((?:·[^\n]*\n?)+)", body)
    if not m:
        return []
    return [ln.strip()[2:].strip() for ln in m.group(1).splitlines() if ln.strip().startswith("· ")]


def _rebuild_toc(parsed: dict) -> None:
    """모델이 쓴 목차 섹션을 제거하고, 실제 소제목 목록으로 목차를 결정론 재구성.
    목차 항목 = subheadings(문서 순서) − _TOC_EXCLUDE, 각 항목에 '· ' 접두 —
    poster _style_paragraphs/앵커가 쓰는 '단락 텍스트 완전일치 첫 매치'와 겹치지 않게 한다."""
    body = parsed.get("body", "")
    # 모델이 임의로 쓴 목차 섹션([구분선]\n목차\n… 다음 [구분선] 전까지) 제거 — 방어적
    body = re.sub(r"\[구분선\]\s*\n목차\s*\n(?:(?!\[구분선\])[^\n]*\n?)*", "", body)
    # [소제목] 없이 '목차' 평문 줄 + 불릿으로 쓴 변형도 제거
    body = re.sub(r"(?m)^목차\s*\n(?:·[^\n]*\n?)+", "", body)
    toc_items = [s for s in parsed.get("subheadings", []) if s not in _TOC_EXCLUDE]
    if toc_items:
        toc_block = "[구분선]\n목차\n" + "\n".join(f"· {s}" for s in toc_items) + "\n\n"
        idx = body.find("[구분선]")
        body = (body[:idx] + toc_block + body[idx:]) if idx >= 0 else (toc_block + body)
    parsed["body"] = re.sub(r"\n{3,}", "\n\n", body)


def _relocate_tables(parsed: dict) -> None:
    """[표삽입]이 소제목 바로 아래면 섹션 첫 산문 문단 뒤로 이동.
    표 앵커(=직전 텍스트)가 소제목이면 목차 항목과 부분일치해 표가 목차로 끌려가는 충돌 방지."""
    subs = set(parsed.get("subheadings", []))
    blocks = parsed.get("body", "").split("\n\n")
    for k, b in enumerate(blocks):
        if b.strip() != "[표삽입]" or k == 0 or k + 1 >= len(blocks):
            continue
        prev_lines = [ln.strip() for ln in blocks[k - 1].strip().splitlines() if ln.strip()]
        prev_last = prev_lines[-1] if prev_lines else ""
        nxt = blocks[k + 1].strip()
        if prev_last in subs and nxt and not nxt.startswith("[") and not nxt.startswith("· "):
            blocks[k], blocks[k + 1] = blocks[k + 1], blocks[k]
    parsed["body"] = "\n\n".join(blocks)


def _finalize_guide_structure(parsed: dict) -> dict:
    """구조 수리 일괄 적용(§7 0-t). 순서에 의미가 있다:
    헤더 마커 보정 → 소제목 번호 제거 → 본문 번호 리스트 정규화 → 평문 소제목 승격
    → 소제목 재수집 → 목차 결정론 재구성 → 소제목 재수집(목차 포함) → 표 위치 보정."""
    _ensure_header_marker(parsed)
    _strip_heading_numbers(parsed)
    _normalize_step_numbers(parsed)
    _promote_orphan_subheads(parsed)
    _sync_subheadings(parsed)
    _rebuild_toc(parsed)
    _sync_subheadings(parsed)
    _relocate_tables(parsed)
    return parsed


def _structure_issues(parsed: dict) -> list[str]:
    """finalize 후 결정론 구조 검증 — 위반 목록 반환(빈 리스트 = 통과).
    앞 4개는 모델 원고 품질(재생성으로 해소), 뒤 3개는 finalize 불변식(터지면 코드 버그)."""
    issues: list[str] = []
    body = parsed.get("body", "")
    subs = parsed.get("subheadings", [])
    if not parsed.get("faq_pairs"):
        issues.append("FAQ 없음")
    else:
        fa = body.find("[FAQ삽입]")
        if fa < 0:
            issues.append("FAQ 자리표시자 없음")
        elif fa < body.rfind("[구분선]"):
            issues.append("FAQ가 글 하단(마지막 섹션 뒤)이 아님 — FAQ는 마무리 직전에 둬라")
        elif not body[fa + len("[FAQ삽입]"):].strip():
            issues.append("FAQ 뒤 마무리 없음 — FAQ 다음에 마무리 2줄을 써라")
    content_subs = [s for s in subs if s not in _TOC_EXCLUDE]
    if len(content_subs) < 4:
        issues.append(f"본문 소제목 부족({len(content_subs)}개<4) — 소주제를 [소제목]으로 분리하라")
    # ── finalize 불변식 ──
    numbered = [s for s in subs if _HEAD_NUM_RE.match(s)]
    if numbered:
        issues.append(f"소제목 번호 잔존({numbered[0]!r})")
    bad_num = [ln.strip() for ln in body.splitlines() if _STEP_NUM_RE.match(ln)]
    if bad_num:
        issues.append(f"본문 아라비아 번호 줄 잔존({bad_num[0][:18]!r})")
    if _toc_items_in_body(body) != content_subs:
        issues.append("목차 항목이 실제 소제목과 불일치")
    return issues


def generate_tech_guide(api_key: str, topic: dict) -> dict | None:
    """topic: {id, keyword, category, hint} → post dict (tech_post와 동일 스키마)."""
    user_msg = (
        f"주제 키워드: {topic['keyword']}\n"
        f"카테고리: {topic['category']}\n"
        f"다룰 포인트 힌트: {topic.get('hint', '')}\n\n"
        "위 주제로 검색 유입 독자가 문제를 실제로 해결하고 나가는 심층 가이드를 작성하라. "
        "최신 정보는 검색으로 확인해서 반영하고, 확인 안 되는 세부 경로는 일반화하라."
    )
    extra = ""
    best, best_len = None, 0
    for attempt in range(1, 4):
        try:
            raw = _gen_text(api_key, user_msg + extra, _GUIDE_SYSTEM, 8192, 0.7, use_search=True)
            if not raw:
                continue
            # 파싱 전 줄 단위 정규화(번호→원형숫자 / [[미니]]→[소제목]) — §7 0-t
            parsed = _parse_response(_pre_normalize_raw(raw))
            if not parsed:
                continue
            parsed = _finalize_guide_structure(parsed)
            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            struct = _structure_issues(parsed)
            if struct:
                extra = "\n\n[재작성] 직전 원고 구조 불량(" + " / ".join(struct) + ") — 구조를 지켜 다시."
                logger.warning(f"가이드 구조 불량({' / '.join(struct)}) — 재생성")
                continue
            # ★반말 종결 게이트(존댓말 강제, 2026-07-27) — 반말 초안은 best 후보로도 미보관
            banmal = banmal_gate(parsed.get("body", ""), parsed.get("faq_str", ""),
                                 parsed.get("summary_text", ""))
            if banmal:
                extra = ("\n\n[재작성] 직전 원고에 반말 종결 문장이 있었다("
                         + " / ".join(repr(b) for b in banmal[:3])
                         + "). 모든 문장을 존댓말(~요/~습니다)로 종결해 다시 써라(인용문만 예외).")
                logger.warning(f"가이드 반말 종결 {len(banmal)}건({banmal[0]!r} 등) — 재생성")
                continue
            if body_len < GUIDE_BODY_MIN:
                extra = (f"\n\n[재작성] 직전 원고가 {body_len}자로 짧았다. 구조·사실 유지하며 각 단계 설명과 "
                         f"원인 해설·팁을 더 깊게 늘려 {GUIDE_BODY_TARGET}자 이상으로 다시 써라.")
                logger.warning(f"가이드 본문 짧음({body_len}자) — 확장 재생성")
                if body_len > best_len:
                    best, best_len = parsed, body_len
                continue
            sub_cnt = len(parsed.get("subheadings", []))
            logger.info(f"가이드 생성 완료: {parsed.get('title')!r} ({body_len}자, 소제목 {sub_cnt})")
            parsed["seed"] = topic["keyword"]
            return parsed
        except Exception as e:
            logger.error(f"가이드 생성 실패(시도 {attempt}): {e}")
            time.sleep(15 * attempt)
    if best and best_len >= 2000:
        logger.warning(f"목표 미달이나 최선본 발행({best_len}자) — 누락 방지")
        best["seed"] = topic["keyword"]
        return best
    return None
