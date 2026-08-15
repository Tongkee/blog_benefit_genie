"""
워드프레스 심층분석 원고 생성 (2026-07-07 신설, WP_PIPELINE.md §1·§4).

네이버 파이프라인의 검증된 자산을 최대 재사용:
- 생성/파싱: content._gen_text + content._parse_response (같은 마커 포맷)
- 품질: quality._AI_PATTERNS + info_content._UNSOURCED_RE (무근거 인용 하드 게이트)
- 원칙: 수치 할루시네이션 금지 — facts에 있는 값만 인용, key_stats·sources는 데이터로 주입

네이버(모바일 스캔형)와 다른 점: 구글 SEO 심층 의도 → 더 길게(2,500~4,000자),
섹션별 '결론→근거/계산 예시→표·리스트', 필수 유형(구조해설·계산예시·의사결정 프레임·흔한 오해).
"""
import json
import logging
import re
import time

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER, _split_long_paragraphs
from generator.quality import _AI_PATTERNS
from generator.info_content import _UNSOURCED_RE

logger = logging.getLogger("deep_content")

# prose 기준 — CONTENT_DEPTH.md 목표 2,800~4,500자 (게이트 3,000+)
DEEP_BODY_MIN = 3000

_CALC_SIGNAL_RE = re.compile(
    r"[×x*]\s*\d|=\s*[\d,]+\s*(원|만원|%)"
    r"|\d[\d,]*\s*원\s*[×x]"
    r"|예[)）:]\s*.*\d"
    r"|\d[\d,]*만\s*원"
    r"|약\s*[\d,]+만"
    r"|\(\s*\d+만"
    r"|세액\s*[\d,]+"
    # 정액 지원형 합산·비교식(2026-07-13: 에너지바우처 5연속 반려 — ×·= 없는 주제 대응)
    r"|[+＋]\s*[\d,]+\s*만?\s*원"
    r"|[=＝]\s*총?\s*[\d,]+"
    # 서술형 계산(나누면·월평균·연간 총 N원) — 기호 없는 실계산도 인정(2026-07-14)
    r"|나누면\s*(약\s*)?[\d,]+\s*원"
    r"|[÷/]\s*\d+\s*개?월?"
    r"|(월평균|월\s*환산)\s*(약\s*)?[\d,]+\s*원"
    r"|총\s*[\d,]{6,}\s*원"
)

# 생성 후 결정적 치환 — 재생성 4회 전부 '것이 중요합니다'로 실패하는 경우 방지
_AI_SANITIZE: list[tuple[re.Pattern, str]] = [
    # 2026-07-24 수정: 치환문에 '해'가 없어 '확인하는 것이 중요합니다'→'확인보면 편해요'로
    # 어간이 깨졌음(정규식이 '하는'의 '하'까지 소비). 아래 '좋습니다' 규칙은 치환문에 '하는'을
    # 다시 넣어 정상이었던 것과 대비. → '확인해보면 편해요'로 복구.
    (re.compile(r"하는\s*것이\s*중요합니다"), "해보면 편해요"),
    (re.compile(r"하는\s*것이\s*좋습니다"), "하는 게 낫더라고요"),
    (re.compile(r"것이\s*중요합니다"), "중요해요"),
    (re.compile(r"하시면\s*됩니다"), "하면 돼요"),
    (re.compile(r"하시기\s*바랍니다"), "해보세요"),
    (re.compile(r"극대화"), "최대한"),
    (re.compile(r"살펴보(도록\s*하겠습니다|겠습니다)"), "정리할게요"),
    (re.compile(r"알려져\s*있"), "공식 자료에 따르면"),
    (re.compile(r"전해지고\s*있"), "안내되고 있"),
]


def _sanitize_ai_patterns(text: str) -> str:
    for rx, repl in _AI_SANITIZE:
        text = rx.sub(repl, text)
    return text

