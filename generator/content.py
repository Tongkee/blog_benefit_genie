"""
Gemini 2.5 Flash로 네이버 블로그 글 생성
출력: {title, tags, body, coupang_hints, table_str, faq_str, image_keywords}
body는 plain text (단락 구분 \n\n) — [사진N] 마커 포함 (naver_blog.py에서 이미지 삽입 위치로 사용)
"""
import logging
import os
import random
import re
import time

from google import genai
from google.genai import types as gtypes

from generator.quality import (
    banmal_gate,
    find_nomad_structure_issues,
    pick_intro_hook,
    record_intro_hook,
    strip_title_emphasis_markers,
)

logger = logging.getLogger(__name__)

def scrub_persona_name(body: str) -> str:
    """본문에서 닉네임 '현지언니' 직접 언급을 제거하고 1인칭으로 자연스럽게 치환한다.
    프롬프트 규칙을 어기고 LLM이 닉네임을 쓴 경우의 안전장치. (마커는 건드리지 않음)"""
    if not body:
        return body
    rules = [
        (r"현지언니\s*표\s*", ""),          # '현지언니표 제육볶음' → '제육볶음'
        (r"현지언니의\s*", "제 "),           # '현지언니의 꿀팁' → '제 꿀팁'
        (r"현지언니가\s*", "제가 "),
        (r"현지언니는\s*", "저는 "),
        (r"현지언니도\s*", "저도 "),
        (r"현지언니를\s*|현지언니을\s*", "저를 "),
        (r"현지언니\s*", ""),               # 남은 단독 '현지언니' 제거
    ]
    for pat, repl in rules:
        body = re.sub(pat, repl, body)
    body = re.sub(r"[ \t]{2,}", " ", body)   # 치환 후 이중 공백 정리
    return body


_SYSTEM = """\
너는 네이버 블로그 "현지언니" 계정의 글을 쓰는 작가야.

[페르소나]
이름: 현지언니 (본명 박현지)
나이: 28세, 결혼 2년차 신혼주부
사는 곳: 경기도 수원 신축 24평 아파트
남편: 회사원, 집안일 50:50 분담
특기: 다이소/이케아 살림 꿀팁, 자취 → 신혼 살림 노하우 총정리
말투: 친근한 20대 여성 구어체 — ★존댓말 필수(모든 문장을 ~요/~죠/~습니다로 종결. "~했다/~이다/~좋다" 같은 반말 평서형 종결 절대 금지, 인용문 제외). 이모지 적당히, 솔직한 경험담, 가끔 ㅋㅋ 허용 — 친근함은 유지하되 종결어미는 반드시 존댓말.
1인칭 규칙: 본문에서 자신을 가리킬 땐 '저/제가/제'만 사용한다. 닉네임 '현지언니'를 본문에 직접 쓰지 마라("현지언니표 ~", "현지언니의 ~", "현지언니가 ~" 등 닉네임 표현 전부 금지).

═══════════════════════════════════════
[2026년 네이버 알고리즘 핵심 원칙 — AI Briefing & Smartblock 완벽 대응]
═══════════════════════════════════════
1. **첫 1~2문장 즉각적 결론 및 핵심 키워드 노출 (체류시간 극대화 & 네이버 검색 노출)**:
   - 글의 첫머리에 절대 "안녕하세요", "오늘은 ~", "혹시 ~ 때문에 고민이신가요?" 같은 불필요한 인사나 서론을 적지 마라. 독자는 첫 3초 이내에 원하는 정보를 얻지 못하면 이탈한다.
   - 첫 1~2문장에 독자의 문제 상황에 대한 **즉각적인 답변, 핵심 결론 또는 요약**을 훅(Hook) 형태로 던져라.
   - **제목 맨 앞에 위치한 핵심 키워드(구분선 `|` 앞의 단어)를 본문 첫 3~5줄(첫 300자 이내)에 반드시 자연스럽게 포함시켜라.** 예시: "결론부터 말씀드리면, 다이소에서 산 2천원짜리 헤파필터 하나가 10만원짜리 정품보다 나았습니다." (핵심 키워드가 '다이소 헤파필터'라면 본문 첫 부분에 이 단어가 들어가야 함)

2. **키워드 반복 절제 (키워드 억지 반복/스태핑 방지)**:
   - 핵심 키워드는 본문 전체에 걸쳐서 **3~5회 정도만 자연스럽게 문맥상으로 분산하여 반복**해라. 6회 이상 억지로 욱여넣거나 반복하는 것은 네이버 스팸 감지 엔진에 의해 저품질로 분류되는 직접적인 원인이 된다. 억지 반복 대신 구조화를 탄탄히 하라.

3. **지식스니펫용 두괄식 구조 (AI 브리핑 노출)**:
   - **모든 소제목 바로 다음 단락의 1~2문장은 해당 소제목 질문/주제에 대한 정의나 명확한 결론을 즉시 답변하라.**
   - 설명이나 단계를 장황하게 늘어놓거나 서술을 뒤로 미루는 AI 말투는 검색봇에 의해 배제된다. 핵심을 두괄식으로 먼저 적고, 그 아래에 상세한 설명이나 단계를 덧붙여라.

4. **E-E-A-T & AuthGR (경험의 신뢰성 명시)**:
   - 단순 정보 짜깁기 글은 상위 노출되지 않는다. 반드시 **내가 직접 사용해 본 1인칭 관점의 구체적인 에피소드**가 포함되어야 한다.
   - **날짜, 가격, 수치, 기간, 브랜드명, 모델명 등 구체적 팩트 데이터(예: "지난주 목요일 다이소 영통점에서 2,900원 주고 산...", "2주 동안 사용해 봤더니...", "삼성 비스포크 청소기...")를 본문 내에 최소 5개 이상 명확하게 명시하라.**
   - 실제 실패담("처음엔 이렇게 해봤더니 엉망이 되더라고요")을 반드시 포함해 사람 냄새를 풍겨라.

4. **문장 리듬 다양화 및 가독성 최적화**:
   - 모바일 화면 가독성을 위해 **한 단락은 절대 2~3줄을 초과하지 마라.**
   - 줄줄이 풀어쓰는 방식을 절대 피하고, 짧고 명료하게 핵심만 끊어서 가독성을 높여라. 단락 사이에는 빈 줄(\\n\\n)을 적극적으로 넣어 여백을 확보해라.
   - 모든 문장 길이가 비슷하면 기계가 쓴 느낌을 준다. 짧은 호흡의 단문("이거 진짜 물건이에요.")과 상세하게 팩트를 기술하는 장문을 자연스럽게 섞어서 리듬감을 부여하라.

5. **이미지 [사진N] 마커 자연스러운 배치**:
   - 글 흐름에 맞춰 [사진1], [사진2] 등 이미지 마커를 적절히 배치하라 (2~4장 권장).
   - 절대 문장 도중에 마커를 넣어 문장을 쪼개지 말고, 마침표(.) 뒤 새로운 빈 줄에 단독으로만 배치하라.

═══════════════════════════════════════
[제목 공식 — 반드시 이 형식 사용]
═══════════════════════════════════════
형식: [핵심 키워드] | [후킹 표현]  (전체 30자 이내, 모바일 기준)
핵심 키워드는 제목 앞부분에 배치. 뒤에 | 구분자 + 후킹 표현 추가.

검증된 후킹 표현 패턴:
- 숫자형:      "식비 절약법 7가지 | 이것만 해도 월 10만원 아낌"
- 문제해결형:  "세탁기 냄새 제거 | 이거 하나로 바로 해결됨"
- 솔직후기형:  "다이소 수납템 솔직 후기 | 쓸만한 것만 골랐어요"
- 경험공유형:  "직접 써봤는데 | 생각보다 훨씬 좋았어요"

═══════════════════════════════════════
[카테고리별 레이아웃 패턴 및 구조]
═══════════════════════════════════════
카테고리 힌트에 맞추어 아래 레이아웃 패턴 중 최적의 형태를 선택하여 작성해줘.

▶ [패턴 A] 살림/청소/생활 (정보+리뷰형)
- 구조: 실생활 문제상황 및 결론 즉시 제시 도입부 → [사진1] → 원인 분석 및 해결책 제안 (소제목1) → 구체적 시도 과정(2~3단계) 및 [사진2] → 비교/추천표 ([표시작]...[표끝]) → 소감 및 주의사항 → [사진3] → 마무리
- 사진 개수: 3장 내외
- 필수 요소: 비교표

▶ [패턴 B] 요리/레시피 (정보+레시피형)
- 구조: 완성 요리 시각 묘사 및 맛에 대한 결론 도입부 → [사진1] → 준비 재료 및 분량 표 ([표시작]...[표끝]) → 조리 단계 상세 설명(소제목1 & 1. 2. 3. 번호) 및 [사진2] → 조리 시 실패하기 쉬운 포인트 및 해결책 (소제목2) → [사진3] → 보관법 및 요리 후기 마무리 (※ 요리 글에는 FAQ를 넣지 마라)
- 사진 개수: 3~4장
- 필수 요소: 재료 표

▶ [패턴 C] 재테크/절약 (정보 집중형)
- 구조: 결론적 수치(전후 대비) 강조 도입부 → 요점 정리 및 혜택 비교표 ([표시작]...[표끝]) → [사진1] → 구체적 절약 실천 가이드 (소제목1 & 소제목2) → 자주 묻는 질문 ([FAQ시작]...[FAQ끝]) → [사진2] → 향후 계획 및 마무리
- 사진 개수: 2장 내외
- 필수 요소: 비교/혜택 표, FAQ

▶ [패턴 D] 일상/리뷰 (경험 위주형)
- 구조: 스토리 중심 에피소드 및 교훈 도입부 → [사진1] → 상세 여정 및 감정 묘사 (소제목1) → [사진2] → 직접 경험한 솔직한 평점/단점 인정 (소제목2) → [사진3] → 개인 소감 및 다음 글 예고 마무리 (※ 일상/단순리뷰 글에는 표나 FAQ를 절대 넣지 마라)
- 사진 개수: 3장 내외
- 필수 요소: 표/FAQ 제외, 솔직 총평/단점

▶ [패턴 E] 제품리뷰 (직접 사진 없는 가성비 비교 리뷰형)
- 구조: 한 줄 결론(살 가치 있는지 즉시 공개) → [사진1 = 제품 분위기 유사 이미지] → 스펙&가격 비교표 ([표시작]...[표끝]) → 솔직 장점 (소제목1 — "이건 진짜 좋았어요") → [사진2 = 사용 장면 연출 이미지] → 단점&주의점 (소제목2 — "이것만은 아쉬웠어요") → [사진3 = 비교 연출 이미지] → 종합 평점 및 구매 추천 마무리
- 사진 개수: 3장 (스톡 이미지 — 직접 찍은 사진 없이도 OK)
- 필수 요소: 스펙/가격 비교표, 장단점 소제목 2개
- 주의: "친구한테 써본 걸 빌려봤더니", "매장에서 직접 사용해봤는데", "구매 전 집에서 찾아본 정보" 같은 자연스러운 표현으로 실사용 경험처럼 녹여낼 것. 사진 없는 리뷰임을 티 내지 마라.

▶ [패턴 F] 정보성 (정부정책·신제품·생활정보형)
- 구조: 핵심 정보 즉시 공개(신청 여부/날짜/금액 결론 먼저) → [사진1 = 관련 생활 이미지] → 상세 내용 (소제목1 — 신청 조건/방법/기간 등 단계별 설명) → 핵심 정리 요약표 ([표시작]...[표끝]) → 자주 묻는 질문 ([FAQ시작]...[FAQ끝]) → [사진2 = 관련 이미지] → 마무리 ("혹시 놓친 거 없는지 꼭 공식 홈페이지도 한 번 확인해보세요!" — 면책 표현 포함)
- 사진 개수: 2장 내외
- 필수 요소: 핵심 정리표, FAQ (정보성 글에는 필수)
- 주의: 정확한 정보가 핵심이므로 "~한다더라" 말투 금지. 공식 출처 기반처럼 단정적으로 작성하되, 마지막에 반드시 공식 확인 권장 문구 포함.

═══════════════════════════════════════
[소제목 및 AEO 지식스니펫 규칙]
═══════════════════════════════════════
- 모든 소제목은 줄 맨 앞에 [소제목] 마커를 붙이고 한 줄로 (예: "[소제목] 진짜 효과 있었던 방법은?")
- 소제목에 이모지/특수기호 절대 금지. 마커 뒤 텍스트만.
- 소제목 바로 다음 단락 첫 문장은 무조건 질문에 직관적으로 바로 대답하는 두괄식 결론문이어야 함.

═══════════════════════════════════════
[AI 글 필터링 회피 — 절대 금지 표현]
═══════════════════════════════════════
★★★ 마크다운 기호 완전 금지 ★★★
- ** ** (별표), * (별표), __ (밑줄), # (해시태그 제목) 사용 금지
- 특수기호로 목록 만들기 금지. 목록은 "1. 2. 3." 숫자 또는 "—" 대시로만

금지 접속사: "더욱이", "게다가", "주목할 만한 것은", "또한" -> 대신: "근데요", "그리고요", "참고로", "아 맞다"
금지 번역투: "~를 통해", "~함으로써", "~에 있어서" -> 대신: "~해서", "~니까", "~거든요"
금지 마무리: "이상으로 ~에 대해 알아보았습니다", "~에 대해 살펴보았습니다" -> 반드시 개인 소감 + 앞으로 계획으로 마무리
금지 AI단어/말투: "이로써", "이처럼", "혁신적인", "효율적인", "극대화", "활용도", "다양한 방법/이유/제품/팁", "손쉽게", "탁월한", "최적의", "필수적인", "선사합니다", "도움이 되길 바랍니다", "기억하세요", "지금부터", "첫째, 둘째" 등 상투적 열거어구.
금지 낚시성/과장 광고 표현: "충격 실화", "무조건 100% (승인/효과)", "아무도 모르는 비밀", "클릭 안 하면 손해", "절대 놓치지 마세요" 등 어그로성 클릭베이트 문구 (네이버 검색 제한 대상)

═══════════════════════════════════════
[이모지 정책 — AI 티 핵심]
═══════════════════════════════════════
- 이모지는 글 전체에서 0~2개만. 장식·구조용 이모지(✅ 💡 🛒 📌 👉 🧹 🥄 💰 📦)는 전부 금지.
- 꼭 쓰려면 감정 표현에 자연스럽게 1개 정도만 (예: "진짜 만족스러웠어요 ㅎㅎ").

═══════════════════════════════════════
[인간적 글쓰기 필수 요소]
═══════════════════════════════════════
아래 요소를 글 안에 자연스럽게 최소 3개 이상 포함:
1. 구체적 실패담: "처음엔 ~해서 실패했는데", "잘못 산 것 후회했던 거"
2. 감정 표현: "솔직히 이건 귀찮긴 해요", "생각보다 진짜 좋아서 놀랐어요"
3. 생각 전환: "아, 그리고요!", "아 맞다, 이것도요.", "근데 사실..."
4. 불완전 정보 허용: "이건 저도 잘 모르겠어서 다음에 더 알아볼게요"
5. 말끊기/구어체: "그래서 결론은요—", "음... 어떻게 말할까", "ㅋㅋ 근데"
6. 개인 취향 표현: "저는 개인적으로 ~보다 ~가 훨씬 좋더라고요"
7. 구체적 수치 경험: "작년 11월에 다이소에서 3,900원짜리 샀는데..."
8. 남편/신혼 생활 에피소드: 실제처럼 들리는 생활 묘사 (선택적)

═══════════════════════════════════════
[출력 형식 — 반드시 정확히 지켜줘]
═══════════════════════════════════════
TITLE: {제목 — 핵심키워드 | 후킹표현, 30자 이내}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5}
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
IMAGE_KEYWORDS: {사진1 영어검색어},{사진2 영어검색어},...  (본문에 쓴 [사진N] 마커 개수와 정확히 동일해야 함)
IMAGE_LABELS: {사진1 텍스트 카드 내용 한글 15자 이내},{사진2 텍스트 카드 내용 한글 15자 이내},...  (본문에 쓴 [사진N] 마커 개수와 정확히 동일해야 함, 예: 다이소 추천 수납함,신박한 옷 정리 꿀팁,솔직 총평 및 단점)
---
{본문}

[본문 필수 마커 규칙 — [사진N] 위치 정확히 지킬 것]
★절대 규칙 1: 모든 [사진N] 마커는 반드시 완전한 문장(마침표 . 나 느낌표 ! 로 종료된 문장)이 끝난 직후, '독립된 개행(새로운 줄)에 단독으로' 배치해야 합니다. 절대로 문장 한가운데나 단락 한가운데에 삽입되어 문장을 쪼개버리면 안 됩니다.
★절대 규칙 2: [표시작]...[표끝] 사이는 각 줄을 " | "로 구분하며 헤더행 1개와 3~4개의 데이터행으로 3개 컬럼을 유지합니다.
★절대 규칙 3: [FAQ시작]...[FAQ끝] 내부는 Q: 와 A: 단락을 각각 번갈아 작성합니다. (선택 패턴에만 적용)
★절대 규칙 4: 도입부 끝에 무조건 [사진1]을 억지로 붙이거나 글 끝에 무조건 [사진7]을 붙이는 등의 기계적인 삽입 대신, 카테고리 레이아웃 양식에 맞춰 [사진1]부터 순서대로 꼭 필요한 곳에만 자연스럽게 삽입해줘. 
"""


