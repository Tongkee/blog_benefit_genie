"""
생성된 블로그 글의 품질 점수화 모듈
네이버 C-Rank 기준 및 AI 패턴 탐지 기반으로 0~100점 채점
60점 이상이면 발행, 미만이면 재생성 권장
"""
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 채점 기준 (최대 100점)
_SCORE_WEIGHTS = {
    "body_length": 20,     # 본문 2000자+ = 20점, 1500자+ = 10점, 1000자+ = 5점
    "no_ai_pattern": 20,   # AI 패턴 감지 시 패턴당 -5점 (최대 -20)
    "subheadings": 10,     # 소제목 2개+ = 10점, 1개 = 5점
    "has_table": 10,       # 표 포함 = 10점
    "has_faq": 10,         # FAQ 포함 = 10점
    "personal_exp": 10,    # 1인칭 경험 표현 = 10점
    "concrete_data": 10,   # 숫자/가격/브랜드 = 10점
    "tags_count": 10,      # 태그 5개+ = 10점, 3개+ = 5점
    "title_length": 10,    # 제목 15~35자 = 10점, 10~40자 = 5점
}

# AI 패턴 — 감지 시 점수 차감
_AI_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"안녕하세요"), "인사말 시작: '안녕하세요'"),
    (re.compile(r"오늘은\s*.+에\s*대해\s*(알아|살펴|소개)"), "AI 도입부: '오늘은 ~에 대해 알아보겠습니다'"),
    (re.compile(r"것이\s*중요합니다"), "AI 교과서체: '것이 중요합니다'"),
    (re.compile(r"하는\s*것이\s*좋습니다"), "AI 교과서체: '하는 것이 좋습니다'"),
    (re.compile(r"하시면\s*됩니다"), "AI 교과서체: '하시면 됩니다'"),
    (re.compile(r"다들\s*아시다시피"), "채우기 문장: '다들 아시다시피'"),
    (re.compile(r"많은\s*분들이"), "채우기 문장: '많은 분들이'"),
    (re.compile(r"이런\s*분들께\s*추천"), "템플릿 문장: '이런 분들께 추천'"),
    (re.compile(r"힘드셨죠"), "빈 공감: '힘드셨죠?'"),
    (re.compile(r"공감되시나요"), "빈 공감: '공감되시나요?'"),
    (re.compile(r"\*\*.+\*\*"), "마크다운 사용: **굵게**"),
    (re.compile(r"[✔★○□◆◇▶]"), "특수기호 목록 사용"),
    (re.compile(r"함께\s*알아보겠습니다"), "AI 도입부: '함께 알아보겠습니다'"),
    (re.compile(r"도움이\s*되셨으면"), "AI 마무리: '도움이 되셨으면'"),
    # 공식(천편일률) 도입부 — 2026 AI/저품질 핵심 신호
    (re.compile(r"이\s*글\s*하나만"), "공식 도입부: '이 글 하나만'"),
    (re.compile(r"찾았지\s*뭐예요"), "공식 도입부: '찾았지 뭐예요'"),
    (re.compile(r"오늘은\s*제가.{0,15}(알려|소개|준비)"), "공식 도입부: '오늘은 제가 ~'"),
    (re.compile(r"끝까지\s*읽어\s*(주세요|보세요)"), "체류 구걸: '끝까지 읽어주세요'"),
    # AI 단어 (실생활에서 잘 안 쓰는 표현)
    (re.compile(r"이로써"), "AI 단어: '이로써'"),
    (re.compile(r"이처럼"), "AI 단어: '이처럼'"),
    (re.compile(r"혁신적"), "AI 단어: '혁신적'"),
    (re.compile(r"극대화"), "AI 단어: '극대화'"),
    (re.compile(r"선사(합니다|해|하는)"), "AI 단어: '선사하다'"),
    (re.compile(r"마련해\s*보세요"), "AI 단어: '마련해보세요'"),
    (re.compile(r"추천드립니다"), "AI 단어: '추천드립니다'"),
    (re.compile(r"다양한\s*(방법|이유|제품|팁|역할|기능|활용)"), "AI 표현: '다양한 ~'"),
    (re.compile(r"도움이\s*(되길|되었으면|되기를|되었기를)\s*(바랍니다|좋겠습니다)"), "AI 상투구: '도움이 되길 바랍니다'"),
    (re.compile(r"기억하세요"), "AI 지시어: '기억하세요'"),
    (re.compile(r"매우\s*(유용|효과적|중요|편리|탁월)"), "AI 수식어: '매우 ~'"),
    (re.compile(r"살펴보(도록\s*하겠습니다|겠습니다)"), "AI 진행어: '살펴보겠습니다'"),
    (re.compile(r"^(첫째|둘째|셋째|넷째|다섯째),?\s", re.MULTILINE), "AI 열거식: '첫째, 둘째'"),
    (re.compile(r"지금부터"), "AI 진행어: '지금부터'"),
    (re.compile(r"충격\s*실화"), "낚시성 표현: '충격 실화'"),
    (re.compile(r"무조건\s*100%"), "낚시성 표현: '무조건 100%'"),
    (re.compile(r"아무도\s*모르는\s*비밀"), "낚시성 표현: '아무도 모르는 비밀'"),
    (re.compile(r"클릭\s*안\s*하면\s*손해"), "낚시성 표현: '클릭 안 하면 손해'"),
    (re.compile(r"절대\s*놓치지\s*마세요"), "낚시성 표현: '절대 놓치지 마세요'"),
]