# 카테고리별 공식 출처(E-E-A-T) — 데이터로 주입, LLM이 지어내지 않음
DEFAULT_SOURCES = {
    "연금·절세 설계": [
        ("국세청 — 연금계좌·금융소득 안내", "https://www.nts.go.kr"),
        ("금융감독원 통합연금포털", "https://100lifeplan.fss.or.kr"),
        ("금융감독원 금융상품통합비교공시(finlife)", "https://finlife.fss.or.kr"),
    ],
    "대출·신용 전략": [
        ("금융감독원 파인(FINE)", "https://fine.fss.or.kr"),
        ("주택도시기금", "https://nhuf.molit.go.kr"),
    ],
    "보험·리스크 설계": [
        ("금융감독원 — 보험다모아", "https://www.e-insmarket.or.kr"),
        ("내보험찾아줌", "https://cont.insure.or.kr"),
    ],
    "세금·환급 가이드": [
        ("국세청 홈택스", "https://www.hometax.go.kr"),
        ("국세청 — 연말정산·환급 안내", "https://www.nts.go.kr"),
    ],
    "주거·청약 전략": [
        ("국토교통부 실거래가 공개시스템", "https://rt.molit.go.kr"),
        ("마이홈 주거복지포털", "https://www.myhome.go.kr"),
    ],
    "제도·복지 해설": [
        ("고용24 실업급여", "https://ei.work24.go.kr"),
        ("복지로", "https://www.bokjiro.go.kr"),
    ],
    # 레거시(기존 글 호환)
    "금융·재테크": [
        ("국세청 — 연금계좌 안내", "https://www.nts.go.kr"),
        ("금융감독원 통합연금포털", "https://100lifeplan.fss.or.kr"),
    ],
    "세금·절세": [("국세청 홈택스", "https://www.hometax.go.kr")],
    "보험": [("보험다모아", "https://www.e-insmarket.or.kr")],
    "부동산·주거": [("마이홈", "https://www.myhome.go.kr")],
}