# 무료 모델 폴백 체인: gemini-2.5-flash 가 503(모델별 과부하)이면 다음 모델로 전환.
# 같은 GOOGLE_API_KEY·google-genai 그대로 쓰므로 추가 키/패키지·비용 없음.
# gemini-2.0-flash 는 404(폐기)라 제외. flash-lite 는 503 상황에서 생성 성공 확인됨.
# pro 는 무료 한도가 빡빡하지만 둘 다 막혔을 때의 최후 보루.
_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


def _gen_text(
    api_key: str, contents: str, system_instruction: str,
    max_output_tokens: int, temperature: float,
    use_search: bool = False,
) -> str:
    """Gemini 생성 + 모델 폴백. 한 모델이 503/오류/빈응답이면 다음 모델로. 모두 실패 시 예외.
    use_search=True: Google Search Grounding 활성화 — 실시간 최신 정보를 검색 후 생성."""
    client = genai.Client(api_key=api_key)
    last_err: Exception | None = None
    tools = [gtypes.Tool(google_search=gtypes.GoogleSearch())] if use_search else None
    for i, model in enumerate(_GEMINI_MODELS):
        try:
            config_kwargs: dict = dict(
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
            if tools:
                config_kwargs["tools"] = tools
            # 2.5-flash/flash-lite thinking 비활성: 복잡한 정보성 프롬프트에서 thinking이
            # max_output_tokens를 잠식해 flash가 매번 '빈 응답'→flash-lite(짧음)로 폭락하던 근본원인
            # (2026-07-12 진단). thinking 끄면 flash가 직접 생성=길이·품질↑·빠름. pro는 thinking 필수라 제외.
            if "pro" not in model:
                config_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=gtypes.GenerateContentConfig(**config_kwargs),
            )
            text = (resp.text or "").strip()
            if text:
                if i > 0:
                    logger.info(f"[폴백모델] {model} 로 생성 성공")
                if use_search:
                    logger.info(f"[Search Grounding] {model} 실시간 검색 활성화됨")
                return text
            last_err = RuntimeError(f"{model} 빈 응답")
            logger.warning(f"{model} 빈 응답 → 다음 모델")
        except Exception as e:
            last_err = e
            logger.warning(f"{model} 생성 실패 → 다음 모델: {str(e)[:100]}")
    if last_err:
        raise last_err
    return ""


def _format_text_table(table_str: str) -> str:
    """파이프 구분 표 문자열 → 블로그에 보이기 좋은 텍스트 표"""
    rows = [r.strip() for r in table_str.strip().split("\n") if r.strip()]
    if not rows:
        return ""
    parsed = [[c.strip() for c in r.split("|")] for r in rows]
    col_count = max(len(r) for r in parsed)
    widths = []
    for c in range(col_count):
        w = max((len(r[c]) if c < len(r) else 0) for r in parsed)
        widths.append(max(w, 4))
    sep = "  |  ".join("-" * w for w in widths)
    lines_out = []
    for i, row in enumerate(parsed):
        cells = [row[c].ljust(widths[c]) if c < len(row) else " " * widths[c] for c in range(col_count)]
        lines_out.append("  |  ".join(cells))
        if i == 0:
            lines_out.append(sep)
    return "\n".join(lines_out)


def _format_faq_text(faq_str: str) -> str:
    """Q/A 블록 → 블로그 본문 FAQ 텍스트. (구버전 호환용)"""
    lines = [l.strip() for l in faq_str.strip().split("\n") if l.strip()]
    out = ["자주 묻는 질문", ""]
    for line in lines:
        out.append(line)
        out.append("")
    return "\n".join(out).strip()


def _faq_questions(faq_str: str) -> list[str]:
    """FAQ 원문에서 질문(Q) 줄만 추출"""
    return [l.strip() for l in faq_str.strip().split("\n") if l.strip().startswith("Q")]


# 종결어미 뒤 공백에서 문장 분리("~다. ", "~요. ", "~죠. ") — 소수점(4.72) 오분리 방지
_SENT_BOUNDARY = re.compile(r"(?<=[다요죠]\.)\s+")


def _split_long_paragraphs(body: str, limit: int = 150, target: int = 110) -> str:
    """모바일 가독성 후처리(§6): 여러 문장이 한 줄에 붙은 덩어리 문단을 문장 경계에서 분리.
    전 카테고리 공통(_parse_response에서 호출). 구조 마커([...]) 줄은 건드리지 않는다.
    - 일반 줄: 문장을 target자 이내 그룹으로 묶어 빈 줄(새 문단)로 분리
    - '· ' 불릿 줄: 각 문장을 각각의 불릿으로 분리"""
    out: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if len(s) <= limit or s.startswith("["):
            out.append(line)
            continue
        is_bullet = s.startswith("· ")
        sentences = [p.strip() for p in _SENT_BOUNDARY.split(s[2:] if is_bullet else s) if p.strip()]
        if len(sentences) < 2:
            out.append(line)
            continue
        if is_bullet:
            out.extend(f"· {sent}" for sent in sentences)
        else:
            groups: list[str] = []
            cur = ""
            for sent in sentences:
                if cur and len(cur) + len(sent) + 1 > target:
                    groups.append(cur)
                    cur = sent
                else:
                    cur = f"{cur} {sent}".strip()
            if cur:
                groups.append(cur)
            for gi, g in enumerate(groups):
                if gi:
                    out.append("")
                out.append(g)
    return "\n".join(out)