# 소제목 패턴 (질문형 소제목 우대)
_SUBHEADING_PATTERN = re.compile(
    r"^[^\n]{3,30}\??\s*$",  # 짧은 단독 줄 (소제목 후보)
    re.MULTILINE,
)

# 1인칭 경험 표현 키워드
_PERSONAL_KEYWORDS = re.compile(
    r"저\s|제가\s|저는\s|남편|신혼|우리\s*집|우리\s*남편|제\s*경험|작년|올해|지난\s*달|"
    r"직접\s*써|실제로\s*써|구매해봤|해봤는데|했는데|사봤|써봤"
)

# 구체적 데이터 — 숫자/가격/브랜드 (AEO 최적화 핵심 팩트)
_CONCRETE_DATA = re.compile(
    r"\d+[,\d]*원|\d+만\s*원|\d+천\s*원|"  # 가격
    r"\d{4}년|\d+월|\d+일|\d+주|\d+일간|\d+개월|"  # 날짜/기간
    r"다이소|이케아|쿠팡|무인양품|JAJU|자주|올리브영|스타벅스|"  # 브랜드명
    r"\d+분\s*만에|\d+배|\d+%\s*|\d+개|\d+곳|\d+종|\d+회|\d+평|\d+호"  # 수량/비율/단위
)

# 표 마커
_TABLE_MARKER = re.compile(r"\[표시작\].*?\[표끝\]", re.DOTALL)
# FAQ 마커
_FAQ_MARKER = re.compile(r"\[FAQ시작\].*?\[FAQ끝\]", re.DOTALL)


# ── 반말 종결 검출 (존댓말 블로그 결정론적 게이트, 2026-07-27) ─────────────────
# 배경: 존댓말 블로그 실발행 글에 반말 문장이 혼입된 실사고. 존댓말 강제가 프롬프트
# 지시 1겹뿐이라, 생성 후 반말을 잡는 결정론적 검수를 여기에 둔다(3겹 방어의 1겹).
# 원칙: 오탐(존댓말·명사 종결을 반말로 판정)이 재생성 루프를 무한 유발하므로
#       재현율보다 정밀도 우선 — 고신뢰 종결 패턴만 잡는다.
# 통과: ~요/~죠/~습니다/~세요/~는데요 등 존댓말, 명사·체언 단독 종결("총 600만원."),
#       FAQ 답변 "네." / "아닙니다.", 인용부호("…", '…') 안 인용문.
_BANMAL_TAIL_RE = re.compile(
    r"(?:"
    # 평서형 ~다 종결: ~했다/~이다/~있다/~없다/~된다/~같다/~한다 등.
    # ~습니다/~입니다/~됩니다 등 합쇼체는 전부 '니다'로 끝나므로 lookbehind로 제외.
    # '마'·'보' 제외: 체언 종결 "~마다."/"~보다."(비교) 오탐 방지 (반말 용언에 이 어간 없음)
    r"(?<![니마보])다"
    # ~했어/~됐어/~있어/~없어 류 (용언 활용 어간 한정 — 명사 오탐 방지)
    r"|(?:했|됐|였|졌|왔|갔|봤|났|샀|섰|줬|웠|았|었|있|없|많|좋|같)어"
    # 종결어미 고유형 (명사와 충돌 없음)
    r"|거든|잖아|더라|라니까|다니까|거야|이야"
    # ~지 종결: 용언 어간 한정 ('단지'·'이미지'·'에너지' 등 명사 통과, '페이지'는 lookbehind 제외)
    r"|(?:거|(?<!페)이|었|았|겠|렇|되|하|없|있|좋|르)지"
    # ~해 종결: '~해야 해/안 해/못 해/~고 해/필요해' 패턴 한정 ('올해'·'손해' 등 명사 통과)
    r"|(?:야|안|못|고|요)\s?해"
    # ~돼 종결 ("하면 돼", "안 돼" — 돼로 끝나는 명사 없음)
    r"|돼"
    # ~네 감탄 종결: 용언 어간 한정 ('동네'·'언니네' 등 명사 통과, FAQ 단답 "네."는 1글자라 미매칭)
    r"|(?:좋|하|되|있|없|겠|았|었|가|오|르)네"
    r")$"
)
# 인용부호 안 인용문 — 검출 제외 대상 (같은 줄 안에서 짝이 맞는 인용만 제거)
_QUOTED_SPAN_RE = re.compile(
    r"\"[^\"\n]{0,120}\"|“[^”\n]{0,120}”|'[^'\n]{0,120}'|‘[^’\n]{0,120}’"
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_LINE_PREFIX_RE = re.compile(r"^(?:[·•✔✓○▶]|[①-⑳]|Q\s*[:.]|A\s*[:.])\s*")


def find_banmal_sentences(text: str, limit: int = 8) -> list[str]:
    """본문에서 평서형 반말 종결 문장을 검출해 반환(없으면 빈 리스트 = 통과).

    - 마커 줄([사진N]/[구분선]/[표삽입] 등)·표 행('|' 포함)은 검사 제외
    - 큰따옴표/작은따옴표 안 인용문은 제거 후 검사(인용 반말 허용)
    - 존댓말(~요/~죠/~니다/~세요)·명사 종결·FAQ 단답("네.")은 통과
    limit개까지만 수집(리포트·피드백용)."""
    if not text:
        return []
    found: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("[") or "|" in s:
            continue
        s = _LINE_PREFIX_RE.sub("", s)
        s = _QUOTED_SPAN_RE.sub(" ", s)
        for sent in _SENT_SPLIT_RE.split(s):
            sent = sent.strip()
            if len(sent) < 2:
                continue
            # 종결 판정은 문장 끝 한글 연속부 기준(뒤 붙은 문장부호·숫자·괄호·ㅋㅋ 제거)
            core = re.sub(r"[^가-힣]+$", "", sent)
            if len(core) < 2:
                continue
            if _BANMAL_TAIL_RE.search(core):
                found.append(sent if len(sent) <= 40 else sent[:37] + "...")
                if len(found) >= limit:
                    return found
    return found


def banmal_gate(body: str, faq_str: str = "", summary_text: str = "") -> list[str]:
    """반말 종결 게이트 공용 헬퍼 — 본문+FAQ+요약을 한 번에 검사.
    반환: 반말 문장 리스트(비어 있으면 통과). 각 발행 경로(info/gov/tech/cheongyak 등)의
    재생성 루프에서 호출해 1문장이라도 있으면 재생성 피드백으로 연결한다."""
    found = find_banmal_sentences(body)
    if faq_str:
        found += find_banmal_sentences(faq_str)
    if summary_text:
        found += find_banmal_sentences(summary_text)
    return found


# ── 노매새드 벤치마킹 4종 — 서론 훅 로테이션 + 구조 결정론 게이트 (2026-07-28) ─────
# 대상: 활성 정보성 파이프라인(info 4종 + gov)만. 스펙 상세 = WRITING_SYSTEM.md §5·§7 0-q.
# ①본문 소제목 5개 '01 '~'05 '(점 없음 — 'N.' 점 형식은 SE 오토포맷 실사고로 금지 유지)
# ②서론 훅 3종(a따옴표 질문/b페르소나 시나리오/c숫자 경험) 로테이션 — 직전 훅과 다르게
# ③표 2개(2열 요약표+3열 계산표) + ❓용어 정의 줄(1행 표는 SE ONE 행삭제 불가로 대체)
# ④'저라면' 2회+ / 마무리 '결국 ~'+'A → B → C' 확인 체인

INTRO_HOOK_SPECS: dict[str, str] = {
    "a": "따옴표 질문 훅 — 독자가 실제 검색·질문할 법한 한 문장을 큰따옴표로 묶어 시작하라. "
         "예) \"월세 살면서 청약통장, 계속 부어야 하나요?\"",
    "b": "페르소나 시나리오 훅 — 구체적인 가상 인물의 상황 1문장으로 시작하라. "
         "예) 직장 3년 차 김 대리는 월급날마다 통장 잔고를 보고 한숨부터 쉽니다.",
    "c": "숫자 경험 훅 — 구체적인 숫자가 든 1인칭 경험 1문장으로 시작하라. "
         "예) 제가 직접 계산해 보니 1년에 47만원을 그냥 흘려보내고 있었습니다.",
}
_HOOK_ORDER = ("a", "b", "c")
# info 워크플로의 'git add data/info_*_history.json' 글롭에 걸리도록 이 이름을 쓴다(CI 영속).
# gov 워크플로는 이 파일을 커밋하지 않으므로 gov는 날짜 기반 폴백이 실질 로테이션이 된다.
_HOOK_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "info_hook_history.json"
)


