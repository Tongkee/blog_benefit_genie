# -*- coding: utf-8 -*-
"""메르 골격 게이트 — 렌더러(조립 단계) 상수 + 결정론 검사 (2026-07-31, NEXT_SESSION §1.B).

메르 24건 HTML 전수 실측(docs/benchmark/analysis_mer_templates.json)으로 확인된
골격 상수를 코드에 박는다. 프롬프트가 아니라 게이트라 모델이 되돌아가지 못한다.

실측 골격(24/24):
- 첫 블록은 텍스트(대표이미지 맨 위 금지)
- 소제목 컴포넌트 0개 · 폰트 크기 변화 0 · 볼드 1/1,382문단
- 강조는 색 2종만: #700001(적갈 — 인용·핵심), #740060(자주 — A/S 재수록)
- 1문단 = 1문장, 줄 중앙 46자·상한 87자
- 이미지: 첫 장 본문 125자 뒤 → 이후 509자당 1장 → 마지막은 88.6% 지점
- 마감 '한줄 코멘트' 24/24
- 레지스터 2종 중 하나로만(섞으면 실패):
  · 메모체: 번호 1~N 연속 + 임/함(명사형) 종결 + 문단 중앙 53자
  · 서술체: 번호 금지 + '다' 종결 + 문단 중앙 41자

적용 범위(2026-07-31 결정): 요즘경제(메르 벤치마크 트랙) 전면. 아침브리핑은
무지개로그 실험 정체성(가운데정렬·✅·섹션) 유지 중이라 '첫 블록 이미지 금지'만.
기존 정보성 트랙(소제목 6개+표+FAQ 검증 구조)은 NEXT_SESSION §2
"1천까지는 지금 방식이 유효한 사다리 — 줄이지 말 것"에 따라 미적용.
"""
import re

SKELETON = {
    "para_max_chars": 87,      # 문단(=문장) 상한
    "img_first_at": 125,       # 첫 이미지: 본문 누적 125자 뒤
    "img_every": 509,          # 이후 509자당 1장
    "img_last_ratio": 0.886,   # 마지막 이미지는 본문 88.6% 지점
    "accent_red": "#700001",   # 인용·핵심 강조
    "accent_purple": "#740060",  # A/S 재수록 강조
}

# 예측·판정 표현 — 마감 코멘트는 전부 사실문장이어야 한다
_FORECAST_RE = re.compile(
    r"전망(이다|된다|입니다)|할 것 같|예상(된다|한다|됩니다)|될 것으로|"
    r"보인다|듯하다|우려된다|기대(된다|됩니다)|~?것으로 보")

# 문장 종결 카운트: 마침표·물음표·느낌표(소수점 1.5 는 제외)
_SENT_END_RE = re.compile(r"[.!?…](?=\s|$)")
# 메모체 명사형 종결(임·함·음·했음 등) / 서술체 '다' 종결
_MEMO_END_RE = re.compile(r"(임|함|음|됨|였음|했음|있음|없음)\s*[.!?…]?$")
_DA_END_RE = re.compile(r"다\s*[.!?…]$")
_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s")

_SKIP_LINE_RE = re.compile(r"^\[사진\d+\]$|^참고:|^\[구분선\]$")


def _paras(body: str) -> list:
    """빈 줄 구분 문단 목록(마커·참고 줄 제외)."""
    return [p.strip() for p in (body or "").split("\n\n")
            if p.strip() and not _SKIP_LINE_RE.match(p.strip())]


def _sentences_in(text: str) -> int:
    return max(len(_SENT_END_RE.findall(text)), 1 if text.strip() else 0)