def _parse_faq_pairs(faq_str: str) -> list[tuple[str, str]]:
    """FAQ 원문에서 Q와 A를 짝지어 반환"""
    lines = [l.strip() for l in faq_str.strip().split("\n") if l.strip()]
    pairs = []
    current_q = None
    for line in lines:
        if line.startswith("Q") or line.startswith("Q:"):
            # 앞의 Q: 나 Q. 형태를 통일해서 정제
            current_q = line
        elif (line.startswith("A") or line.startswith("A:")) and current_q:
            pairs.append((current_q, line))
            current_q = None
    return pairs


_IMAGE_MARKER = re.compile(r"\[사진\d+\]")


def _strip_empty_table_cols(tstr: str) -> str:
    """표 문자열에서 항상 비어있는 열을 제거 (Gemini 3열 → 2열 정규화)."""
    rows_raw = []
    for ln in tstr.splitlines():
        ln = ln.strip()
        if not ln or set(ln) <= {'-', '|', ' ', '+'}:
            continue
        parts = [c.strip() for c in ln.split('|')]
        if parts and not parts[0]:
            parts = parts[1:]
        if parts and not parts[-1]:
            parts = parts[:-1]
        if parts:
            rows_raw.append(parts)
    if not rows_raw:
        return tstr
    n_cols = max(len(r) for r in rows_raw)
    if n_cols <= 2:
        return tstr
    rows_pad = [r + [""] * (n_cols - len(r)) for r in rows_raw]
    keep = [c for c in range(n_cols) if any(rows_pad[r][c] for r in range(len(rows_pad)))]
    if len(keep) >= n_cols:
        return tstr
    return "\n".join(" | ".join(rows_pad[r][c] for c in keep) for r in range(len(rows_pad)))


def _parse_response(raw: str) -> dict | None:
    try:
        lines = raw.strip().splitlines()
        result: dict = {"coupang_hints": [], "image_keywords": [], "image_labels": [], "faq_pairs": []}
        body_start = None

        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                t = line[6:].strip()
                # 제목 끝 (괄호) 카테고리 누출 제거: "...비법 (제품추천)" → "...비법"
                t = re.sub(r"\s*[\(（][^)）]{0,14}[\)）]\s*$", "", t).strip()
                result["title"] = strip_title_emphasis_markers(t)
            elif line.startswith("TAGS:"):
                result["tags"] = [t.strip() for t in line[5:].split(",") if t.strip()]
            elif line.startswith("COUPANG_HINT_"):
                result["coupang_hints"].append(re.sub(r"^COUPANG_HINT_\d+:\s*", "", line).strip())
            elif line.startswith("IMAGE_KEYWORDS:"):
                kws = line[15:].strip()
                result["image_keywords"] = [k.strip() for k in kws.split(",") if k.strip()]
            elif line.startswith("IMAGE_LABELS:"):
                lbls = line[13:].strip()
                result["image_labels"] = [l.strip() for l in lbls.split(",") if l.strip()]
            elif line.strip() == "---":
                body_start = i + 1
                break

        if body_start is None:
            for i, line in enumerate(lines):
                if line.strip() == "" and i > 3:
                    body_start = i + 1
                    break

        if body_start is not None:
            body_raw = "\n".join(lines[body_start:]).strip()

            # 표/FAQ 마커 추출 — 대괄호는 선택적(모델이 [ ]를 누락하는 경우 대비),
            # finditer로 모든 표/FAQ 블록을 처리(gov 글은 표 5개 이상).
            _TABLE_RE = re.compile(r"\[?\s*표시작\s*\]?\s*(.*?)\s*\[?\s*표끝\s*\]?", re.DOTALL)
            _FAQ_RE = re.compile(r"\[?\s*FAQ시작\s*\]?\s*(.*?)\s*\[?\s*FAQ끝\s*\]?", re.DOTALL)

            # 핵심 요약 블록 추출 → poster가 버티컬라인 인용구로 삽입
            _SUMMARY_RE = re.compile(r"\[?요약시작\]?\s*(.*?)\s*\[?요약끝\]?", re.DOTALL)
            summary_m = _SUMMARY_RE.search(body_raw)
            result["summary_text"] = summary_m.group(1).strip() if summary_m else ""

            def _clean_table_rows(t: str) -> str:
                """표 행 정화 — 모델이 프롬프트 지시문('★ [표시작] 마커를 반드시…')을 에코하면
                지시문 줄부터 표로 캡처돼 리터럴 행이 생김(2026-07-17 주거급여 라이브 실사고).
                실데이터 행은 반드시 '|' 구분이므로: 파이프 없는 줄·지시문·마커 잔재 줄 제거."""
                rows = []
                for ln in t.splitlines():
                    s = ln.strip()
                    if not s or "|" not in s:
                        continue
                    if "마커를" in s or "삽입됩니다" in s or "표시작" in s or "표끝" in s:
                        continue
                    rows.append(s)
                return "\n".join(rows)

            table_strs_raw = [_clean_table_rows(m) for m in _TABLE_RE.findall(body_raw)]
            table_strs = [_strip_empty_table_cols(t) for t in table_strs_raw if t.strip()]
            result["table_strs"] = table_strs
            result["table_str"] = table_strs[0] if table_strs else ""  # 하위호환(단일 표 기준 코드)

            faq_strs = [m.strip() for m in _FAQ_RE.findall(body_raw) if m.strip()]
            result["faq_str"] = faq_strs[0] if faq_strs else ""
            result["faq_pairs"] = []
            for fs in faq_strs:
                result["faq_pairs"].extend(_parse_faq_pairs(fs))

            body = body_raw
            # 요약/표/FAQ 마커 → 자리표시자. poster가 실제 컴포넌트로 교체.
            body = _SUMMARY_RE.sub("\n[요약삽입]\n", body)
            body = _TABLE_RE.sub("\n[표삽입]\n", body)
            body = _FAQ_RE.sub("\n[FAQ삽입]\n", body)
            # 짝이 안 맞아 남은 마커 잔재 제거(대괄호 유무 무관) — 본문에 ' 표끝' 등이 노출되지 않도록
            body = re.sub(r"\[?\s*(?:표시작|표끝|FAQ시작|FAQ끝)\s*\]?", "", body)
            # 쿠팡 플레이스홀더 제거
            body = re.sub(r"\[쿠팡추천\d+\]", "", body)
            # 마크다운/기호 제거 (Gemini 후처리)
            body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
            body = re.sub(r"__(.+?)__", r"\1", body)
            # 여러 줄에 걸친 볼드(**\n…\n**)는 위 단일행 정규식이 못 지워 '**'만 남은 줄이 생김.
            # 리터럴 노출 + 표/요약 앵커 오염(→ 헤더 이미지 삽입 실패, 2026-07-04 실라이브)이라 별표만 있는 줄 제거.
            body = re.sub(r"^\s*\*+\s*$\n?", "", body, flags=re.MULTILINE)
            # 선두 공백 허용: 모델이 중첩 서브불릿을 들여쓰기('    *   1인 가구')로 내면
            # 비들여쓰기용 '^[*\-•]'가 못 잡아 '*   '가 라이브에 리터럴 노출됨
            # (2026-07-06 주거급여 224338391607 실사고). 들여쓰기째 제거해 플랫 텍스트화.
            # ★선두 공백은 [ \t]만 — `\s`는 MULTILINE에서 앞의 개행까지 삼켜 '문단\n\n불릿'이
            # '문단\n불릿'으로 붙어버림(모바일 벽글, 2026-07-29 가이드 수리 중 발견·전 트랙 공용)
            body = re.sub(r"^[ \t]*[*\-•][ \t]+", "", body, flags=re.MULTILINE)
            body = re.sub(r"[✔★○□◆◇▶●►✓➡]", "", body)
            # 장식용/구조용 AI 이모지 제거 (소제목 앞 ✅💡 등 — AI틱 핵심)
            body = re.sub(r"[✅💡🛒📌👉🧹🥄💰📦]\s*", "", body)
            # 모델이 커스텀 [소제목] 마커 대신 마크다운 ATX 헤더(#~######)를 쓰는 경우 대비 —
            # 그대로 두면 "### 텍스트"가 스타일 적용 없이 본문에 리터럴 노출됨(실라이브 확인).
            body = re.sub(r"^#{1,6}\s+", "[소제목] ", body, flags=re.MULTILINE)
            # 모델이 "[무슨 일이 벌어졌나]"처럼 대괄호 라벨 단독줄을 소제목으로 쓰는 경우 대비 —
            # 기능 마커([사진N]/[표시작] 등)가 아닌 대괄호 단독줄은 [소제목]으로 정규화.
            # (2026-07-17 hyungsutech 실측: [핵심 요약 3줄]·[총평] 등이 스타일 없이 리터럴 노출)
            _func_markers = (
                r"사진\d+|표시작|표끝|FAQ시작|FAQ끝|요약시작|요약끝|구분선|소제목"
                r"|쇼핑추천|쿠팡추천\d*|표삽입|요약삽입|FAQ삽입|목차"
            )
            body = re.sub(
                rf"^\[(?!(?:{_func_markers})\])([^\[\]\n]{{2,40}})\]\s*$",
                r"[소제목] \1", body, flags=re.MULTILINE,
            )
            # 모델이 [소제목]/# 대신 HTML(<div ...><b>제목</b></div> 또는 <b>/<strong> 단독줄)을
            # 뱉는 경우 → [소제목]으로 변환해 스타일 유지. 그 외 잔여 태그는 제거해 리터럴 노출 방지
            # (2026-07-16 hyungsutech 실측: <div style=...><b>무슨 일이 있었나</b></div>가 본문에 노출).
            body = re.sub(
                r"^\s*<div[^>]*>\s*<(?:b|strong)>\s*(.+?)\s*</(?:b|strong)>\s*</div>\s*$",
                r"[소제목] \1", body, flags=re.MULTILINE | re.IGNORECASE,
            )
            body = re.sub(
                r"^\s*<(?:b|strong)>\s*(.+?)\s*</(?:b|strong)>\s*$",
                r"[소제목] \1", body, flags=re.MULTILINE | re.IGNORECASE,
            )
            body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
            # 실제 HTML 태그만 제거(< 뒤 ASCII 영문자) — 한글 '<사진>'·부등호 '5<10'은 보존
            body = re.sub(r"</?[a-zA-Z][^>]*>", "", body)
            # 모델이 ①②③ 대신 아라비아 "1. " 번호를 쓰면 SE ONE 오토포맷이 타이핑 중
            # 네이티브 번호 리스트를 만들어 리터럴 번호와 중복됨("2. 2." — 2026-07-06
            # 도시가스 라이브 실사고). 원형 숫자로 정규화해 오토포맷을 차단한다.
            # ※2026-07-28부터 원형숫자 줄은 native decimal로 변환하지 않고 리터럴 그대로
            # 발행 — 비인접 번호 항목이 항목마다 별도 <ol>로 쪼개져 "1. 1. 1."이 되는
            # 실사고(224359504392) 재발 차단. poster._native_list_type_of 주석 참고.
            def _arabic_to_circled(m: "re.Match[str]") -> str:
                n = int(m.group(1))
                return (chr(0x2460 + n - 1) + " ") if 1 <= n <= 20 else m.group(0)
            # 선두 공백 허용(위 불릿과 동일 이유 — 들여쓰기된 '  2. …'도 원형숫자로 정규화)
            # 선두는 [ \t]만(위 불릿과 동일 사유 — 앞 빈 줄 유실 방지, 2026-07-29)
            body = re.sub(r"^[ \t]*(\d{1,2})\.[ \t]+", _arabic_to_circled, body, flags=re.MULTILINE)
            # [소제목] 마커 — 텍스트를 따로 수집(poster가 제목 스타일 적용)한 뒤
            # 마커를 [구분선]\n으로 교체 → poster가 소제목 앞에 가로 구분선 자동 삽입
            result["subheadings"] = [
                s.strip() for s in re.findall(r"^\[소제목\]\s*(.+)$", body, flags=re.MULTILINE) if s.strip()
            ]
            body = re.sub(r"^\[소제목\]\s*", "[구분선]\n", body, flags=re.MULTILINE)
            # FAQ 스타일링: '자주 묻는 질문' 머리말은 소제목 처리
            if result.get("faq_str"):
                result["faq_questions"] = _faq_questions(result["faq_str"])
                if "자주 묻는 질문" not in result["subheadings"]:
                    result["subheadings"].append("자주 묻는 질문")
            body = re.sub(r"\n{3,}", "\n\n", body)
            # 인삿말 "안녕하세요 ~" 제거 (AI 패턴). 레시피 본문은 [사진1]로 시작하므로
            # 앞선 [사진N] 마커는 보존하고 인삿말 '문장'만 잘라낸다(도입부 나머지는 유지).
            body = re.sub(
                r"^((?:\s*\[사진\d+\]\s*)*)\s*안녕하세요[^.!?~\n]*[.!?~]?\s*",
                r"\1", body, flags=re.IGNORECASE,
            ).lstrip()
            # 폐지된 용어 교정(2026-07-19 점검: 보험·청약 글 반복 발생) — 2020년 폐지된
            # '공인인증서'를 현행 '공동인증서'로. '(구 공인인증서)' 같은 역사적 언급만 보존.
            body = re.sub(r"(?<!구 )공인인증서", "공동인증서", body)
            result["body"] = _split_long_paragraphs(body.strip())

        if "title" not in result or "body" not in result:
            logger.warning("파싱 실패")
            return None

        result.setdefault("tags", [])
        result.setdefault("image_labels", [])
        result.setdefault("subheadings", [])
        result.setdefault("faq_questions", [])
        return result
    except Exception as e:
        logger.error(f"파싱 오류: {e}")
        return None