def pick_intro_hook(pipeline_key: str) -> tuple[str, str]:
    """직전과 다른 서론 훅 유형을 고른다. 반환 (hook_id, 훅 지시문).
    상태 파일의 최근(3일 내) 기록이 있으면 a→b→c→a 로테이션, 없으면(gov CI처럼 커밋이 안 돼
    상태가 항상 오래된 경우 포함) 날짜 기반 결정론 폴백 — 연속 실행일마다 다른 훅이 보장된다."""
    today = datetime.now(KST)
    last = None
    try:
        with open(_HOOK_STATE_PATH, encoding="utf-8") as f:
            ent = json.load(f).get(pipeline_key) or {}
        d = datetime.strptime(ent.get("date", ""), "%Y-%m-%d")
        if ent.get("hook") in _HOOK_ORDER and (today.date() - d.date()).days <= 3:
            last = ent["hook"]
    except Exception:
        last = None
    if last:
        hook = _HOOK_ORDER[(_HOOK_ORDER.index(last) + 1) % len(_HOOK_ORDER)]
    else:
        hook = _HOOK_ORDER[(today.timetuple().tm_yday + sum(ord(c) for c in pipeline_key)) % len(_HOOK_ORDER)]
    return hook, INTRO_HOOK_SPECS[hook]


def record_intro_hook(pipeline_key: str, hook: str) -> None:
    """생성 성공 시에만 호출 — 이번에 쓴 훅을 상태 파일에 기록(다음 회차 로테이션 기준)."""
    try:
        state = {}
        if os.path.exists(_HOOK_STATE_PATH):
            with open(_HOOK_STATE_PATH, encoding="utf-8") as f:
                state = json.load(f)
        if not isinstance(state, dict):
            state = {}
        state[pipeline_key] = {"hook": hook, "date": datetime.now(KST).strftime("%Y-%m-%d")}
        with open(_HOOK_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"서론 훅 상태 저장 실패(무시): {e}")