_SYSTEM = (
    "너는 '현지언니' 명의의 생활금융·제도 분석 칼럼니스트다.\n"
    "이 글은 워드프레스(구글 검색)용 심층분석 칼럼이다. 실용 가이드가 아니라 "
    "「제도 구조 → 수치 비교 → 상황별 판단 기준」을 제시하는 분석 글이다.\n"
    "문체: 해요체 유지, 담백·정확. 친근하지만 얕지 않게 — 전문성은 정확한 숫자·출처·비교표로 드러내라.\n"
    "과한 1인칭 경험담('저도 처음엔…')은 최소화하고, 필요할 때만 한 문장 이내로.\n"
    "\n[대원칙 — 반드시 준수]\n"
    "1. 서두 인사말·자기소개 절대 금지. 첫 문단=결론(두괄식). "
    "둘째 문단=이 글이 답할 질문+분석 축 예고. "
    "셋째 문단(또는 둘째 끝)=「이 글의 분석 범위·한계(2026년 기준, 공식 자료 확인 권장)」1문장.\n"
    "2. ★수치 할루시네이션 절대 금지: 세율·한도·금리·수수료 등 '구체 수치'는 [팩트 데이터]에 있는 값만 사용. "
    "데이터에 없으면 '공식 자료로 확인'으로 처리하고 절대 지어내지 마라. 계산도 데이터 값으로만.\n"
    "3. ★무근거 인용 금지: '평균 N%로 알려져 있어요', '~라는 말이 있어요'처럼 출처 없는 수치·주장 절대 금지.\n"
    "4. ★깊이의 정의 = 정보 이득: 각 섹션은 반드시 ①결론 첫 문장 → ②근거/계산 예시(실수치로 ×·= 명시) "
    "→ ③표나 리스트 순서로. 최소 한 섹션엔 '숫자를 넣어 계산해보는' 구체 예시가 있어야 한다.\n"
    "4-1. ★수치 일관성: 같은 계산·항목이 본문 서술과 표에 함께 나오면 '기준 숫자와 결과값'을 반드시 일치시켜라. "
    "비과세 한도가 있는 경우 '일반 계좌=전체 수익에 과세, 혜택 계좌=(수익-비과세분)에 과세'처럼 과세 기준을 서로 다르게 정확히 적용하고, "
    "본문과 표의 절감액·세금이 어긋나지 않게 하라.\n"
    "5. ★필수 섹션 유형: (가)제도·구조 해설 (나)돈 계산 예시 2케이스 이상 (다)「내 상황별 판단 기준」 "
    "(라)흔한 오해/함정. 이 네 가지 성격이 소제목에 녹아 있어야 한다.\n"
    "6. 문체: **해요체 only** — '~합니다/됩니다/제시합니다' 금지, '~해요/돼요/정리할게요' 사용. "
    "담백하고 정확하게. 어려운 용어는 처음 나올 때 괄호로 짧게 풀이. "
    "쉽지만 얕지 않게 — 전문성은 '정확한 숫자와 판단 기준'으로 드러내라.\n"
    "7. 이모지 금지. AI 상투어('다양한', '~하시기 바랍니다', '것이 중요합니다') 금지. "
    "★해요체 변형도 동일 금지 — '것이 중요해요/좋아요', '하시면 돼요'로 문장·문단을 반복해 맺지 마라"
    "(한 글에 1회 이내). 구체적 수치·조건·결과로 맺어라(2026-07-24: 해요체라 금지목록을 빠져나가 "
    "실업급여 글에 '~것이 중요해요' 6회 반복). "
    "강조 마커([[ ]]·**·__) 금지 — 중요한 건 소제목·표·숫자로 드러내라.\n"
    "8. 투자·가입 권유 단정 금지: '무조건 하라' 대신 '이런 경우엔 이렇게 판단한다'는 기준 제공. "
    "마지막은 개인차·공식 확인 안내.\n"
    "9. 가독성: 한 문장 60자 내외, 한 문단 2~3문장까지. 문단 사이 빈 줄. "
    "불릿은 '· '로 시작(60자 이내), 순서 단계는 '①②③'.\n"
    "9-1. ★번호 연속성: 한 소제목 안에서 ①②③ 번호는 반드시 1부터 연속 증가. "
    "번호 항목 사이에 산문 문단이 끼어도 다음 항목은 이어지는 번호를 쓴다(①…②…③, 절대 ①①① 반복 금지).\n"
    "9-2. 번호 항목(①②③)은 '항목명: 핵심 결론' 한 줄로 짧게. 부연이 필요하면 항목 아래 별도 산문 문단으로. "
    "한 번호 항목 안에 여러 문장을 이어붙이지 마라.\n"
    "9-3. ★같은 성격의 항목을 3개 이상 나열할 땐 반드시 '· ' 불릿 목록(6개 초과면 표)으로 묶어라. "
    "'노인 (…)' '영유아 (…)'처럼 한 줄짜리 문단을 연달아 나열하는 것 절대 금지 — "
    "문단 나열은 세로로 길어져 가독성을 망친다(2026-07-12 에너지바우처 글 피드백).\n"
    "9-4. ★목록 마커 일관성: 불릿 목록의 항목은 '하나도 빠짐없이' 전부 '· '로 시작하라 — "
    "목록 중간의 한 항목만 마커를 빼먹으면 목록이 쪼개져 렌더링이 깨진다.\n"
    "9-5. 번호·불릿 항목은 가능하면 '핵심 라벨: 설명' 형태로 써라(라벨 2~10자, "
    "예 '· 소득 기준: …', '① 임차 요건: …'). 라벨은 렌더링에서 자동으로 굵게 강조돼 스캔 가독성을 높인다.\n"
    "10. [사진N] 마커는 단독 줄로만. 문장 안에 이미지 지시문을 옮겨 적지 마라.\n"
    "11. 독자 호칭 금지: '독자님·여러분·구독자' 등 부르지 마라. 필요하면 '본인·나' 관점으로 서술.\n"
)