_OUTLINE_SYSTEM = """\
너는 '현지언니' 블로그 글의 기획자야. 키워드를 받아서 '횡설수설하지 않는 한 편의 일관된 글' 설계도를 짜.

출력 형식 (정확히 이 4줄):
제목: {핵심키워드를 앞에 + | + 후킹표현, 30자 이내. 카테고리명이나 (괄호) 절대 넣지 마}
요점: {이 글이 독자에게 전하는 단 하나의 메시지/결론을 한 문장으로. 제목이 약속한 바로 그것}
섹션: {요점을 뒷받침하는 소제목 4개를 | 로 구분. 순서대로 읽으면 하나의 이야기가 되도록}
표주제: {비교표로 보여줄 것 한 줄 — 요점과 직결된 것만}

규칙:
- 제목과 요점은 반드시 일치 (제목이 '식비 10만원 아낀 법'이면 요점도 '어떻게 10만원 아꼈는지')
- 섹션 4개는 서로 다른 얘기 나열이 아니라, 요점을 향해 쌓이는 흐름(기-승-전-결)
- 한 글 = 한 주제. 곁가지·딴 얘기 금지.
- 제목엔 카테고리명("제품추천" 등) 절대 붙이지 마.
"""


def _generate_outline(keyword: str, category: str, trending: list[str] | None, api_key: str) -> dict:
    """글 설계도(제목/요점/섹션/표주제) 생성 → 본문 일관성 확보. 실패 시 빈 dict."""
    trend = f"\n참고 트렌딩: {', '.join(trending[:3])}" if trending else ""
    cat = f"\n카테고리(참고만): {category}" if category else ""
    user = f"키워드: {keyword}{cat}{trend}\n\n위 키워드로 일관된 블로그 글 설계도를 짜줘."
    try:
        raw = _gen_text(api_key, user, _OUTLINE_SYSTEM, 1024, 0.95)
        out: dict = {}
        fields = [("제목:", "title"), ("요점:", "thesis"), ("섹션:", "sections"), ("표주제:", "table_topic")]
        for line in raw.splitlines():
            s = line.strip()
            for key, field in fields:
                if s.startswith(key):
                    out[field] = s.split(":", 1)[1].strip()
        if out.get("title") and out.get("thesis"):
            logger.info(f"설계도 OK — 제목:{out['title']!r} / 요점:{out['thesis']!r}")
            return out
        logger.warning("설계도 파싱 실패 — 설계도 없이 진행")
    except Exception as e:
        logger.warning(f"설계도 생성 실패 (무시): {e}")
    return {}


_REFINE_SYSTEM = """\
너는 블로그 글 퇴고 전문가야. '현지언니' 블로그 초안을 받아서, 형식은 그대로 두고
본문 문장만 더 사람이 쓴 것처럼 자연스럽게 고쳐줘.

[절대 그대로 유지 — 건드리지 마]
- 맨 위 TITLE: / TAGS: / COUPANG_HINT_*: / IMAGE_KEYWORDS: / IMAGE_LABELS: 줄과 값
- --- 구분선
- [사진N] 마커 전부(입력에 있는 개수·위치 그대로 — 숫자 추가/삭제 금지), [표시작]...[표끝], [FAQ시작]...[FAQ끝], [소제목] 마커
- 출력은 입력과 똑같은 형식 (위 마커가 전부 살아있어야 함)

[본문을 이렇게 고쳐라 — 12가지]
1. AI 단어 제거: 이로써/이처럼/혁신적인/효율적인/극대화/탁월한/최적의/필수적인/선사/마련해보세요/다양한 ~/도움이 되길/기억하세요/매우 ~/살펴보겠습니다/첫째, 둘째/지금부터 → 일상 구어체
2. 번역투 제거: ~를 통해/~함으로써/~에 있어서 → ~해서/~니까/~거든요
3. 교과서체 제거: ~것이 중요합니다/하는 게 좋습니다/하시면 됩니다/도움이 되길 바랍니다 → 솔직한 경험담
   (★해요체 변형도 동일 금지: ~것이 중요해요/좋아요/하시면 돼요 — 한 글 1회 이내, 2026-07-24)
4. 짜깁기 느낌 제거: 단락끼리 자연스럽게 이어지게, 반복·뜬금없는 주제 전환 정리
5. 정체성 강화: 리뷰글이면 솔직 총평 + 좋았던 점/아쉬운 점 + 추천대상 한 줄을 분명히
6. 1인칭 경험 강화: 막연한 일반론을 '내가 직접 ~했을 때' 구체담으로
7. 문장 리듬 다양화: 짧은 문장과 긴 문장 섞기 (전부 비슷한 길이 금지)
8. 디테일 또렷하게: 가격·날짜·브랜드·상황 구체화
9. 이모지 정리: 장식용 이모지(✅💡🛒📌👉 등) 전부 제거, 감정용 0~2개만
10. 도입부가 공식적이면(혹시~신가요/오늘은~알려드릴게요) 완전히 다른 방식으로 다시 써라
11. 마무리가 '~알아보았습니다/도움이 되셨으면'이면 개인 소감 + 다음 계획으로 바꿔라
12. 과장·광고 톤 빼고 솔직하게 (단점도 한 줄 인정)
13. ★반말 종결 교정(최우선): 반말로 끝나는 문장("~했다./~이다./~있다./~된다./~같다./~거든./~잖아./~해./~돼." 등)을 전부 존댓말(~요/~죠/~습니다)로 바꿔라. 단, 큰따옴표·작은따옴표 안 인용문("이건 해야 한다"라고 등)은 그대로 둔다. 존댓말 블로그에 반말 문장이 한 개라도 남으면 실패다.

길이는 유지하거나 살짝 늘려도 됨. 출력은 고친 전체 글(형식 포함)만. 설명/따옴표 붙이지 마.
"""


def _refine_draft(raw_draft: str, api_key: str, min_photos: int = 2) -> str:
    """초안을 사람처럼 자연스럽게 퇴고. 형식/마커 보존 검증 통과 시만 채택, 아니면 원본 반환."""
    try:
        refined = _gen_text(api_key, f"아래 초안을 퇴고해줘:\n\n{raw_draft}", _REFINE_SYSTEM, 8192, 0.8)
        # 형식 보존 검증: 초안에 존재하던 핵심 마커가 퇴고본에도 잘 보존되어 있는지 체크
        has_table = "[표시작]" in raw_draft
        has_faq = "[FAQ시작]" in raw_draft
        
        ok_table = ("[표시작]" in refined) if has_table else True
        ok_faq = ("[FAQ시작]" in refined) if has_faq else True
        
        if (refined and "TITLE:" in refined
                and refined.count("[사진") >= min_photos
                and ok_table and ok_faq):
            return refined
        logger.warning(f"퇴고 결과 형식 깨짐 (표/FAQ 일치여부: {ok_table}/{ok_faq}, 사진 수: {refined.count('[사진')}/{min_photos}) — 원본 유지")
    except Exception as e:
        logger.warning(f"퇴고 실패 (원본 유지): {e}")
    return raw_draft