_NOMAD_SUB_NUM_RE = re.compile(r"^0([1-5])\s")
_ARROW_CHAIN_RE = re.compile(r"→[^\n]*→")  # 한 줄에 화살표 2개 이상 = 확인 체인


_ANY_SUB_NUM_RE = re.compile(r"^(?:\d{1,2}[.\s]|[①②③④⑤⑥⑦⑧⑨⑩])")


def find_nomad_structure_issues(subheadings: list[str], body: str, table_count: int,
                                require_numbers: bool = True) -> list[str]:
    """노매새드 4종 구조 결정론 게이트(info·gov 공용). 반환: 위반 목록(비면 통과).
    각 항목은 재생성 피드백 문구로 그대로 되먹일 수 있게 '무엇을 어떻게'로 서술한다.
    require_numbers: gov=True(01~05 번호 유지), info=False(2026-07-29 사용자 지시로 번호 폐기
    — 프롬프트만 고치고 이 게이트를 안 고쳐 재생성 4회 전멸한 실사고 후 파라미터화)."""
    issues: list[str] = []
    body = body or ""
    if require_numbers:
        numbered: dict[int, str] = {}
        for s in subheadings or []:
            m = _NOMAD_SUB_NUM_RE.match((s or "").strip())
            if m:
                numbered[int(m.group(1))] = s.strip()
        if sorted(numbered) != [1, 2, 3, 4, 5]:
            issues.append(
                f"본문 소제목 번호 불량(01~05 각 1개 필요, 현재 {sorted(numbered)}) — "
                "본문 소제목 5개는 '01 '~'05 '(두 자리+공백, 점 금지)로 시작, FAQ 소제목은 번호 없이"
            )
        else:
            q_cnt = sum(1 for s in numbered.values() if s.endswith("?"))
            if q_cnt < 3:
                issues.append(f"질문형 소제목 {q_cnt}개 — 01~05 중 3개 이상은 '~까?/~나요?' 질문형으로")
    else:
        body_subs = [s.strip() for s in (subheadings or [])
                     if s and "자주 묻는" not in s and "함께 보면" not in s]
        bad = [s for s in body_subs if _ANY_SUB_NUM_RE.match(s)]
        if bad:
            issues.append(f"소제목에 번호 발견({bad[0]!r} 등 {len(bad)}개) — "
                          "소제목 앞 번호('01 '·'1.'·① 등) 전부 제거")
        q_cnt = sum(1 for s in body_subs[:5] if s.endswith("?"))
        if q_cnt < 3:
            issues.append(f"질문형 소제목 {q_cnt}개 — 본문 소제목 5개 중 3개 이상은 '~까?/~나요?' 질문형으로")
    if table_count != 2:
        issues.append(
            f"표 {table_count}개 — [표시작]~[표끝] 정확히 2쌍: "
            "01 섹션 2열 요약표(구분|내용) + 03 섹션 3열 계산표(구분|계산|결과)"
        )
    intro = body.split("[구분선]", 1)[0]
    if "결론부터 말하면" not in intro:
        issues.append("서론 4문장 안에 '결론부터 말하면 ~입니다. 다만 ~' 문장이 없음")
    if "정리해보겠습니다" not in intro and "정리해 보겠습니다" not in intro:
        issues.append("서론 마지막 문장이 '~정리해보겠습니다.'로 끝나지 않음")
    if body.count("저라면") < 2:
        issues.append(f"'저라면' {body.count('저라면')}회 — 개인 판단 문장('저라면 ~하겠습니다') 2회 이상 필요")
    if "결국" not in body:
        issues.append("마무리에 '결국 ~'으로 시작하는 결론 문장이 없음")
    if not _ARROW_CHAIN_RE.search(body):
        issues.append("마무리 확인 체인 한 줄('단계1 → 단계2 → 단계3' 형식)이 없음")
    if not any(ln.strip().startswith("❓") for ln in body.splitlines()):
        issues.append("전문용어 정의 줄 없음 — 핵심 용어 첫 등장 바로 다음 줄에 '❓ 용어: 한 줄 정의' 단독 줄")
    return issues