_STRUCT = (
    "\n[글 구조 — 이 순서, 마커 필수. 2,800~4,500자 심층]\n"
    "(도입 2~3문단. 첫 문단=결론. 둘째 문단=이 글이 답할 질문+분석 축 예고. 인사말·[사진] 마커 없이 바로 본문 시작.)\n"
    "\n[요약시작]\n"
    "· (핵심 결론 1)\n· (핵심 결론 2)\n· (핵심 결론 3)\n"
    "[요약끝]\n"
    "\n[소제목] (구조·제도 해설 소제목 — 결론/수치 포함, 예 '세액공제: 한도는 공유, 환급액은 소득이 가른다')\n"
    "(결론 첫 문장 → 제도 원리를 쉽게 → 데이터 수치 인용. 3~5문단.)\n"
    "\n[소제목] (계산 예시 소제목 — 실제 숫자를 넣어보는 섹션)\n"
    "(★facts의 수치로 '얼마 넣으면 얼마' 식 계산을 최소 2개(서로 다른 소득·나이·상황). 불릿으로 케이스 비교. "
    "표 앞에 1~2문장. ★정액 지원 제도처럼 곱셈 계산이 없는 주제라도 반드시 '여름 N만원 + 겨울 N만원 = 총 N만원', "
    "'일반 가구 대비 N만원 절감' 같은 합산·비교식(＋·＝ 포함)을 케이스별로 써라 — 계산 예시가 없으면 재작성이다.)\n"
    "[표시작]\n"
    "항목 | 선택지A | 선택지B\n"
    "(행1) | (값) | (값)\n"
    "(행2) | (값) | (값)\n"
    "[표끝]\n"
    "(★표는 반드시 [표시작]과 [표끝] 사이에, 각 행을 파이프(|)로 구분해 작성. "
    "facts 기반 3열 비교표. 셀은 짧게.)\n"
    "\n[소제목] (심화 축 소제목 — 위에서 예고한 분석 축의 나머지)\n"
    "(결론 → 근거 → 엣지 케이스. 데이터 없는 수치는 '공식 확인'으로.)\n"
    "\n[소제목] 내 상황별 판단 기준\n"
    "(★의사결정 프레임 — 소득·나이·상황별로 '이런 경우엔 이렇게 판단하는 경우가 많아요' 참고 기준을 "
    "①②③ 순서로. 단정 대신 조건별 판단. 마지막에 한 줄 핵심 원칙.)\n"
    "\n[소제목] 많이들 착각하는 것들\n"
    "(흔한 오해 2~3개. ★형식 — 번호 없이, 접두어를 정확히: "
    "'오해: \"(사람들이 잘못 아는 문장 1줄)\"' → 바로 다음 줄 '사실: (바로잡는 설명 1~3문장)'. "
    "★오해 문장은 반드시 큰따옴표로 감싼 인용문으로 쓴다(2026-07-29 실사고 — 따옴표 없이 "
    "'~된다/~있다' 단정형으로 쓰면 글쓴이가 단언하는 반말 문장으로 읽힘, WP 라이브 16건). "
    "사실 문장은 존댓말(~입니다/~해요)로 쓴다. "
    "각 오해/사실 쌍 사이에 빈 줄 1개. '오해:'/'사실:' 접두어가 정확해야 스타일 카드로 렌더링된다.)\n"
    "\n[소제목] 자주 묻는 질문\n"
    "[FAQ시작]\n"
    "Q: (검색 롱테일 질문 1)\nA: (facts 기반 2~3문장)\n"
    "Q: (질문 2)\nA: (답)\n"
    "Q: (질문 3)\nA: (답)\n"
    "[FAQ끝]\n"
)