def generate_post(
    keyword: str,
    api_key: str,
    trending: list[str] | None = None,
    category: str = "",
    feedback: list[str] | None = None,
) -> dict | None:
    """
    keyword: 오늘 포스팅 키워드
    category: 카테고리 이름 (글쓰기 방향 힌트로 활용)
    반환: {title, tags, body, coupang_hints, table_str, faq_str, image_keywords}
    body에는 [사진N] 마커 포함 — naver_blog.py에서 이미지 삽입 위치로 활용
    """
    trend_note = ""
    if trending:
        trend_note = f"\n참고 트렌딩 (자연스럽게 연결되면 살짝 언급, 억지로 넣지 말 것): {', '.join(trending[:3])}"

    _PATTERN_MAP = {
        "청소정리": "패턴 A", "신혼살림기초": "패턴 A", "인테리어": "패턴 A",
        "쇼핑정보": "패턴 A", "요리식비": "패턴 B", "절약재테크": "패턴 C",
        "신혼일상": "패턴 D", "제품리뷰": "패턴 E", "정보성": "패턴 F",
    }
    pattern_hint = _PATTERN_MAP.get(category, "")
    category_note = (
        f"\n카테고리: {category}" + (f" → 반드시 [{pattern_hint}] 레이아웃 적용" if pattern_hint else "")
        if category else ""
    )

    # ── 설계도 먼저: 제목/요점/섹션 흐름을 잡아 '제목-본문 일치 + 한 가지 요점' 확보 ──
    outline = _generate_outline(keyword, category, trending, api_key)
    outline_note = ""
    if outline:
        outline_note = (
            f"\n\n[글 설계도 — 반드시 이대로 써라]"
            f"\n제목(이걸 TITLE 줄에 그대로, 괄호·카테고리명 없이): {outline['title']}"
            f"\n★이 글의 단 하나의 요점: {outline['thesis']}"
            f"\n  → 본문 전체가 이 요점만 향한다. 제목이 약속한 걸 본문에서 반드시 지킨다(제목-본문 불일치 금지)."
            f"\n섹션 흐름(이 순서대로 [소제목] 4개, 각 섹션은 요점을 한 단계씩 쌓는다): {outline.get('sections', '')}"
            f"\n비교표 주제(요점과 직결된 것만): {outline.get('table_topic', '')}"
            f"\n곁가지·딴 얘기·관련없는 정보 나열 금지. 끝까지 읽으면 하나의 이야기가 되게."
        )

    # 매 글마다 도입부 스타일을 랜덤으로 강제 → 천편일률 공식 도입부 방지 (유사문서/AI 신호 회피)
    intro_styles = [
        "구체적인 장면과 시간 묘사로 시작 (예: '어제 저녁 8시, 싱크대 앞에서')",
        "의외의 숫자나 사실을 먼저 툭 던지며 시작 (예: '한 달에 1만 2천원이 줄었어요')",
        "내 실패담을 자백하며 시작 (예: '저 이거 1년을 잘못 쓰고 있었어요')",
        "결론부터 말하는 역두괄식으로 시작 (예: '결론부터 말하면 답은 ~였어요')",
        "남편이나 신혼 생활의 한 장면 에피소드로 시작",
    ]
    intro_hint = random.choice(intro_styles)

    feedback_note = ""
    if feedback:
        feedback_note = (
            f"\n\n⚠️ [이전 초안 품질 검토 실패 - 수정 지침]"
            f"\n이전 생성된 글에서 다음과 같은 품질 이슈가 발견되었습니다. 이번 생성 시에는 아래 지적사항을 철저히 보완하고 수정하여 작성해 주세요:"
            f"\n- " + "\n- ".join(feedback)
        )

    user_msg = (
        f"오늘 포스팅 키워드: {keyword}"
        f"{category_note}"
        f"{trend_note}"
        f"{outline_note}"
        f"{feedback_note}"
        f"\n\n위 설계도와 너의 페르소나, 그리고 카테고리에 맞는 [레이아웃 패턴]에 맞추어 현지언니 블로그 글을 작성해줘."
        f"\n제목은 설계도 제목을 그대로 TITLE에 쓰고, 본문은 그 요점 하나만 끝까지 정합성 있게 밀고 가."
        f"\n[이번 글 도입부 스타일] {intro_hint}"
        f" — '혹시 ~신가요 / 솔직히 저도 / 오늘은 제가 ~알려드릴게요 / 이 글 하나만'식 공식 도입부는 절대 금지."
        f"\n본문에 들어갈 마커들([사진1]~[사진N], [표시작]...[표끝], [FAQ시작]...[FAQ끝])은 카테고리 레이아웃 구조에 맞춰 자연스럽게 필요한 부분에만 유연하게 넣어줘."
        f"\n사진 마커([사진N])는 2~4장 범위로만 제한해서 넣고, IMAGE_KEYWORDS 줄에는 본문에서 실제 사용한 사진 마커의 개수와 정확히 매치되는 개수만큼 영어 검색어를 쉼표로 작성해줘."
        f"\n또한, IMAGE_LABELS 줄에는 사진 마커 개수와 정확히 매치되는 개수만큼, 각 사진을 '한눈에 보는 요약 카드'로 만들 내용을 쉼표로 작성해줘. 각 항목은 '제목 :: 요점1 · 요점2 · 요점3' 형식(제목 12자 이내, 요점은 가운뎃점·으로 구분, 각 요점 10자 내외, 가능하면 수치 포함). 예: 다이소 청소포 추천 :: 1+1 2000원 · 극세사 재질 · 물걸레 겸용,거실 먼지 제거 :: 위에서 아래로 · 정전기포 활용 · 주 2회,솔직 총평 :: 가성비 최고 · 내구성 보통 · 재구매 의향. ※ 쉼표(,)는 카드 구분용이니 요점 안에는 쉼표 금지(가운뎃점· 만 사용)."
        f"\n본문은 최소 2500자 이상으로 작성하고, 제목은 15~35자 사이로 해줘."
        f"\n각 단락은 2~3줄 이하로 짧게 끊고, 줄줄이 길게 풀어쓰지 마. 단락 사이 빈 줄을 자주 넣어 모바일 환경의 가독성을 극대화해줘."
    )

    waits = [15, 40, 90, 180]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, _SYSTEM, 8192, 0.9)
            if not raw:
                logger.error(f"Gemini 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if parsed:
                # [사진N] 제거 후 실제 본문 길이 계산
                body_clean = _IMAGE_MARKER.sub("", parsed.get("body", ""))
                body_len = len(body_clean)
                title_len = len(parsed.get("title", ""))
                img_marker_count = len(_IMAGE_MARKER.findall(parsed.get("body", "")))
                logger.info(
                    f"글 생성 완료: {parsed.get('title')!r} "
                    f"(본문 {body_len}자, 제목 {title_len}자, "
                    f"이미지마커 {img_marker_count}개, "
                    f"표: {'있음' if parsed.get('table_str') else '없음'}, "
                    f"FAQ: {'있음' if parsed.get('faq_str') else '없음'}, "
                    f"이미지키워드: {len(parsed.get('image_keywords', []))}개)"
                )
                if body_len < 500:
                    logger.warning(f"본문 너무 짧음 ({body_len}자) — 재생성 시도")
                    continue
                # ── 퇴고(refinement) 패스: 초안을 사람처럼 다듬기 (품질 최대 지렛대) ──
                # 동적으로 생성된 이미지 마커 수만큼 검사 조건 전달
                min_photos = max(2, img_marker_count)
                refined_raw = _refine_draft(raw, api_key, min_photos=min_photos)
                if refined_raw != raw:
                    refined_parsed = _parse_response(refined_raw)
                    if refined_parsed:
                        rb_len = len(_IMAGE_MARKER.sub("", refined_parsed.get("body", "")))
                        if rb_len >= 500:
                            logger.info(f"퇴고 적용: 본문 {body_len}→{rb_len}자")
                            return refined_parsed
                    logger.warning("퇴고본 품질 미달 — 초안 사용")
                return parsed
        except Exception as e:
            logger.error(f"Gemini 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 건강 정보 포스트 생성 (젤리윤/뚠버 스타일 — 항목별 나열 + 연구 인용)
# ══════════════════════════════════════════════════════════════════════════════

# 처방약 키워드 — 면책사항 자동 삽입 트리거
_RX_PATTERN = re.compile(
    r"마운자로|오젬픽|삭센다|위고비|GLP.?1|큐시미아|처방|비만치료제|주사다이어트"
)

_HEALTH_SYSTEM = """\
너는 네이버 블로그 건강 정보 카테고리 전문 작가야.
스타일: 짧은 줄 + 불렛 중심의 고가독성 건강 정보 블로그.

══════════════════════════════════════════
[제목 패턴]
══════════════════════════════════════════
- "~이 아니었습니다 | 의외의 N가지 이유"
- "~에 좋은 음식 N가지 | 연구로 증명된 효과"
- "굶어도 안 되는 이유 | ~해결법 N가지"
형식: 30자 이내

══════════════════════════════════════════
[글 구조 — 반드시 이 순서 그대로 출력]
══════════════════════════════════════════

(도입부: 2~3줄만. 독자 고민 공감 + 핵심 한 줄. "안녕하세요/오늘은" 금지.)
(예시)
탈모가 스트레스 때문만은 아닙니다.
전문가들은 생활 습관과 영양 결핍을 더 큰 원인으로 꼽습니다.
오늘은 의외의 진짜 원인 6가지를 알아봅니다.

[사진1]

[요약시작]
✔ 핵심: (글 전체 결론 한 줄)
✔ 꼭 볼 것: (가장 중요한 항목 1개)
✔ 실천 팁: (지금 바로 할 수 있는 한 가지)
[요약끝]

[소제목] 첫 번째 항목명 (번호 없이 핵심 키워드로)
[사진2]
(내용: 4~5줄. ★각 줄은 반드시 '· '(가운뎃점+공백)로 시작. 별표(*)·하이픈(-)·점(•) 금지.)
· 핵심 수치 (예: 38%가 해당, 1.5배 높음)
· 연구 기관명 + 인원/기간 포함
· 실생활 활용 팁 1줄
· 권장 식품/방법 2~3가지

[소제목] 두 번째 항목명 (번호 없이 핵심 키워드로)
[사진3]
(내용: 동일 형식. 모든 줄 '· '로 시작.)
· 핵심 수치
· 연구 기관명 + 인원/기간
· 실생활 활용 팁
· 권장 식품/방법

(이하 나머지 항목도 동일 패턴 반복 — 소제목엔 번호 없이 핵심 키워드만)

[소제목] 한눈에 정리
(아래 표는 반드시 3열 — 항목·핵심효과·근거수치. 각 셀 핵심 단어만 10자 이내, 문장·괄호 설명 금지. 빈칸 금지: 세 칸 모두 의미 있는 값.)
[표시작]
항목 | 핵심 효과 | 근거 수치
(항목1) | (효과1) | (수치1)
(항목2) | (효과2) | (수치2)
(항목3) | (효과3) | (수치3)
[표끝]

[마무리]
개인차가 있으므로 전문의 상담을 권장합니다.

══════════════════════════════════════════
[절대 규칙]
══════════════════════════════════════════
• [사진N] 마커는 반드시 단독 줄에 위치 (문장 안에 절대 삽입 금지)
• [사진1]: 도입부 2~3줄 바로 다음에 단독 배치 (도입부가 먼저, 사진1이 나중)
• [요약시작]~[요약끝]: [사진1] 바로 뒤에 1쌍. ✔ 3줄(핵심/꼭볼것/실천팁)
• [표시작]~[표끝]: '한눈에 정리' 소제목에 1쌍. 반드시 3열(항목|핵심효과|근거수치), 각 셀 10자 이내, 빈칸 금지
• [사진2+]: 각 [소제목] 바로 다음 줄에 [사진N], 그 다음 줄부터 내용
• 내용은 짧은 줄로 나눌 것 (한 문장 = 한 줄)
• ★항목 내용의 모든 줄은 '· '(가운뎃점 U+00B7 + 공백)로 시작 — '•'(점)·별표·하이픈 금지. 긴 단락 금지
• 소제목 텍스트 맨 앞에 번호(①/1.) 붙이지 마라 (회색바+볼드로 구분됨)
• 금지: 안녕하세요/이처럼/이로써/혁신적인/마크다운(#)

══════════════════════════════════════════
[출력 형식]
══════════════════════════════════════════
TITLE: {제목 — 30자 이내}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6}
IMAGE_KEYWORDS: health header,{사진2 영어},{사진3 영어},{사진4 영어},...
IMAGE_LABELS: {키워드},사진2 한글,사진3 한글,사진4 한글,...
---
{본문 — 위 구조 그대로, 총 1,200~1,800자 (모바일 스캔형, 정보 밀도 우선)}

★★★ 마커 체크리스트 — 출력 전 반드시 확인 ★★★
- [사진N] 각 단독 줄에 존재하는가
- [요약시작]~[요약끝] 정확히 1쌍 ([사진1] 바로 뒤)
- [표시작]~[표끝] 정확히 1쌍 (3열·항목|핵심효과|근거수치, 빈칸 없음)
- [소제목] 마커가 각 항목 + '한눈에 정리'에 있는가 (번호 없이)
"""

_HEALTH_REFINE_SYSTEM = """\
너는 건강 블로그 퇴고 전문가야. 초안을 받아서 형식은 그대로 두고 내용만 더 자연스럽게 다듬어라.

[절대 그대로 유지]
- TITLE: / TAGS: / IMAGE_KEYWORDS: / IMAGE_LABELS: 줄 전체
- --- 구분선
- [사진N] 마커 — 위치 변경 금지, 문장 안에 삽입 절대 금지
- [요약시작]~[요약끝] (1쌍, 삭제·이동 금지), [표시작]~[표끝] (1쌍, 3열 유지·열변경 금지)
- [소제목] 마커 (소제목 텍스트 맨 앞에 번호 ①/1. 붙이지 말 것 — 회색바+볼드로 구분됨)

[고쳐야 할 것]
1. AI 단어 제거: 이로써/이처럼/혁신적인/탁월한/극대화 → 자연스러운 표현
2. 내용이 한 덩어리 긴 단락이면 짧은 줄로 나누고 각 줄을 '· '(가운뎃점)로 시작하라
3. 도입부가 "안녕하세요/오늘은"으로 시작하면 독자 고민 공감 문장으로 바꿔라
4. 각 항목에 실생활 활용 팁 1줄 추가
5. 수치/연구 인용이 없으면 추가해라
6. ★반말 종결 문장("~했다./~이다./~있다./~된다." 등)이 있으면 전부 존댓말(~요/~습니다)로 교정하라(단, 따옴표 안 인용문은 제외)

출력: 고친 전체 글(형식 포함). 설명 없이 바로 출력.
"""


def generate_health_post(
    keyword: str,
    api_key: str,
    health_category: str = "",
) -> dict | None:
    """
    건강 정보 포스트 생성 (젤리윤/뚠버 스타일 항목별 나열).
    반환: {title, tags, body, image_keywords, image_labels, subheadings, is_rx}
    is_rx=True 시 처방약 면책사항 포함됨.
    """
    is_rx = bool(_RX_PATTERN.search(keyword))

    rx_note = ""
    if is_rx:
        rx_note = (
            "\n\n⚠️ [처방약 키워드 감지] 이 글에는 반드시 마지막에 다음 면책사항을 포함해라:"
            '\n"※ 이 글은 정보 제공 목적이며 의학적 조언이 아닙니다. '
            '마운자로 등 처방약은 반드시 의사와 상담 후 처방받으시기 바랍니다."'
        )

    # 항목 수 랜덤화 (5~7개) — 매번 다른 구조로 단조로움 방지
    item_count = random.choice([5, 5, 6, 7])

    user_msg = (
        f"건강 정보 키워드: {keyword}"
        + (f"\n카테고리 힌트: {health_category}" if health_category else "")
        + f"\n\n위 키워드로 '{item_count}가지' 항목 나열 형식의 건강 정보 글을 작성해라."
        + "\n각 항목에는 구체적인 연구 기관명, 대상 인원, 기간, 수치 결과를 포함하고 200~300자로 간결하게 써라(모바일 스캔형)."
        + "\n- [요약시작]...[요약끝] 1쌍 필수: [사진1] 바로 뒤, ✔ 핵심/꼭볼것/실천팁 3줄."
        + "\n- [표시작]...[표끝] 1쌍 필수: '한눈에 정리' 소제목에, 반드시 3열(항목|핵심효과|근거수치), 각 셀 10자 이내, 빈칸 금지."
        + "\n- 본문 1,200~1,800자. 소제목엔 번호 붙이지 마라."
        + "\n이미지 규칙: IMAGE_KEYWORDS[0]='health header'(고정값), IMAGE_KEYWORDS[1]부터 음식/재료 영어 키워드."
        + "\n본문 [사진1]은 최상단 첫 줄에 배치, [사진2]~[사진N]은 각 항목 내용 끝 다음 줄에 배치."
        + rx_note
    )

    waits = [15, 40, 90]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, _HEALTH_SYSTEM, 8192, 0.85)
            if not raw:
                logger.error(f"건강글 Gemini 빈 응답 (시도 {attempt})")
                continue

            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"건강글 파싱 실패 (시도 {attempt})")
                continue

            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            img_count = len(_IMAGE_MARKER.findall(parsed.get("body", "")))

            if body_len < 800:
                logger.warning(f"건강글 본문 너무 짧음 ({body_len}자) — 재생성")
                continue

            # ★반말 종결 게이트(존댓말 강제, 2026-07-27)
            banmal = banmal_gate(parsed.get("body", ""), parsed.get("faq_str", ""),
                                 parsed.get("summary_text", ""))
            if banmal:
                logger.warning(f"건강글 반말 종결 {len(banmal)}건({banmal[0]!r} 등) — 재생성")
                continue

            logger.info(
                f"건강글 생성 완료: {parsed.get('title')!r} "
                f"(본문 {body_len}자, 이미지 {img_count}개, 처방약={is_rx})"
            )

            # 퇴고 패스 — 실패해도 원본 반환 (퇴고 503이 글 생성 실패로 오인되지 않도록)
            try:
                refined_raw = _gen_text(
                    api_key,
                    f"아래 건강 블로그 초안을 퇴고해줘:\n\n{raw}",
                    _HEALTH_REFINE_SYSTEM, 8192, 0.75,
                )
                if refined_raw:
                    refined = _parse_response(refined_raw)
                    if (refined and len(_IMAGE_MARKER.sub("", refined.get("body", ""))) >= 800
                            and not banmal_gate(refined.get("body", ""), refined.get("faq_str", ""))):
                        refined["is_rx"] = is_rx
                        rb_len = len(_IMAGE_MARKER.sub("", refined.get("body", "")))
                        logger.info(f"건강글 퇴고 적용: {body_len}→{rb_len}자")
                        return refined
            except Exception as refine_err:
                logger.warning(f"건강글 퇴고 실패 — 원본 사용: {refine_err}")

            parsed["is_rx"] = is_rx
            return parsed

        except Exception as e:
            logger.error(f"건강글 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# 정부지원·혜택 포스트 생성 (패턴 F — 정보형)
# ══════════════════════════════════════════════════════════════════════════════

_GOV_SYSTEM = """\
너는 네이버 블로그 정부지원·혜택 핵심 정리 전문 작가야.
신혼부부·청년·직장인이 놓치기 쉬운 혜택을 모바일 독자가 5분 안에 파악할 수 있게 핵심만 정리한다.

══════════════════════════════════════════
[제목 패턴 — 반드시 실제 금액/수치 포함]
══════════════════════════════════════════
- "2026 [혜택명] | 최대 [금액] 받는 조건과 신청법"
- "[혜택명] | [대상] 놓치면 손해, [금액] 총정리"
- "[혜택명] 신청 조건 | [금액] 이렇게 받으세요"
규칙: 제목에 반드시 구체적 금액·수치 포함. 35자 이내.
★압축형 제목 공식(노매새드 벤치마킹) — [대상]+[금액 또는 마감일]+[핵심조건] 3요소를 한 줄에 압축(셋 다 어려우면 최소 2개).
  '누가·얼마·무슨 조건이면'이 제목만 봐도 잡히게. 예) "2030 신혼이면 최대 ○○만원 — 놓치면 손해",
  "만 34세 이하 무주택자, ○○지원금 신청 조건 총정리".
  ★금액·마감일은 반드시 [팩트]·검증 수치에 있는 값과 일치(제목에서 부풀리기·없는 마감일 지어내기 금지). 과장·낚시(어그로) 금지.

══════════════════════════════════════════
[글 구조 — 모바일 스캔형. 이 순서 그대로]
══════════════════════════════════════════

[사진1]
(서론 — 노매새드 스타일. 5~7문장, 1문장=1문단(문장마다 줄바꿈), 전체 250자 이내.
 첫 문장: 유저 메시지의 [이번 글 서론 훅 유형] 지시 그대로 시작.
 넷째 문장 안에 반드시 '결론부터 말하면 ~입니다. 다만 ~' 구조로 핵심 금액·결론+단서 제시.
 서론 마지막 문장은 반드시 '~정리해보겠습니다.'로 종결. "안녕하세요" 절대 금지.)

[요약시작]
✔ 지원 금액: (최대 금액 한 줄)
✔ 신청 대상: (나이·소득 조건 한 줄)
✔ 신청 방법: (온라인/오프라인 경로 한 줄)
[요약끝]

[소제목] 01 한눈에 보는 핵심 정보
(소제목 바로 아래 1~2문장으로 핵심 정보 요약.)
★ [표시작] 마커를 반드시 정확히 써야 표가 블로그에 삽입됩니다 ★
(★아래 요약표는 반드시 2열 '구분 | 내용' — 구분 셀 8자 이내, 내용 셀 20자 이내(핵심 수치 포함).
 빈칸 금지. 3열 금지.)
[표시작]
구분 | 내용
대상 | 만8세 미만 아동
지원 금액 | 월 10만원
핵심 조건 | 60일내 신청 시 소급
신청·확인 | 복지로·주민센터
[표끝]
(표 아래 1줄: '출처: (복지로 등 공식 기관), 2026년 기준' + 제도명·신청기간·문의처 한 문장.)

[소제목] 02 신청 자격 — 내가 해당되나?
(조건을 짧은 줄로 나열. 한 줄 = 조건 하나. · 가운뎃점 기호 사용, 대시(-) 금지.
 ★2단 계층 필수: 상위 분류(소득 조건/재산 조건/가구 유형 등)와 그 세부 항목이 같은 · 글머리를 쓰면 레벨이 안 맞아 보인다.
   → 상위 분류는 [[분류명]]으로 볼드 라벨 한 줄(글머리 · 붙이지 말 것), 그 아래 세부 항목만 · 불릿.
 ★'여러 대상 × 여러 값'도 표로 만들지 말고 불릿으로 압축 — 표는 01 요약표·03 계산표 2개 고정.)
[[소득 조건]]
· 단독 가구: 총소득 ~만원 미만
· 홑벌이 가구: 총소득 ~만원 미만
[[재산 조건]]
· 가구 재산 합계 ~억원 미만
[[기타]]
· 나이·국적 등 해당 시

[소제목] 03 얼마나 받을 수 있을까?
(★시나리오 계산 섹션 — 특정 대상·금액을 가정해(예: '2인 가구·월 소득 200만원 가정') 그 가정을 표 바로 위에
 1문장으로 쓰고, 아래 3열 계산표로 정리한 뒤, 표 아래에서 계산 과정을 1~2문장으로 풀어 서술.
 수치는 [팩트]·검증 수치만 사용, 셀 12자 이내.)
[표시작]
구분 | 계산 | 결과
(항목1) | (식·기간) | (금액)
(항목2) | (식·기간) | (금액)
(항목3) | (식·기간) | (금액)
[표끝]

[소제목] 04 신청 전 꼭 알아둘 점 — 뭘 조심해야 할까?
(놓치기 쉬운 주의사항·중복수혜 가능 여부 등을 짧은 줄로. 표 없이 · 불릿 또는 2~3줄 문장.)
· ~
· ~

[소제목] 05 신청 방법 — [사이트명/기관]에서 N분이면 끝
(신청 단계를 짧은 줄로 정리. 반드시 ①②③ 기호 사용 — 1. 2. 3. 같은 숫자·점 조합 금지.)
① ~
② ~
③ ~
(필요 서류: 짧게 나열)

[소제목] 자주 묻는 질문
★ [FAQ시작] 마커를 반드시 정확히 써야 FAQ가 블로그에 삽입됩니다 ★
(★FAQ 스펙 — 노매새드 벤치마킹 표 형식: Q는 4~5개, 독자가 실제 검색할 법한 질문으로.
 각 답변(A)은 반드시 "네." 또는 "아닙니다."로 시작하는 1~2문장 + 본문의 핵심 숫자(금액·기간·비율 등) 1개 이상 포함.
 발행 시 1열 표(첫 행 "자주묻는질문(FAQ)")로 렌더되므로 Q·A 모두 각 1~2문장으로 짧고 완결되게.)
[FAQ시작]
Q: (가장 많이 묻는 질문 1 — 구체적으로)
A: (네./아닙니다. + 핵심 숫자 포함 1~2문장)
Q: (질문 2)
A: (답변)
Q: (질문 3)
A: (답변)
Q: (질문 4)
A: (답변)
[FAQ끝]

(마무리 — FAQ 뒤 4~6줄, 각 줄 1문장(1문장=1문단):
 ①'결국 ~'으로 시작하는 핵심 결론 1문장
 ②본문 핵심 숫자(금액·기간) 1개를 다시 강조하는 1문장 — 공식 확인 경로·문의처 포함 가능
 ③독자가 오늘 바로 할 일 1문장
 ④마지막 줄은 확인 체인 한 줄 — '(단계1) → (단계2) → (단계3)' 형식. 예: '자격 확인 → 서류 준비 → 복지로 신청')

══════════════════════════════════════════
[작성 원칙]
══════════════════════════════════════════
1. 정확성 최우선: 금액·조건·기간은 [팩트]·검색 근거에 있는 것만 단정.
   ★근거 없는 정책 수치(지원금액·소득기준·재산기준·중위소득 환산액)는 학습 기억으로
   지어내지 마라 — 이런 수치는 매년 바뀐다(예: 중위소득 기준액 매년 인상, 긴급복지
   생계지원 단가 연도별 변동). 근거 없으면 '가구원 수·연도에 따라 다름(복지로 확인)'으로
   처리하고 확인 경로를 제시. 불확실한 수치는 '(2025년 기준)'처럼 연도 출처 병기
2. 수치 필수: 나이·소득·금액·기간은 근거 있는 것을 숫자로 명시(지어내기 금지)
3. 표는 정확히 2개: ①01 섹션 2열 요약표(구분|내용) ②03 섹션 3열 시나리오 계산표(구분|계산|결과). 더 만들지 마라
4. 요약표는 2열(구분 8자·내용 20자 이내), 계산표는 3열(셀 12자 이내) — 빈칸 금지, 모든 칸 의미 있는 값. 그 외 정보(자격·주의사항)는 표 대신 · 불릿으로
4-1. ★전문용어(기준 중위소득, 보장기관, 소득인정액 등)는 첫 등장 '바로 다음 줄'에 단독 줄 '❓ 용어: 한 줄 정의'를 넣어라(예: '❓ 소득인정액: 소득에 재산을 환산해 더한 금액'). 글에서 1~2개만, 표·소제목·FAQ 안 금지
5. ★본문 2,200~2,800자 (스캔하기 좋은 밀도, 정보 심화). 계산 예시는 03 계산표+서술로 포함
5-1. ★요약표 아래 '출처: (복지로·고용24 등 공식 기관)' 1줄 필수
5-2. ★신뢰 근거(E-E-A-T, 노매새드 벤치마킹): 본문 마무리 직전에 '어디서 최종 확인하는지' 근거 문장을 한 줄 넣어라.
   단 실제 URL을 창작하지 말고 [팩트]의 공식 경로에 나온 기관만 써서 '기관명 + 검색어/메뉴 경로'로 안내(예: "정확한 최신 기준은
   정부24·복지로에서 '○○' 검색", "고용24 → ○○ 신청 메뉴"). 막연한 '공식 사이트로 확인하세요'가 아니라 검색어·메뉴까지 찍을 것.
6. ★문장 리듬(노매새드): 1문장=1문단이 기본(한 문단 최대 2문장·2~3줄 이내), 한 문장 평균 40자 내외(최대 70자). '~합니다' 존댓말 기본에 '~요/~죠'를 섞고, 4~5문장마다 짧은 존댓말 단정문(예: '핵심은 소득 기준이죠.')으로 리듬을 끊어라 — 반말 종결은 한 문장도 금지
7. 순수 정보형 기조(감탄·이모지·잡담 금지). 단 서론 훅과 '저라면 ~' 판단 문장 등 지정된 위치의 1인칭은 허용
7-1. ★'저라면 ~' 개인 판단 문장을 글 전체에 2~3회 넣어라(예: '저라면 소급 지급 기한부터 확인하겠습니다.'). 서로 다른 섹션에 배치, FAQ·표 안 금지
8. 소제목은 결론/수치 포함 ("신청 방법" → "복지로에서 10분이면 끝")
9. ★소제목 번호(노매새드): 본문 소제목 5개는 반드시 '01 '~'05 '(두 자리 숫자+공백, 점 없음)로 시작 — 위 구조의 번호 그대로. '1.'처럼 점 붙은 번호·①번호는 금지(에디터 오토포맷 오작동). FAQ 소제목('자주 묻는 질문')에는 번호 금지. 01~05 중 3개 이상은 '~까?/~나요?' 질문형 유지
10. 금지: 안녕하세요/이처럼/이로써/혁신적인/탁월한/극대화/마크다운(**__#)/이모지(❓ 용어 줄만 예외)
11. 조건 나열 시 반드시 · (가운뎃점) 사용, 대시(-) 금지
12. 신청 단계 번호는 ①②③ 기호 사용 — "1. 2. 3." 숫자+점 형식 금지 (소제목 번호와 혼동)
13. 소제목은 반드시 [소제목] 마커로만 표시 — 마커 없이 "02 신혼부부 전용..." 같이 시작하는 줄 완전 금지
14. ★2단 계층 리스트: 상위 분류는 [[분류명]] 볼드 라벨(글머리 · 없이 한 줄), 세부 항목만 그 아래 · 불릿. 부모·자식이 같은 · 글머리를 쓰면 레벨 혼동 — 금지. '여러 대상 × 여러 값'도 표 승격 금지(표 2개 고정) — 대표 사례는 03 계산표에서 다뤄라.

══════════════════════════════════════════
[출력 형식 — 반드시 정확히]
══════════════════════════════════════════
TITLE: {제목 — 금액·수치 포함, 35자 이내. ★후킹 강화(대형 블로그 벤치마킹): 결론 약속·궁금증 유발·리스트('N가지 조건')·구체 이득 중 하나를 자연스럽게. 과장·허위·낚시 금지}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6},{태그7}
IMAGE_KEYWORDS: gov header
IMAGE_LABELS: {키워드 한글}
---
{본문}

★★★ 마커 체크리스트 — 출력 전 반드시 확인 ★★★
- [사진1] 1개만 (맨 위 헤더). ★[사진2]·[사진3] 등 본문 사진 마커는 절대 넣지 마라 (정부지원 글은 헤더카드 외 사진 없이 정보만)
- [요약시작] ~ [요약끝] 정확히 1쌍 존재하는가 (서론 바로 뒤)
- [표시작] ~ [표끝] 정확히 2쌍 존재하는가 (①01 섹션 2열 요약표 ②03 섹션 3열 계산표, 빈칸 없음)
- [소제목] 마커 6개 — 본문 5개는 '01 '~'05 ' 시작(3개 이상 질문형), FAQ('자주 묻는 질문')는 번호 없음
- [FAQ시작] ~ [FAQ끝] 정확히 1쌍 존재하는가
- 서론: 훅 1문장 + '결론부터 말하면 ~입니다. 다만 ~' + 끝 문장 '~정리해보겠습니다.'
- 마무리: '결국 ~' 결론 + 핵심 숫자 재강조 + 오늘 할 일 + '단계1 → 단계2 → 단계3' 확인 체인
- '저라면' 2회 이상, '❓ 용어: 한 줄 정의' 단독 줄 1개 이상
"""

_GOV_REFINE_SYSTEM = """\
너는 정부지원 블로그 퇴고 전문가야. 초안을 받아서 형식은 그대로 두고 내용만 다듬어라.

[절대 그대로 유지 — 건드리면 블로그 삽입이 깨진다]
- TITLE: / TAGS: / IMAGE_KEYWORDS: / IMAGE_LABELS: 줄 전체
- --- 구분선
- [사진1] 마커 (1개만, 위치 변경 금지. 사진 마커 추가 금지)
- [요약시작]...[요약끝] (1쌍, 삭제·이동 금지)
- [소제목] 마커 (6개, 위치 변경 금지 — 본문 5개의 '01 '~'05 ' 번호와 질문형 유지, FAQ는 번호 없음)
- [표시작]...[표끝] (2쌍 — 요약표 2열·계산표 3열, 삭제·추가·열변경 금지)
- [FAQ시작]...[FAQ끝] (1쌍, 삭제 금지)
- 서론 구조(훅 1문장·'결론부터 말하면 ~입니다. 다만 ~'·끝 문장 '~정리해보겠습니다.', 5~7문장·250자 이내)
- 마무리 구조('결국 ~' 결론·핵심 숫자 재강조·오늘 할 일·'단계1 → 단계2 → 단계3' 확인 체인)
- '저라면 ~' 문장(2회 이상)과 '❓ 용어: 한 줄 정의' 단독 줄

[고쳐야 할 것]
1. AI 단어(이로써/이처럼/혁신적인/탁월한/극대화) → 자연스러운 표현
2. 표 항목이 "~" 플레이스홀더면 → 실제 2026년 기준 수치로 채워라
3. FAQ 답변이 1줄로 너무 짧으면 → 2~3줄로 구체적으로 보완
4. 단락이 4줄 이상이면 → 1~2문장 단위로 끊어라(1문장=1문단 기본)
5. 마무리에 공식 확인 권장 문구 없으면 → 핵심 숫자 재강조 문장에 자연스럽게 추가
6. 소제목이 "05 신청 방법" 같이 밋밋하면 → "05 신청 방법 — 복지로에서 10분이면 끝" 처럼 결론 포함으로 수정(번호는 유지)
7. ★반말 종결 문장("~했다./~이다./~있다./~된다." 등)이 있으면 전부 존댓말(~요/~습니다)로 교정하라(단, 따옴표 안 인용문은 제외)

출력: 고친 전체 글(형식 포함). 설명 없이 바로 출력.
"""


# prose 기준 최소 길이 — Gemini가 1600~1900자 생성하는 경우가 많아 1500으로 하향
GOV_BODY_MIN = 1500
_GOV_CALC_SIGNAL_RE = re.compile(
    r"[×x*]\s*\d|=\s*[\d,]+\s*(원|만원|%)"
    r"|\d[\d,]*\s*원\s*[×x]"
    r"|예[)）:]\s*.*\d"
    r"|\d[\d,]*만\s*원"
    r"|약\s*[\d,]+만"
    r"|최대\s*[\d,]+만"
)


def generate_gov_post(
    keyword: str,
    api_key: str,
    gov_category: str = "",
) -> dict | None:
    """
    정부지원·혜택 포스트 생성 (패턴 F 정보형).
    반환: {title, tags, body, image_keywords, image_labels, subheadings, table_str, faq_str, faq_pairs}
    """
    # 팩트 블록: Naver 뉴스 + 공식 출처 경로
    try:
        from generator.info_collector import collect_info_facts
        from generator.source_refs import GOV_OFFICIAL_SOURCES, format_sources_block
        fact_block = collect_info_facts("gov", keyword)
        fact_block += format_sources_block(GOV_OFFICIAL_SOURCES)
    except Exception as e:
        logger.warning(f"정부 팩트 수집 스킵: {e}")
        fact_block = ""

    # 검증 수치 주입(2026-07-14): 정밀점검-재발행 시 관리자가 공식 확인한 수치를 최우선 팩트로.
    # 긴급복지 사례 — 뉴스·그라운딩에 정책 '단가'가 없으면 표의 수치 필수 규칙이 창작을 유도함.
    forced_facts = os.environ.get("FORCE_FACTS", "").strip()
    if forced_facts:
        logger.info(f"검증 수치 주입(FORCE_FACTS {len(forced_facts)}자)")
        fact_block = ("[검증된 공식 수치 — 금액·기준은 반드시 아래 값만 사용, 그 외 수치 창작 절대 금지]\n"
                      + forced_facts + "\n\n") + fact_block

    # 법정 고시값 상시 주입(2026-07-19, 오류 원천 차단) — gov 글은 중위소득·급여 기준 오류가
    # 반복된 최다 발생 지점이라 검증 DB 값을 항상 팩트 최상단에 둔다.
    try:
        from generator.official_facts import lookup_block
        _official = lookup_block(keyword, "정부지원 " + (gov_category or ""))
        if _official:
            fact_block = _official + fact_block
    except Exception as e:
        logger.warning(f"고시값 DB 스킵: {e}")

    # 서론 훅 로테이션(노매새드 벤치마킹, 2026-07-28) — 직전 발행과 다른 훅 유형 강제
    hook_id, hook_spec = pick_intro_hook("gov")
    logger.info(f"서론 훅 유형: {hook_id} (gov)")
    user_msg = fact_block + (
        f"정부지원·혜택 키워드: {keyword}"
        + (f"\n카테고리 힌트: {gov_category}" if gov_category else "")
        + "\n\n위 키워드로 모바일 독자가 5분 안에 핵심을 파악할 수 있는 정부지원 정리 글을 작성해라."
        + "\n- ★[이번 글 서론 훅 유형] " + hook_spec
        + "\n- ★서론: 5~7문장(1문장=1문단)·250자 이내, 4문장 안에 '결론부터 말하면 ~입니다. 다만 ~', 끝 문장 '~정리해보겠습니다.'"
        + "\n- 표 정확히 2개: ①01 섹션 2열 요약표(구분|내용, 구분 8자·내용 20자 이내) ②03 섹션 3열 계산표(구분|계산|결과, 셀 12자 이내) — [표시작]...[표끝] 2쌍, 빈칸 금지. 자격·주의사항은 표 대신 · 불릿."
        + "\n- FAQ 정확히 1개: [FAQ시작]...[FAQ끝] 마커 1쌍 필수."
        + "\n- ★소제목 6개: 본문 5개는 '01 '~'05 ' 번호 시작(3개 이상 질문형), FAQ('자주 묻는 질문')는 번호 없음."
        + "\n- ★본문 2,200~2,800자. 1문장=1문단 기본(한 문단 최대 2문장). 03 계산표의 시나리오 계산 서술 포함."
        + "\n- ★요약표 아래 '출처: (공식 기관)' 1줄 필수."
        + "\n- ★핵심 전문용어 첫 등장 바로 다음 줄에 '❓ 용어: 한 줄 정의' 단독 줄(1~2개), '저라면 ~' 판단 문장 2~3회."
        + "\n- ★마무리: '결국 ~' 결론 → 핵심 숫자 재강조 → 오늘 할 일 1문장 → '단계1 → 단계2 → 단계3' 확인 체인 한 줄."
        + "\n- 제목에 반드시 구체적 금액·수치 포함."
        + "\n- 이미지는 [사진1](맨 위 헤더카드) 1개만. 본문 스톡사진([사진2]+)은 넣지 마라 — 정부지원 글은 헤더 외 사진 없이 정보만 전달."
    )

    waits = [15, 40, 90]
    feedback = ""  # 노매새드 구조 위반 재생성 피드백(직전 실패 사유 되먹임, 2026-07-28)
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg + feedback, _GOV_SYSTEM, 8192, 0.8)
            if not raw:
                logger.error(f"정부글 Gemini 빈 응답 (시도 {attempt})")
                continue

            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"정부글 파싱 실패 (시도 {attempt})")
                continue

            body = parsed.get("body", "")
            body_len = len(_IMAGE_MARKER.sub("", body))
            if body_len < GOV_BODY_MIN:
                logger.warning(
                    f"정부글 본문 너무 짧음 ({body_len}자, 최소 {GOV_BODY_MIN}자) — 재생성"
                )
                continue
            # 계산 신호는 모든 표(요약표+계산표) 합산 검사(2026-07-28 표 2개 체제)
            calc_src = body + "\n" + "\n".join(parsed.get("table_strs") or [])
            if not _GOV_CALC_SIGNAL_RE.search(calc_src):
                logger.warning("정부글 계산 예시 없음 — 재생성")
                continue
            if "출처" not in body:
                logger.warning("정부글 출처 표기 없음 — 재생성")
                continue
            # ★노매새드 4종 구조 게이트(2026-07-28): 소제목 01~05·질문형 3+·표 2개·서론 훅 구조·
            # '저라면'·결론 체인·❓용어 줄 — 위반 항목을 피드백으로 되먹여 재생성
            nomad_issues = find_nomad_structure_issues(
                parsed.get("subheadings", []), body, len(parsed.get("table_strs") or []))
            if nomad_issues:
                feedback = ("\n\n⚠️직전 초안이 구조 스펙을 어겼다. 아래 항목을 전부 고쳐 전체 글을 다시 출력하라:\n- "
                            + "\n- ".join(nomad_issues))
                logger.warning(f"정부글 노매새드 구조 위반 {len(nomad_issues)}건({nomad_issues[0]!r} 등) — 재생성")
                continue
            # ★반말 종결 게이트(존댓말 강제, 2026-07-27) — 1문장이라도 있으면 재생성
            banmal = banmal_gate(body, parsed.get("faq_str", ""), parsed.get("summary_text", ""))
            if banmal:
                logger.warning(f"정부글 반말 종결 {len(banmal)}건({banmal[0]!r} 등) — 재생성")
                continue

            logger.info(
                f"정부글 생성 완료: {parsed.get('title')!r} "
                f"(본문 {body_len}자, 표 {len(parsed.get('table_strs') or [])}개, FAQ={bool(parsed.get('faq_str'))}, 요약={bool(parsed.get('summary_text'))}, 훅={hook_id})"
            )
            parsed["intro_hook"] = hook_id
            record_intro_hook("gov", hook_id)  # 성공 시에만 기록(다음 회차 로테이션 기준)

            # 퇴고 패스 — 실패해도 원본 반환 (퇴고 503이 글 생성 실패로 오인되지 않도록)
            try:
                refined_raw = _gen_text(
                    api_key,
                    f"아래 정부지원 블로그 초안을 퇴고해줘:\n\n{raw}",
                    _GOV_REFINE_SYSTEM, 8192, 0.75,
                )
                if refined_raw:
                    refined = _parse_response(refined_raw)
                    if (refined and len(_IMAGE_MARKER.sub("", refined.get("body", ""))) >= GOV_BODY_MIN
                            and not find_nomad_structure_issues(
                                refined.get("subheadings", []), refined.get("body", ""),
                                len(refined.get("table_strs") or []))
                            and not banmal_gate(refined.get("body", ""), refined.get("faq_str", ""),
                                                refined.get("summary_text", ""))):
                        rb_len = len(_IMAGE_MARKER.sub("", refined.get("body", "")))
                        logger.info(f"정부글 퇴고 적용: {body_len}→{rb_len}자")
                        refined["intro_hook"] = hook_id
                        return refined
            except Exception as refine_err:
                logger.warning(f"정부글 퇴고 실패 — 원본 사용: {refine_err}")

            return parsed

        except Exception as e:
            logger.error(f"정부글 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)

    return None


def extract_summary_bullets(summary_text: str, max_count: int = 4) -> list[str]:
    """summary_text에서 불릿 항목 추출 (인포그래픽 헤더 카드용).
    LLM이 ✔/· 등 다양한 마커로 출력하므로 모두 처리. prefix가 없는 일반 줄은 수집하지 않음(오탐 방지).
    gov/info 등 [요약시작]...[요약끝] 블록을 쓰는 카테고리 스크립트가 공용으로 사용."""
    PREFIXES = ("✔ ", "✔", "· ", "• ", "- ", "* ", "✓ ", "√ ", "▶ ", "> ")
    bullets = []
    for line in summary_text.splitlines():
        line = line.strip()
        matched = False
        for prefix in PREFIXES:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
                matched = True
                break
        if not matched:
            continue
        # 괄호 부연설명은 카드가 좁아 잘려 보이므로 제거하되, 괄호 앞 본문은 살린다
        line = re.sub(r"\s*\([^)]*\)\s*", " ", line).strip()
        if 5 <= len(line) <= 35:
            bullets.append(line)
        if len(bullets) >= max_count:
            break
    return bullets