def score_content(
    title: str,
    body: str,
    tags: list[str],
    table_str: str = "",
    faq_str: str = "",
    category: str = "",
) -> dict:
    """
    블로그 글 품질 점수화.
    
    category 파라미터를 기반으로 A/B/C/D 패턴별 가중치/필수 요소를 동적으로 판별합니다.
    """
    c = category.strip()
    if c in ["신혼일상", "일상", "신혼 일상"]:
        pattern = "D"  # 일상/리뷰 (표/FAQ 제외)
    elif c in ["요리식비", "오늘의 집밥 레시피", "cooking", "요리&식비절약", "요리&식비"]:
        pattern = "B"  # 요리/레시피 (표 필수, FAQ 제외)
    elif c in ["절약재테크", "재테크/절약", "절약&재테크"]:
        pattern = "C"  # 재테크/절약 (표 필수, FAQ 필수)
    else:
        pattern = "A"  # 살림/청소/생활 (표 필수, FAQ 제외)

    score = 0
    issues: list[str] = []
    # 점수는 통과(>=60)여도, 아래 '중대(수정 가능)' 이슈가 있으면 재생성을 유도하기 위한 목록.
    critical: list[str] = []

    # 1. 본문 길이 (패턴 D, A, B는 최대 30점, 패턴 C는 최대 20점)
    # ★목표 글자수는 카테고리별로 다름(WRITING_SYSTEM §6 모바일 스캔형, 정보밀도>볼륨):
    #   B(레시피)=1200 / D(일상)=1300 / A(살림)=1500 / C(절약)=1800.
    # full=목표 이상, -10=목표-300 이상, -20=목표-600 이상, 그 미만은 매우 짧음.
    body_len = len(body)
    max_body_score = 30 if pattern in ["D", "A", "B"] else 20
    body_target = {"B": 1200, "D": 1300, "A": 1500, "C": 1800}.get(pattern, 1500)
    if body_len >= body_target:
        score += max_body_score
    elif body_len >= body_target - 300:
        score += (max_body_score - 10)
        issues.append(f"본문 약간 짧음 ({body_len}자, 목표 {body_target}자+)")
    elif body_len >= body_target - 600:
        score += (max_body_score - 20)
        issues.append(f"본문 짧음 ({body_len}자, 목표 {body_target}자+)")
        critical.append(f"본문 짧음 ({body_len}자) — {body_target}자+로 보강(경험담·꿀팁 추가)")
    else:
        issues.append(f"본문 매우 짧음 ({body_len}자, 목표 {body_target}자+) — 발행 비권장")
        critical.append(f"본문 매우 짧음 ({body_len}자) — {body_target}자+로 대폭 보강 필요")

    # 2. AI 패턴 감지 (패턴 D는 최대 30점, 패턴 A, B, C는 최대 20점)
    ai_base = 30 if pattern == "D" else 20
    ai_deduct = 0
    for pattern_regex, desc in _AI_PATTERNS:
        if pattern_regex.search(body) or pattern_regex.search(title):
            ai_deduct = min(ai_deduct + 5, 20)
            issues.append(f"AI 패턴 감지: {desc}")
    score += max(0, ai_base - ai_deduct)

    # 2-1. ★반말 종결 게이트 (존댓말 블로그 강제 — 1문장이라도 있으면 불통과 수준 감점 + 재생성)
    banmal = banmal_gate(body, faq_str)
    if banmal:
        score -= min(15 * len(banmal), 30)
        msg = f"반말 종결 문장 {len(banmal)}개 감지: " + " / ".join(f"'{b}'" for b in banmal[:3])
        issues.append(msg)
        critical.append(
            "반말 종결 문장을 전부 존댓말(~요/~습니다)로 교정(인용문 제외): "
            + " / ".join(f"'{b}'" for b in banmal[:3])
        )

    # 3. 소제목 존재 (최대 10점)
    subheading_matches = re.findall(r"^\S.{2,25}\??\s*$", body, re.MULTILINE)
    subheadings = [s for s in subheading_matches if 5 <= len(s.strip()) <= 30]
    if len(subheadings) >= 2:
        score += 10
    elif len(subheadings) == 1:
        score += 5
        issues.append("소제목 1개 — 2개 이상 권장")
    else:
        issues.append("소제목 없음 — 질문형 소제목 추가 권장")

    # 4. 표 포함 (패턴 A, B, C는 10점, 패턴 D는 체크하지 않음)
    has_table = bool(table_str) or bool(_TABLE_MARKER.search(body))
    if pattern in ["A", "B", "C"]:
        if has_table:
            score += 10
        else:
            issues.append("표 없음 — 비교표 추가 권장")

    # 5. FAQ 포함 (패턴 C는 10점, 패턴 A, B, D는 체크하지 않음)
    has_faq = bool(faq_str) or bool(_FAQ_MARKER.search(body))
    if pattern == "C":
        if has_faq:
            score += 10
        else:
            issues.append("FAQ 없음 — FAQ 섹션 추가 권장")

    # 6. 1인칭 경험 표현 (패턴 D는 20점, 패턴 A, B, C는 10점)
    personal_count = len(_PERSONAL_KEYWORDS.findall(body))
    max_personal_score = 20 if pattern == "D" else 10
    if personal_count >= 3:
        score += max_personal_score
    elif personal_count >= 1:
        score += (max_personal_score - 10)
        issues.append(f"1인칭 경험 표현 부족 ({personal_count}회) — '저', '남편', '신혼' 등 추가")
    else:
        issues.append("1인칭 경험 표현 없음 — 개인 경험담 추가 필요")

    # 7. 구체적 데이터 및 AEO 정보 밀도 (10점)
    sentences = [s.strip() for s in body.split(".") if s.strip()]
    fact_sentences = [s for s in sentences if _CONCRETE_DATA.search(s)]
    data_count = len(_CONCRETE_DATA.findall(body))
    fact_ratio = len(fact_sentences) / len(sentences) if sentences else 0

    if data_count >= 6 and fact_ratio >= 0.15:
        score += 10
    elif data_count >= 4 or fact_ratio >= 0.10:
        score += 7
        if data_count < 6:
            issues.append(f"AEO 팩트 데이터 보강 가능 ({data_count}개, 비율 {fact_ratio:.1%})")
    elif data_count >= 2:
        score += 4
        issues.append(f"AEO 팩트 데이터 부족 ({data_count}개, 비율 {fact_ratio:.1%}) — 수치(가격, 시간, 단위) 추가 권장")
    else:
        issues.append("AEO 구체적 팩트 데이터 거의 없음 — 숫자/가격/시간/브랜드명 추가 필수")
        critical.append("AEO 팩트 데이터 거의 없음 — 분량/시간/가격 등 구체 수치를 본문에 추가")

    # 8. 태그 수 (최대 10점)
    tag_count = len(tags)
    if tag_count >= 5:
        score += 10
    elif tag_count >= 3:
        score += 5
        issues.append(f"태그 부족 ({tag_count}개) — 5개 이상 권장")
    else:
        issues.append(f"태그 너무 적음 ({tag_count}개)")

    # 9. 제목 길이 (최대 10점)
    title_len = len(title)
    if 15 <= title_len <= 35:
        score += 10
    elif 10 <= title_len <= 40:
        score += 5
        issues.append(f"제목 길이 미흡 ({title_len}자, 권장 15~35자)")
    else:
        issues.append(f"제목 길이 부적합 ({title_len}자, 권장 15~35자)")

    # 10. 네이버 블로그 SEO 키워드 노출 및 스태핑 검사
    keyword = ""
    if "|" in title:
        keyword = title.split("|")[0].strip()
    else:
        keyword = title.strip()

    if keyword:
        # 특수문자 제거 후 글자만 매칭하여 공백 유연성 제공
        kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword)
        if kw_clean:
            # 검색 엔진처럼 각 글자 사이에 공백이 들어갈 수 있도록 정규식 생성
            kw_pattern = re.compile(r"\s*".join(re.escape(char) for char in kw_clean), re.IGNORECASE)
            
            # 본문에서 모든 마커(대괄호로 둘러싸인 항목)를 임시 제거하고 순수 텍스트 추출
            body_clean = re.sub(r'\[.*?\]', '', body).strip()
            
            # 첫 문단(300자 이내)에 키워드가 있는지 확인
            first_300 = body_clean[:300]
            if not kw_pattern.search(first_300):
                score -= 10
                msg = f"네이버 SEO 오류: 첫 300자 내 핵심 키워드('{keyword}')가 미배치됨"
                issues.append(msg)
                critical.append(msg + " — 도입부에 키워드 자연스럽게 1회 배치")

            # 키워드 반복 빈도 확인 (과다 반복 - 6회 초과 시 감점, 0회 시 감점)
            occurrences = len(kw_pattern.findall(body_clean))
            if occurrences > 6:
                score -= 10
                msg = f"네이버 SEO 오류: 핵심 키워드('{keyword}') 과다 반복 ({occurrences}회, 권장 3~5회)"
                issues.append(msg)
                critical.append(f"키워드('{keyword}') 과다 반복 {occurrences}회 → 3~5회로 줄이고 대명사·동의어로 대체")
            elif occurrences == 0:
                score -= 10
                msg = f"네이버 SEO 오류: 본문에 핵심 키워드('{keyword}')가 전혀 사용되지 않음"
                issues.append(msg)
                critical.append(f"핵심 키워드('{keyword}')를 본문에 3~5회 자연스럽게 사용")

    # 점수 범위 보정 (0~100)
    score = max(0, min(100, score))
    passed = score >= 60
    # 점수는 통과여도 수정 가능한 중대 이슈가 있으면 재생성을 권고(needs_retry).
    needs_retry = bool(critical)

    logger.info(
        f"품질 점수: {score}/100 ({'통과' if passed else '재생성 권장'}"
        f"{', 중대이슈 재생성권고' if (passed and needs_retry) else ''}) | 패턴: {pattern} | "
        f"본문 {body_len}자 | AI패턴 {ai_deduct//5}개 | "
        f"소제목 {len(subheadings)}개 | 데이터 {data_count}개"
    )
    if issues:
        logger.info(f"품질 이슈: {' / '.join(issues)}")
    if needs_retry:
        logger.info(f"중대(수정가능) 이슈: {' / '.join(critical)}")

    return {
        "score": score,
        "issues": issues,
        "critical": critical,
        "needs_retry": needs_retry,
        "pass": passed,
        "detail": {
            "body_length": body_len,
            "ai_patterns_found": ai_deduct // 5,
            "subheadings": len(subheadings),
            "has_table": has_table,
            "has_faq": has_faq,
            "personal_count": personal_count,
            "data_count": data_count,
            "tag_count": tag_count,
            "title_length": title_len,
            "pattern": pattern,
        },
    }