_OUTPUT_FORMAT = (
    "\n[출력 형식 — 반드시 이 형식]\n"
    "TITLE: {검색의도+정보 이득이 드러나는 제목. 2026 연도 포함 권장. "
    "예 '연금저축펀드 vs IRP, 세액공제만 보면 손해 봅니다 | 4개 축 심층 비교'}\n"
    "TAGS: {쉼표로 구분된 태그 5~7개}\n"
    "---\n"
    "{위 [글 구조]대로 마커 포함 본문}\n"
)


def _build_system(category: str) -> str:
    return (
        _SYSTEM
        + _STRUCT
        + _OUTPUT_FORMAT
        + "\n[마커 체크리스트 — 누락 시 재작성]\n"
        "- 본문은 [사진] 마커 없이 도입 문단으로 시작(WP는 상단에 제목+핵심수치 스트립이 온다)\n"
        "- [요약시작]~[요약끝] 1쌍(· 3줄)\n"
        "- [표시작]~[표끝] 1쌍(행을 파이프(|)로 구분한 비교표)\n"
        "- [FAQ시작]~[FAQ끝] 1쌍(Q 3개+)\n"
        "- [소제목] 6개(구조해설/계산예시/심화축/의사결정/흔한오해/FAQ)\n"
        "- 구체 수치는 팩트 데이터 값만, 최소 1개 섹션에 계산 예시\n"
    )


def _gate(parsed: dict, cfg: dict | None = None) -> tuple[bool, list[str]]:
    """심층 품질 게이트 — 통과 여부 + 이슈. WP_PIPELINE §4.
    cfg(topic['gate'])로 콘텐츠 유형별 완화 가능(예: 실계좌 인증글=팩트 위주 경량).
    기본값은 심층 가이드 기준 유지(하위호환)."""
    cfg = cfg or {}
    body_min = cfg.get("body_min", DEEP_BODY_MIN)
    min_calc = cfg.get("min_calc", 2)
    min_faq  = cfg.get("min_faq", 3)
    need_table = cfg.get("require_table", True)
    issues: list[str] = []
    body = parsed.get("body", "")
    body_len = len(_IMAGE_MARKER.sub("", body))

    if body_len < body_min:
        issues.append(f"본문 짧음({body_len}자, 최소 {body_min}자)")
    # 무근거 인용 하드 게이트(네이버 실사고 교훈 재사용)
    if _UNSOURCED_RE.search(body):
        issues.append("무근거 인용 표현('알려져 있'류)")
    # AI 상투어 — 하드 게이트(재생성)
    ai_hits = [desc for rx, desc in _AI_PATTERNS if rx.search(body)]
    if ai_hits:
        issues.append(f"AI패턴: {ai_hits[0]}")
    # 구조 요건
    subs = [s for s in parsed.get("subheadings", []) if s != "자주 묻는 질문"]
    if len(subs) < 4:
        issues.append(f"소제목 부족({len(subs)}개, 4+ 필요)")
    if need_table and not parsed.get("table_strs"):
        issues.append("비교표 누락")
    if min_faq and len(parsed.get("faq_pairs", [])) < min_faq:
        issues.append(f"FAQ 부족({len(parsed.get('faq_pairs', []))}개)")
    # 계산 예시 신호 — 본문+표 합산
    if min_calc:
        calc_src = body + "\n" + "\n".join(parsed.get("table_strs", []) or [])
        calc_n = len(_CALC_SIGNAL_RE.findall(calc_src))
        if calc_n < min_calc:
            issues.append(f"계산 예시 부족({calc_n}개, {min_calc}+ 필요)")
    # 반말 종결 — 하드 게이트(2026-07-29 WP 라이브 감사: 30글 중 16글 혼입, 대부분
    # 따옴표 없는 '오해:' 단정문). 네이버 트랙(§4-1)과 동일 기준을 WP에도 적용.
    try:
        from generator.quality import find_banmal_sentences
        _bm = find_banmal_sentences(body)
        if _bm:
            issues.append(f"반말 종결 {len(_bm)}문장(예: {_bm[0][:30]})")
    except Exception:
        pass

    # 치명적(재생성 유발)
    critical = [
        i for i in issues
        if any(k in i for k in ("짧음", "표 누락", "FAQ 부족", "무근거", "계산 예시", "AI패턴", "반말"))
    ]
    return (not critical, issues)