def register_issues(body: str, register: str) -> list:
    """레지스터 순도 검사 — 'memo'(메모체) 또는 'narrative'(서술체).
    글 단위 플래그로 고정하고 종결어미 검사를 그 플래그에 묶는다(섞으면 위반)."""
    lines = [ln.strip() for ln in (body or "").splitlines()
             if ln.strip() and not _SKIP_LINE_RE.match(ln.strip())]
    if not lines:
        return ["본문 없음"]
    issues = []
    numbered = [(i, _NUMBERED_RE.match(ln)) for i, ln in enumerate(lines)]
    numbered = [(i, int(m.group(1))) for i, m in numbered if m]
    if register == "memo":
        if not numbered:
            issues.append("메모체인데 번호 목록(1~N)이 없다")
        else:
            nums = [n for _, n in numbered]
            expect = list(range(nums[0], nums[0] + len(nums)))
            if nums != expect or nums[0] != 1:
                issues.append(f"메모체 번호가 1~N 연속이 아니다: {nums[:8]}")
        da = [ln for ln in lines if _DA_END_RE.search(ln)]
        if len(da) > max(1, len(lines) // 10):
            issues.append(f"메모체에 '~다' 종결 {len(da)}줄 혼입(임/함 종결로 통일): "
                          f"{da[0][:30]!r}")
    elif register == "narrative":
        if numbered:
            issues.append(f"서술체에 번호 목록 {len(numbered)}줄 사용(번호 금지): "
                          f"{lines[numbered[0][0]][:30]!r}")
        memo = [ln for ln in lines if _MEMO_END_RE.search(ln)]
        if len(memo) > max(1, len(lines) // 10):
            issues.append(f"서술체에 명사형 종결(임/함) {len(memo)}줄 혼입: {memo[0][:30]!r}")
    else:
        issues.append(f"알 수 없는 레지스터: {register!r} (memo|narrative)")
    return issues


def skeleton_issues(body: str, register: str = "narrative") -> list:
    """골격 위반 목록 — 비면 통과. 생성 루프의 되먹임(style_feedback)으로 쓴다."""
    issues = []
    paras = _paras(body)
    if not paras:
        return ["본문 없음"]
    limit = SKELETON["para_max_chars"]
    over = [p for p in paras if max(len(l) for l in p.splitlines()) > limit]
    if over:
        issues.append(f"{limit}자 넘는 문단 {len(over)}개 — 쪼개라: {over[0][:40]}…")
    multi = [p for p in paras if _sentences_in(p) > 1]
    if multi:
        issues.append(f"1문단 1문장 위반 {len(multi)}개 — 문장마다 빈 줄로 끊어라: "
                      f"{multi[0][:40]}…")
    if "**" in body or "__" in body:
        issues.append("볼드 마커(**·__) 금지 — 강조는 렌더러 색 2종만 쓴다")
    issues += register_issues(body, register)
    return issues


def closing_comment_issues(comment: str, body: str) -> list:
    """마감 '한줄 코멘트' 슬롯 검사 — 3문장 고정 틀 + 전부 사실문장.
    틀: [본문 인용 수치 2개 재진술] + [그 두 수치의 산술 결과] + [확정된 다음 공식 일정].
    판정·전망 문장 금지(검증 불가 주장 생산기가 되므로)."""
    if not comment or not comment.strip():
        return ["마감 코멘트 없음"]
    issues = []
    n_sent = _sentences_in(comment.strip())
    if n_sent != 3:
        issues.append(f"마감 코멘트는 정확히 3문장(현재 {n_sent}문장)")
    m = _FORECAST_RE.search(comment)
    if m:
        issues.append(f"마감 코멘트에 예측·판정 표현 금지: {m.group(0)!r}")
    body_nums = set(re.findall(r"\d+(?:\.\d+)?", (body or "").replace(",", "")))
    com_nums = re.findall(r"\d+(?:\.\d+)?", comment.replace(",", ""))
    in_body = [n for n in com_nums if n in body_nums]
    if len(in_body) < 2:
        issues.append(f"본문에 있는 수치 2개 이상 재진술 필요(현재 {len(in_body)}개)")
    return issues


def closing_slot(body: str, k: int = 3) -> str:
    """마감 '한줄 코멘트' 슬롯 — '참고:' 줄·마커를 뺀 마지막 k개 문단(1문단=1문장이므로
    3문장 틀 = 마지막 3문단)을 이어 반환. closing_comment_issues 검사 대상."""
    paras = _paras(body)
    return " ".join(paras[-k:]) if paras else ""


def place_markers_by_chars(body: str, n: int, start_no: int = 1) -> tuple:
    """누적 글자수 기준 [사진N] 마커 배치 — 첫 장 125자 뒤 → 509자당 1장 →
    마지막 장은 본문 88.6% 지점. 첫 블록(첫 문단) 앞에는 절대 넣지 않는다.
    본문이 짧아 자리가 안 나오는 마커는 버린다(끝에 몰아붙이지 않음).
    반환: (본문, 배치된 마커 목록)"""
    if n < 1:
        return body, []
    paras = [p for p in (body or "").split("\n\n") if p.strip()]
    # 참고 줄은 항상 마지막 — 배치 대상 범위에서 제외
    body_end = len(paras)
    while body_end > 0 and paras[body_end - 1].strip().startswith("참고:"):
        body_end -= 1
    text_paras = [p for p in paras[:body_end] if not _SKIP_LINE_RE.match(p.strip())]
    total = sum(len(p) for p in text_paras)
    if total < SKELETON["img_first_at"] or body_end < 2:
        return body, []
    targets = [SKELETON["img_first_at"] + SKELETON["img_every"] * k for k in range(n)]
    if n >= 2:
        targets[-1] = max(total * SKELETON["img_last_ratio"], targets[-2] + 1)
    out, markers = [], []
    cum, ti, no = 0, 0, start_no
    for idx, p in enumerate(paras):
        out.append(p)
        if idx < body_end and not _SKIP_LINE_RE.match(p.strip()):
            cum += len(p)
            while ti < len(targets) and cum >= targets[ti] and idx < body_end - 1:
                m = f"[사진{no}]"
                out.append(m)
                markers.append(m)
                no += 1
                ti += 1
    return "\n\n".join(out), markers