# ── 주식(stock) 전용 품질 게이트 ─────────────────────────────────────────────

_INLINE_EMPHASIS = re.compile(r"\[\[(.+?)\]\]")
_BUY_REC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"지금\s*(사|매수)"), "직접 매수 권유: '지금 사/매수'"),
    (re.compile(r"무조건\s*(매수|담|사)"), "단정적 매수 권유"),
    (re.compile(r"풀\s*매수"), "풀매수 권유"),
    (re.compile(r"적극\s*매수\s*추천"), "매수 추천"),
    (re.compile(r"반드시\s*(담|사)"), "강제 매수 표현"),
]
_YEAR_IN_TITLE = re.compile(r"20\d{2}")


def strip_title_emphasis_markers(title: str) -> str:
    """제목에 남은 [[강조]] 마커 제거(포스터 입력 전·품질검사 전 공통)."""
    return _INLINE_EMPHASIS.sub(r"\1", title).strip()


def strip_body_emphasis_markers(body: str, max_markers: int = 10) -> str:
    """본문 [[강조]] 마커를 텍스트만 남기고 제거. max_markers 초과 시 전부 제거(볼드 포기·노출 방지)."""
    if not body:
        return body
    if len(_INLINE_EMPHASIS.findall(body)) > max_markers:
        return _INLINE_EMPHASIS.sub(r"\1", body)
    return body