def generate_deep_post(topic: dict, api_key: str) -> dict | None:
    """topic → 심층분석 post dict(wp_render 입력).
    topic = {keyword, category, facts(dict), key_stats(list), sources(list|None)}"""
    category = topic.get("category", "금융·재테크")
    keyword = topic.get("keyword", "")
    facts = topic.get("facts", {})
    system = _build_system(category)
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2, default=str)

    user_msg = (
        f"주제(키워드): {keyword}\n"
        f"카테고리: {category}\n\n"
        f"[팩트 데이터 — 이 수치만 사용, 추가·변조 금지]\n{facts_json}\n\n"
        "위 팩트만 근거로 심층분석 글을 작성해라. 계산 예시는 이 수치로만. "
        "데이터에 없는 수치는 '공식 자료로 확인'으로 처리하라."
    )
    # 건별 특수 구조 지시(청약 공고 분석 등, 2026-07-17) — 기본 구조 위에 덧붙는 추가 요구
    if topic.get("extra_instructions"):
        user_msg += "\n\n[이 글의 추가 요구사항 — 반드시 반영]\n" + topic["extra_instructions"]

    # 2026-07-16: 07-15 크론이 5회 전부 '본문 짧음(2,261~2,988자)'으로 실패 → 2회 증설
    waits = [10, 30, 60, 90, 60, 60]
    feedback = ""
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg + feedback, system, 8192, 0.2,
                            use_search=bool(topic.get("use_search")))
            if not raw:
                logger.warning(f"빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"파싱 실패 (시도 {attempt})")
                continue
            parsed["body"] = _sanitize_ai_patterns(_split_long_paragraphs(parsed.get("body", "")))
            parsed["title"] = _sanitize_ai_patterns(parsed.get("title", ""))
            ok, issues = _gate(parsed, topic.get("gate"))
            if not ok:
                logger.warning(f"품질 미달 재생성 (시도 {attempt}): {'; '.join(issues[:3])}")
                feedback = (
                    f"\n\n[이전 시도 거부 — 반드시 수정]\n"
                    f"- {'; '.join(issues[:4])}\n"
                    "- '것이 중요합니다/중요해요'·'것이 좋습니다/좋아요'·'하시면 됩니다/돼요' 등 AI 교과서체 "
                    "절대 금지(해요체 변형 포함, 2026-07-24)."
                )
                # 짧음 실패엔 구체 지시 — 일반 피드백만으론 같은 길이로 재생성됨(07-15 실측)
                if any("짧음" in i for i in issues):
                    feedback += (
                        "\n- 본문이 너무 짧다. 각 섹션에 사례·계산 과정·표 해설을 더 붙여 "
                        "공백 제외 3,500자 이상으로 써라. 섹션을 빼지 말고 깊이를 더해라."
                    )
                continue
            if issues:
                logger.info(f"통과(경미 이슈): {'; '.join(issues)}")
            # 데이터로 주입 — LLM이 지어내지 않음
            parsed["key_stats"] = topic.get("key_stats", [])
            parsed["sources"] = topic.get("sources") or DEFAULT_SOURCES.get(category, [])
            parsed["keyword"] = keyword
            parsed["category"] = category
            body_len = len(_IMAGE_MARKER.sub("", parsed["body"]))
            logger.info(
                f"심층 생성 완료: {parsed.get('title')!r} ({body_len}자, "
                f"소제목 {len(parsed.get('subheadings', []))}, FAQ {len(parsed.get('faq_pairs', []))})"
            )
            return parsed
        except Exception as e:
            logger.error(f"생성 실패 (시도 {attempt}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])
    return None