def sanitize_anchor_text(text: str) -> str:
    """이미지·표 앵커 매칭용 — [[ ]]·접두사 제거."""
    if not text:
        return ""
    t = _INLINE_EMPHASIS.sub(r"\1", text)
    t = re.sub(r"^\[가운데\]\s*", "", t)
    return t.strip()


_STALE_TITLE_YEAR = re.compile(r"(20\d{2})\s*년")
_TODAY_IPO_DEADLINE = re.compile(r"오늘\s*[\(（]?\d*\s*일[\)）]?\s*마감|오늘\s*청약\s*마감|오늘\s*마감")


def validate_info_dates(title: str, body: str) -> list[str]:
    """정보성 글 제목·본문 날짜 오류(critical). 구식 연도."""
    critical: list[str] = []
    current_year = datetime.now(KST).year
    for m in _STALE_TITLE_YEAR.finditer(title or ""):
        y = int(m.group(1))
        if y < current_year - 1:
            critical.append(f"제목 구식 연도({y}년) — {current_year}년 기준으로 수정")
            break
    return critical


def validate_ipo_date_claims(body: str) -> list[str]:
    """공모주 글 — 팩트 없이 '오늘 마감' 등 기준일·청약일 혼동 표현."""
    if _TODAY_IPO_DEADLINE.search(body or ""):
        return ["공모주 '오늘 마감/청약' 표현 — 팩트 데이터 청약일만 사용"]
    return []


def _flatten_fact_strings(obj, out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).startswith("_"):
                continue
            _flatten_fact_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_fact_strings(v, out)
    elif obj is not None:
        s = str(obj).strip()
        if s and re.search(r"\d", s):
            out.append(s)
    return out


def _parse_float_metric(fact_data: dict | list, *keys: str) -> float | None:
    if not isinstance(fact_data, dict):
        return None
    for key in keys:
        raw = fact_data.get(key)
        if raw is None:
            continue
        m = re.search(r"-?\d+(?:\.\d+)?", str(raw).replace(",", ""))
        if m:
            try:
                return float(m.group())
            except ValueError:
                continue
    return None


def validate_stock_facts(body: str, table_str: str, fact_data: dict | list) -> dict:
    """팩트 데이터 vs 본문·표 교차검증. needs_retry 유발 critical 반환."""
    issues: list[str] = []
    critical: list[str] = []
    combined = f"{table_str}\n{body}"

    # 핵심 수치가 본문/표에 반영됐는지(할루시네이션 1차 방어)
    anchor_keys = (
        "현재가", "현재가(USD)", "등락률(%)", "공모가", "경쟁률",
        "펀드보수", "괴리율", "PER", "PBR",
    )
    if isinstance(fact_data, dict):
        for key in anchor_keys:
            val = fact_data.get(key)
            if val is None or str(val).strip() in ("", "-", "N/A", "None"):
                continue
            num = re.search(r"-?\d+(?:\.\d+)?", str(val).replace(",", ""))
            if num and num.group() not in combined.replace(",", ""):
                msg = f"팩트 '{key}'={val} 값이 본문·표에 없음"
                issues.append(msg)
                critical.append(msg + " — 표/본문에 팩트 수치 반영")

    # PBR/PER 해석 sanity (MSTR 등 고PBR·적자 종목 오판 방지)
    if isinstance(fact_data, dict):
        pbr = _parse_float_metric(fact_data, "PBR")
        if pbr is not None:
            if pbr > 5 and re.search(r"저평가|싸게\s*거래|밸류\s*매력", combined):
                critical.append(f"PBR {pbr}인데 저평가 표현 — 해석 오류(자산 구조·적자 여부 확인)")
            if pbr < 0.8 and re.search(r"고평가|비싼\s*편|프리미엄\s*과다", combined):
                critical.append(f"PBR {pbr}인데 고평가 표현 — 해석 오류")
        per = _parse_float_metric(fact_data, "PER", "추정PER(컨센서스)")
        if per is not None and per < 0 and re.search(r"PER\s*[0-9]|저\s*PER|PER\s*낮", combined):
            critical.append("적자(PER 음수) 종목인데 PER 수치로 저평가·고평가 단정 — 수정 필요")

    return {"issues": issues, "critical": critical, "needs_retry": bool(critical)}


def score_stock_content(
    title: str,
    body: str,
    tags: list[str],
    table_str: str = "",
    faq_str: str = "",
    topic_id: str = "",
    fact_data: dict | list | None = None,
    subheading_count: int = 0,
) -> dict:
    """주식(종목분석·공모주·ETF) 전용 품질 채점. 60점 통과 + critical 시 재생성."""
    title = strip_title_emphasis_markers(title)
    score = 0
    issues: list[str] = []
    critical: list[str] = []

    body_len = len(body)
    body_target = 1200
    if body_len >= body_target:
        score += 20
    elif body_len >= 900:
        score += 12
        issues.append(f"본문 약간 짧음 ({body_len}자, 목표 {body_target}자+)")
    elif body_len >= 700:
        score += 6
        issues.append(f"본문 짧음 ({body_len}자)")
        critical.append(f"본문 짧음 ({body_len}자) — {body_target}자+ 권장")
    else:
        issues.append(f"본문 매우 짧음 ({body_len}자)")
        critical.append(f"본문 매우 짧음 ({body_len}자) — 재생성 필요")

    ai_deduct = 0
    for pattern_regex, desc in _AI_PATTERNS:
        if pattern_regex.search(body) or pattern_regex.search(title):
            ai_deduct = min(ai_deduct + 5, 20)
            issues.append(f"AI 패턴: {desc}")
    score += max(0, 20 - ai_deduct)

    # ★반말 종결 게이트 (존댓말 블로그 강제 — 1문장이라도 있으면 critical 재생성)
    banmal = banmal_gate(body, faq_str)
    if banmal:
        score -= min(15 * len(banmal), 30)
        issues.append(f"반말 종결 문장 {len(banmal)}개: " + " / ".join(f"'{b}'" for b in banmal[:3]))
        critical.append(
            "반말 종결 문장을 전부 존댓말(~요/~습니다)로 교정(인용문 제외): "
            + " / ".join(f"'{b}'" for b in banmal[:3])
        )

    buy_hits = 0
    for pattern_regex, desc in _BUY_REC_PATTERNS:
        if pattern_regex.search(body):
            buy_hits += 1
            issues.append(f"투자 권유 위반: {desc}")
            critical.append(desc + " — 중립적 판단 기준으로 수정")
    if buy_hits:
        score = max(0, score - min(buy_hits * 10, 20))

    sh_count = subheading_count or len(re.findall(r"^\[구분선\]", body, re.MULTILINE))
    if sh_count >= 5:
        score += 10
    elif sh_count >= 3:
        score += 6
    else:
        issues.append(f"소제목 부족 ({sh_count}개)")

    # 모바일 가독성 — 덩어리 문단 감지 (WRITING_SYSTEM §6: 한 문장 50자 내외, 문단 1~2문장).
    # 한 줄(=한 문단)이 150자를 넘으면 모바일에서 5줄+ 벽글이 돼 스캔 독자가 이탈한다.
    long_lines = [
        ln for ln in (l.strip() for l in body.splitlines())
        if len(ln) > 150 and not ln.startswith("[")
    ]
    if long_lines:
        score -= min(len(long_lines) * 3, 12)
        issues.append(f"덩어리 문단 {len(long_lines)}개 (150자+) — 문장 분리·'· ' 불릿화 필요")
        if len(long_lines) >= 4 or any(len(ln) > 260 for ln in long_lines):
            critical.append(
                f"덩어리 문단 과다({len(long_lines)}개, 최장 {max(len(ln) for ln in long_lines)}자) "
                "— 한 문단 1~2문장, 불릿은 '· '로 시작해 60자 이내로 분해"
            )

    has_table = bool(table_str) or bool(_TABLE_MARKER.search(body))
    has_faq = bool(faq_str) or bool(_FAQ_MARKER.search(body))
    if has_table:
        score += 10
    else:
        critical.append("표 없음 — 재생성")
    if has_faq:
        score += 10
    else:
        critical.append("FAQ 없음 — 재생성")

    # 강조 마커는 폐지(2026-07-05) — 마커 0개가 정상(만점). 남아 있어도 타이핑 단계에서
    # 텍스트로 벗겨지므로 발행엔 무해 → 재생성(critical) 대신 소폭 감점만.
    emphasis_count = len(_INLINE_EMPHASIS.findall(body))
    if emphasis_count == 0:
        score += 10
    else:
        score += max(0, 10 - emphasis_count * 3)
        issues.append(f"강조 마커 {emphasis_count}개 — 마커 금지(텍스트로만 작성)")

    tag_count = len(tags)
    if tag_count >= 5:
        score += 10
    elif tag_count >= 3:
        score += 5

    title_len = len(title)
    if 15 <= title_len <= 35:
        score += 10
    elif 10 <= title_len <= 40:
        score += 5
        issues.append(f"제목 길이 미흡 ({title_len}자)")
    else:
        issues.append(f"제목 길이 부적합 ({title_len}자)")

    if not _YEAR_IN_TITLE.search(title):
        score -= 5
        msg = "제목에 기준 연도(2026 등) 없음 — 신뢰·최신성 약화"
        issues.append(msg)
        critical.append(msg)

    if fact_data is not None:
        fv = validate_stock_facts(body, table_str, fact_data)
        issues.extend(fv["issues"])
        critical.extend(fv["critical"])

    if topic_id == "공모주캘린더":
        for msg in validate_ipo_date_claims(body):
            issues.append(msg)
            critical.append(msg)

    score = max(0, min(100, score))
    passed = score >= 60
    needs_retry = bool(critical)

    logger.info(
        f"[stock] 품질 {score}/100 ({'통과' if passed else '재생성'}"
        f"{', critical' if needs_retry else ''}) | 본문 {body_len}자 | "
        f"소제목 {sh_count} | [[ ]] {emphasis_count}개"
    )
    if issues:
        logger.info(f"[stock] 이슈: {' / '.join(issues[:8])}")

    return {
        "score": score,
        "issues": issues,
        "critical": critical,
        "needs_retry": needs_retry,
        "pass": passed,
        "detail": {
            "body_length": body_len,
            "subheadings": sh_count,
            "emphasis_count": emphasis_count,
            "has_table": has_table,
            "has_faq": has_faq,
            "topic_id": topic_id,
        },
    }
