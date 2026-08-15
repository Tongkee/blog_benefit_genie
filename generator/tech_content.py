"""
형수의테크공장 — IT/테크 뉴스 자동 포스트 생성 (프로토타입).

핵심 설계:
  · 뉴스 = 트래픽 엔진 → Naver 뉴스 검색 API로 최근 N일 기사만 팩트로 사용(pubDate 필터)
  · 글 형식 4종 로테이션 → 매 발행 형식 순환(지루함 방지 + 깔때기 단계별 독자)
  · 출력 포맷은 gov/health와 동일 → generator.content._parse_response 그대로 재사용
  · 이미지: 판매제품=쇼핑API 실사진 / 루머=인포그래픽 (본 모듈은 마커만 배치, poster가 처리)

형식(fmt):
  breaking  ① 속보·루머   — 홈피드 유입 (이미지=인포그래픽)
  explain   ② 쉬운 해설   — 검색·신뢰   (이미지=AI 일러스트/개념도)
  pick      ③ 꿀템 큐레이터 — 쇼핑커넥트 전환 (이미지=쇼핑API 실사진)
  compare   ④ 비교·논란   — 체류시간   (이미지=인포그래픽+쇼핑API)
"""
import logging
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER
from generator.info_collector import _fetch_naver_news
from generator.quality import banmal_gate

logger = logging.getLogger("tech_content")

KST = timezone(timedelta(hours=9))
TECH_BODY_MIN = 1300  # 하한은 안전망, 목표 길이(1700~2400)는 프롬프트로 유도

# 종합 테크 시드 — ★구체적 소비자 '제품/모델'로 한정(추상 키워드는 산업·이벤트 뉴스를 물어와 트래픽 저조).
# 실제 글감은 시드로 최신 뉴스를 조회해 그 헤드라인/맥락에서 결정(뉴스 주도 = 항상 신선).
TECH_SEEDS = [
    # 스마트폰 (구체 모델)
    "아이폰 18", "갤럭시 S26", "갤럭시 Z 폴드", "갤럭시 Z 플립", "아이폰 에어",
    "픽셀 스마트폰", "갤럭시 AI",
    # 웨어러블·오디오
    "갤럭시 워치", "애플워치", "에어팟", "갤럭시 버즈", "무선이어폰 신제품",
    # PC·부품
    "게이밍 노트북", "RTX 그래픽카드", "맥북", "게이밍 모니터",
    # 가전·디지털
    "로봇청소기", "에어프라이어", "삼성 TV 신제품", "무선청소기", "공기청정기", "제습기",
    # 자동차 (소비자 관심 신차/전기차)
    "아이오닉", "기아 EV", "테슬라 모델", "전기차 신차 출시",
    # AI 소비자 서비스 (카테고리별 하루 1편 전환으로 AI·IT 시드 보강, 2026-07-17)
    "챗GPT 신기능", "AI 스마트폰", "제미나이", "AI 노트북",

    # 롱테일 축(2026-07-31) — 플래그십 이벤트에 수렴하지 않는 상시 검색 수요
    "보조배터리 추천",
    "USB-C 충전기",
    "스마트태그 위치추적",
    "폰 케이스 신제품",
    "스마트워치 밴드",
    "모니터암 추천",
    "기계식 키보드 신제품",
    "NAS 홈서버",
    "와이파이 공유기",
    "게이밍 헤드셋",
    "외장 SSD",
    "식기세척기 추천",
    "전동칫솔 신제품",
    "블루투스 스피커",
    "인덕션 신제품",
    "의류건조기",
    "정수기 렌탈",
    "커피머신 신제품",
    "전기차 충전기 설치",
    "블랙박스 신제품",
    "차량용 무선충전기",
    "전기자전거 추천",
    "AI 이미지 생성 서비스",
    "클라우드 저장공간 비교",
    "화상회의 앱",
    "비밀번호 관리 앱",
]

# 시드 → 블로그 카테고리 매핑 (hyungsutech에 생성된 주제별 카테고리로 자동 분류)
SEED_CATEGORY = {
    "아이폰 18": "스마트폰·모바일", "갤럭시 S26": "스마트폰·모바일", "갤럭시 Z 폴드": "스마트폰·모바일",
    "갤럭시 Z 플립": "스마트폰·모바일", "아이폰 에어": "스마트폰·모바일", "픽셀 스마트폰": "스마트폰·모바일",
    "갤럭시 AI": "스마트폰·모바일", "갤럭시 워치": "스마트폰·모바일", "애플워치": "스마트폰·모바일",
    "에어팟": "스마트폰·모바일", "갤럭시 버즈": "스마트폰·모바일", "무선이어폰 신제품": "스마트폰·모바일",
    "게이밍 노트북": "PC·노트북", "RTX 그래픽카드": "PC·노트북", "맥북": "PC·노트북", "게이밍 모니터": "PC·노트북",
    "로봇청소기": "가전·디지털", "에어프라이어": "가전·디지털", "삼성 TV 신제품": "가전·디지털",
    "무선청소기": "가전·디지털", "공기청정기": "가전·디지털", "제습기": "가전·디지털",
    "아이오닉": "자동차·모빌리티", "기아 EV": "자동차·모빌리티", "테슬라 모델": "자동차·모빌리티",
    "전기차 신차 출시": "자동차·모빌리티",
    "챗GPT 신기능": "AI·IT", "AI 스마트폰": "AI·IT", "제미나이": "AI·IT", "AI 노트북": "AI·IT",
    # 롱테일 축(2026-07-31)
    "보조배터리 추천": "스마트폰·모바일", "USB-C 충전기": "스마트폰·모바일", "스마트태그 위치추적": "스마트폰·모바일", "폰 케이스 신제품": "스마트폰·모바일", "스마트워치 밴드": "스마트폰·모바일",
    "모니터암 추천": "PC·노트북", "기계식 키보드 신제품": "PC·노트북", "NAS 홈서버": "PC·노트북", "와이파이 공유기": "PC·노트북", "게이밍 헤드셋": "PC·노트북", "외장 SSD": "PC·노트북",
    "식기세척기 추천": "가전·디지털", "전동칫솔 신제품": "가전·디지털", "블루투스 스피커": "가전·디지털", "인덕션 신제품": "가전·디지털", "의류건조기": "가전·디지털", "정수기 렌탈": "가전·디지털", "커피머신 신제품": "가전·디지털",
    "전기차 충전기 설치": "자동차·모빌리티", "블랙박스 신제품": "자동차·모빌리티", "차량용 무선충전기": "자동차·모빌리티", "전기자전거 추천": "자동차·모빌리티",
    "AI 이미지 생성 서비스": "AI·IT", "클라우드 저장공간 비교": "AI·IT", "화상회의 앱": "AI·IT", "비밀번호 관리 앱": "AI·IT",
}


def category_for_seed(seed: str) -> str:
    return SEED_CATEGORY.get(seed, "스마트폰·모바일")


# 형식별 이미지 전략(라벨용) — poster 연동은 다음 단계. 지금은 헤더 [사진1]만 사용.
FMT_IMAGE = {
    "breaking": "infographic",
    "explain": "illustration",
    "pick": "shopping",
    "compare": "infographic",
    "top5": "shopping",
}

_COMMON_RULES = """\
너는 '형수의테크공장' 블로그 작가 '형수'다. 어려운 최신 테크 소식을 누구나 5분 안에
이해하도록 쉽고 정확하게 풀어준다. 친근하지만 팩트에 엄격하다.

[글쓰기 태도 — ★재미없으면 실패다. 정보 나열은 아무도 안 읽는다]
· 독자 관점이 먼저다. 이 소식에서 독자가 '진짜 궁금해할 것'과 '나한테 무슨 이득·손해인지'를
  중심으로 써라. 스펙·수치를 나열만 하지 말고 "그래서 이게 왜 좋은지/아쉬운지/나한테 뭔지"를
  꼭 해석해줘라.
· 도입부(리드)는 뻔한 배경설명 금지. 궁금증·의외성·손해회피("이거 모르면 손해") 중 하나로
  첫 두 줄에서 확 잡아라.
· ★문체를 섞어라 — 단, 어떤 문장이든 종결은 반드시 존댓말이다. '~습니다'로 끝나는 문장을
  3연속 이상 쓰지 말고, 짧은 단정·질문·대비를 섞어 리듬을 만들어라. 짧은 단정문도 반드시
  존댓말 종결(예: "가격이 문제죠." O / "가격이 문제다." X), 질문("그럼 지금 사도 될까요?"),
  대비("싸 보이지만, 함정이 있습니다"). 문장을 짧게 끊더라도 반말 평서형(~다./~이다.)으로
  이탈하는 순간 실패다 — 리듬은 '~요/~죠/~습니다/~인데요' 안에서만 만들어라.
· 구체 장면·비유로 와닿게. 추상적 설명 대신 실제 사용 상황·숫자·비교로.
· 과장·낚시는 금지하되, 밋밋함도 금지. 팩트 위에서 흥미를 얹어라.

[절대 원칙]
0. ★독자에게 '존댓말(~습니다/~해요)'로 쓴다. 반말(~이야/~했어/~보여) 금지. 그리고 '현지언니'
   등 다른 블로그·사람·계정을 본문에 절대 언급하지 마라(이 블로그 독자는 모른다).
1. 아래 [최신 뉴스] 팩트에 있는 사실만 단정. 없는 스펙·가격·일정은 지어내지 마라.
2. 확정 안 된 소식은 반드시 "~로 알려졌다 / ~로 전망된다 / 유출됐다" 톤. 단정 금지.
3. 낡은 정보 금지 — 뉴스 날짜 기준 최신만. ★기준일 표기 문구("2026년 7월 기준" 등)는 쓰지 마라 — 불릿 끝에 잔재로 남아 글을 어색하게 만든다(2026-07-16 사용자 피드백).
4. 금지어: 안녕하세요/이처럼/이로써/혁신적인/탁월한/극대화/것이 중요합니다/하는 게 좋습니다/마크다운(**#)/이모지. ★HTML 태그(<div>,<b>,<span>,<br> 등) 절대 쓰지 마라 — 소제목은 반드시 [소제목] 마커만 사용.
5. 소제목 텍스트 맨 앞에 번호(1./①) 붙이지 마라 — 회색바+볼드로 구분됨.
6. 목록/장점/대상 나열의 모든 항목 줄은 반드시 '· '(가운뎃점+공백)로 시작. '라벨: 설명' 형태여도 앞에 · 필수. 단계 번호는 ①②③.
7. 단락은 2~3줄 이내. 한 문장 = 한 줄 지향(모바일 스캔형).
8. 2단 계층: 상위 분류는 [[분류명]] 볼드 라벨(글머리 · 없이 한 줄), 세부만 그 아래 · 불릿. 부모·자식 같은 글머리 금지.
9. ★초점 엄수: 오직 주어진 주제와 '직접' 관련된 사실만 써라. 무관한 다른 제품·행사·지역·기업 소식은 절대 섞지 마라(초점 흐려짐).
9-1. ★소제목 중 최소 2개에는 주제의 제품·기술명을 그대로 넣어라 — 소제목만 훑어도 무슨 글인지
   보여야 한다("쉽게 말하면 이런 겁니다"처럼 주제 없는 소제목만 나열 금지, 2026-07-16 사용자 피드백).
10. ★표 규칙: 각 셀은 짧게(20자 이내). 한 셀 안에 여러 줄·여러 불릿(·) 절대 금지 — 항목이 많으면 셀에 몰아넣지 말고 행을 나눠라. (예: 칩셋/RAM/배터리/가격을 각각 다른 행으로. 한 셀에 스펙 5개 나열 금지)
11. ★음영 강조: 콘텐츠 소제목 섹션마다 독자가 꼭 기억해야 할 핵심 문장 1개를 골라, 그 문장을
   별도 줄로 분리한 뒤 문장 전체를 {{...}}로 감싸 '단독줄'로 써라(글 전체 3~5곳). 발행 시
   형광펜 음영으로 변환된다. 반드시 줄 전체가 {{로 시작해 }}로 끝나야 한다 — 문장 중간 일부만
   감싸면 효과 없다. 여러 줄을 하나의 {{}}로 묶지 마라. ★일반 본문 문단에만 사용 —
   표·FAQ·'핵심 요약 3줄'·총평·불릿(·) 줄 안에는 절대 금지.
12. ★소제목은 목차식 요약이 아니라 '다음 문단을 안 읽고는 못 배기게' 만드는 문장형 카피로.
   (예: "스펙·일정 정리" ✗ → "발표 하나로 판이 바뀐 이유" ✓ / "장단점 분석" ✗ → "3개월 써보면
   보이는 진짜 단점" ✓). 단, 규칙 9-1(제품·기술명 포함 최소 2개)은 유지하고,
   근거 없는 단정·공포("끝났다", "사면 망한다")는 금지.

[출력 형식 — 반드시 정확히]
TITLE: {후킹 제목 35자 이내 — '결과+진짜 이유'형("~된 진짜 이유"), 손해회피형("모르면 손해"), 수치 약속형 중 하나. 뉴스 팩트가 받쳐주는 선에서 최대한 세게 — 단 근거 없는 단정 예언·공포 조장·거짓 과장 금지}
TAGS: {태그1},{태그2},{태그3},{태그4},{태그5},{태그6}
IMAGE_KEYWORDS: tech header
IMAGE_LABELS: {키워드 한글}
---
{본문 — 아래 구조 그대로}
"""

# ── 형식별 구조 — 현지언니 정보성 포맷(✔요약박스·FAQ) 탈피, 테크 블로그 네이티브 구조 ──
# [사진1] = 발행 스크립트가 뉴스 실사진(og:image)을 자동 삽입하는 홈판 대표 썸네일 자리.
#           카드형 인포그래픽 아님 → 도입부에서 이미지를 설명하려 들지 마라(사진은 그냥 얹힌다).
# 벤치마크(테크티노)식 공통 뼈대 — 대화체 훅 → 핵심요약 → 질문형 소제목(데이터·1인칭 해석) →
# 마무리 한마디 → 참여 유도 질문. 형식별로 소제목의 '각도'만 다르게.
_BENCH_OPEN = """[사진1]
(도입 2~3문단. ★대화체·실생활 훅으로 시작하라 — 예: "얼마 전 회사 동료와 ~ 얘기를 하다가 '정말 그럴까?' 싶어 찾아봤습니다." 처럼 독자가 '어 나도 궁금했는데' 하게. 그리고 이 글에서 무엇을 알게 될지 살짝 예고. 뻔한 배경설명·사전적 정의로 시작하지 마라.)

[소제목] 핵심 요약 3줄
· (이 글의 결론/핵심 숫자 1 — 구체 수치로)
· (핵심 2)
· (핵심 3)
(★이 소제목 문구는 '핵심 요약 3줄' 그대로 고정 — 제품명으로 바꾸지 마라. 발행 시 포스트잇 박스로
변환된다. 제품·기술명은 아래 다른 소제목들에 넣어라.)
"""
# ※목차 섹션은 제거(2026-07-16 사용자 피드백: 소제목 3~4개짜리 글에 목차는 군더더기)
_BENCH_CLOSE = """
[소제목] 알고 보면 더 재밌는 뒷이야기
(이 주제에 얽힌 흥미로운 맥락 1가지 — 이전 세대의 흑역사, 업계 경쟁 구도의 아이러니, 개발 비화,
소비자들 사이의 밈 등. 3~5줄, 가볍고 대화체로. ★[최신 뉴스]나 검색으로 확인되는 사실만 —
확인 안 되는 일화를 지어내지 마라. 마땅한 비화가 없으면 '이전 세대·경쟁 제품과 얽힌 역사'로
대체하라. 소제목 문구는 상황에 맞게 바꿔도 된다(예: "○○의 흑역사, 기억하시나요"). 체류시간을
만드는 섹션이다 — 여기서 재미없으면 독자가 나간다.)

[소제목] 총평
(전체를 아우르는 정리 2~3줄. 핵심을 다시 짚되 '그래서 독자는 어떻게 하면 되는지' 개인 인사이트 한 스푼. 앞 내용 단순 반복 금지.)

(마무리 한마디: 기억에 남는 한 줄로 여운을 줘라. 예: "좋은 폰은 스펙이 만들지만, 오래 쓰는 폰은 결국 관리가 만듭니다." 진부한 요약 금지.)

(★참여 유도 질문 1줄: 독자에게 의견을 물어 댓글을 유도하라. 예: "여러분이라면 성능을 먼저 보시나요, 가격을 먼저 보시나요?")
"""

_FMT_PROMPTS = {
    # ① 뉴스 팩트체크·판정형 — 2026-07-29 벤치마킹: 상위 블로그는 순수 속보가 없고
    # 뉴스를 '팩트체크 표 + 살까말까 판정' 구매행동 프레임으로 변환(소멸형→체류형).
    "breaking": _COMMON_RULES + "\n[구조 — 뉴스 팩트체크·판정형]\n" + _BENCH_OPEN + """
(★도입 마지막 문장은 "결론부터 말씀드리면, ~입니다" 요약 판정 1문장.)

[소제목] 한눈에 보는 팩트 체크
(유출·발표 내용을 표로 정리 — ★3열(항목|알려진 내용|신뢰도·한줄평), 각 셀 12자 이내,
빈칸 금지. '신뢰도' 열엔 확정/유력/루머 구분과 짧은 평. 출처 성격을 표 아래 1줄로.)
[표시작]
항목 | 알려진 내용 | 신뢰도·한줄평
칩셋 | ~ | ~
출시 예상 | ~ | ~
[표끝]

[소제목] 지금 알려진 것 vs 지켜볼 것
(확정 팩트와 미확정 루머를 분리해 서술. 이전 세대·경쟁 제품 대비 뭐가 달라지는지.)

[소제목] 그래서 기다릴까, 지금 살까
(독자 상황별 판정 — "~라면 기다리세요, ~라면 지금 사도 됩니다" 조건부 결론 · 불릿.
"제가 보기엔~" 1인칭 관점 한 스푼.)
""" + _BENCH_CLOSE,
    # ② 쉬운 해설 — 해설형(비유·개념).
    "explain": _COMMON_RULES + "\n[구조 — 쉬운 해설형]\n" + _BENCH_OPEN + """
[소제목] 이게 왜 어렵게 느껴질까
(독자가 헷갈리는 지점을 콕 집고, 핵심 개념을 결론부터 한 줄로.)

[소제목] 쉽게 말하면 이런 겁니다
(어려운 원리를 일상 비유로. 구체 장면으로 와닿게 3~4줄.)

[소제목] 그래서 나한테 좋은 건
(체감 변화·장점을 · 불릿으로. 각 항목에 구체 수치·예시와 '왜 좋은지' 해석.)
""" + _BENCH_CLOSE,
    # ③ 꿀템 큐레이터 — 리뷰/스펙형.
    "pick": _COMMON_RULES + "\n[구조 — 리뷰/스펙형]\n" + _BENCH_OPEN + """
[소제목] 어떤 제품이길래
(제품 성격·핵심 특징을 실제 스펙과 함께. '어떤 사람의 어떤 고민'을 풀어주는지 관점으로.)

[소제목] 스펙·가격 한눈에
(★반드시 3열(항목|스펙|한줄평), 각 셀 20자 이내, 빈칸 금지. '한줄평' 열엔 그 스펙이 좋은지/아쉬운지 짧게. 항목마다 행을 나눠라 — 한 셀에 여러 스펙 몰아넣기 금지.
★스펙 최소 기준(2026-07-19, 제습기 할인 글 실사고): 모델명·가격·판매처 같은 메타 정보만으로
표를 채우지 마라. 뉴스에 실스펙이 없으면 검색으로 제조사 공식 스펙을 확보해 제품 성능 스펙
(용량·소비전력·소음·크기·기능 등) 행을 최소 3개 이상 넣어라. 같은 스펙 수식어를 본문에서
3회 이상 반복 금지("22L 넉넉" 반복 같은 물타기). 스펙 확보가 불가능한 소재면 억지로 리뷰
흉내 내지 말 것.)
[표시작]
항목 | 스펙 | 한줄평
칩셋 | ~ | ~
RAM·저장 | ~ | ~
배터리 | ~ | ~
가격 | ~ | ~
[표끝]
(가격·스펙은 판매처 기준, 변동 가능 — 1줄)

[소제목] 좋은 점 vs 아쉬운 점
(· 불릿으로 장점과 단점을 솔직하게 균형 있게. 단점도 진짜로. 광고티 금지.)

[소제목] 이런 분께 추천
(구매 적합 대상을 · 불릿으로. 3~4개.)

[쇼핑추천]
""" + _BENCH_CLOSE,
    # ④ 비교 판정형 — 2026-07-29 벤치마킹(sg90929) 강화: 결론 선제시+항목별 승자 판정.
    "compare": _COMMON_RULES + "\n[구조 — 1:1 비교 판정형]\n" + _BENCH_OPEN + """
(★도입 마지막 문장은 반드시 "결론부터 말씀드리면, ~는 A가, ~는 B가 앞섭니다" 식 요약 판정 1문장.)

[소제목] 뭐가 쟁점이길래
(비교 포인트·논란을 양쪽 입장 균형 있게. 독자가 왜 이걸 고민하는지 짚어줘라.)

[소제목] 항목별로 비교해보면
(비교가 핵심이니 표를 충실히 — 3열(항목|A|B), 4~5개 행, 각 셀 15자 이내, 빈칸 금지.
★표 아래에 항목별 승자 판정을 문장으로 2~3줄 — "무게는 A, 화면은 B" 식으로 명시하고,
가격 차이는 '딱 ○○만 ○천 원' 수준의 정확 수치로.)
[표시작]
항목 | A | B
가격 | ~ | ~
성능 | ~ | ~
[표끝]

[소제목] 그래서 저는 이렇게 고르겠습니다
(사용자 프로필 2~3개로 조건부 결론 — "~하는 분이라면 A, ~가 우선이면 B". · 불릿.)
""" + _BENCH_CLOSE,
    # ⑤ TOP5 순위형 — 2026-07-29 벤치마킹(newkiller33): 소형 블로그도 상위노출 달성한 템플릿.
    "top5": _COMMON_RULES + "\n[구조 — TOP5 순위 추천형]\n" + _BENCH_OPEN + """
(주제 뉴스의 제품군으로 '용도별 추천 TOP5'를 구성하라. 현재 판매 중인 실제 모델만 —
검색 근거 없는 모델명·스펙 창작 금지. 제목에 'TOP 5'와 '2026년 ○월 기준'을 넣어라.)

[소제목] 고르기 전에 이것만 알면 됩니다
(핵심 선택 기준 3~4개를 각 1~2문장으로 교육 — 용어를 쉬운 말로.)

[소제목] 1위. (모델명) — "(포지셔닝 별명)"
(★각 순위 공식: "1위인 이유는 '~하다'는 거예요" 한 줄 논거 → 핵심 스펙 2~3개 →
'이런 분께' 1문장. 2~5위도 같은 공식으로 [소제목]을 각각 만들어라.)

[소제목] 상황별로 다시 정리하면
(예산·용도별 매칭을 · 불릿 3~4개로. "○○이 우선이면 N위 모델" 식.)

[쇼핑추천]
""" + _BENCH_CLOSE,
}


def _recent_tech_news(keyword: str, days: int = 7, display: int = 8) -> list[dict]:
    """Naver 뉴스에서 keyword 최근 기사 → pubDate로 days일 이내만 필터(낡은 자료 배제)."""
    raw = _fetch_naver_news(keyword, display=display)
    if not raw:
        return []
    cutoff = datetime.now(KST) - timedelta(days=days)
    fresh = []
    for n in raw:
        try:
            dt = parsedate_to_datetime(n.get("date", ""))
            if dt and dt.astimezone(KST) >= cutoff:
                fresh.append(n)
        except Exception:
            fresh.append(n)  # 날짜 파싱 실패 시 보존(하드 배제 안 함)
    logger.info(f"테크 뉴스 필터: {keyword!r} {len(raw)}건 → 최근 {days}일 {len(fresh)}건")
    return fresh


# 소비자 관심 신호 — 헤드라인에 있으면 가점(출시·가격·비교 등 트래픽 되는 소비자 제품 주제)
_CONSUMER_SIGNALS = (
    "출시", "출시일", "가격", "공개", "스펙", "신제품", "리뷰", "성능",
    "할인", "예약", "사전예약", "언박싱", "배터리", "카메라", "디스플레이",
    "업데이트", "탑재", "유출", "렌더링", "체험", "써보니", "직접", "후기",
)
# 트래픽 약한 뉴스 — 강한 감점. 학술/B2B/지역/행정 + 비즈니스/노조/증시/법률 노이즈까지 배제.
_NONCONSUMER_SIGNALS = (
    # 학술·B2B·지역·행정
    "대학", "연구진", "연구소", "논문", "학회", "포럼", "세미나", "컨퍼런스",
    "수상", "우승", "선정", "협약", "MOU", "산학", "특허", "장관", "지자체",
    "시장", "도지사", "군수", "구청", "박람회", "설명회", "간담회", "위원회",
    "채용", "공모전", "육성", "지원사업", "정책", "규제", "국회", "부처", "행사",
    # 비즈니스·노조·증시·법률 (소비자 무관)
    "파업", "노조", "노사", "실적", "주가", "매출", "영업이익", "증권", "투자",
    "리콜", "소송", "담합", "공정위", "인수", "합병", "CEO", "임원", "인사",
    "컨센서스", "목표주가", "배당", "지분", "적자", "흑자", "수출", "관세",
    # 기업 동정·B2B 보도자료 (2026-07-16 실측: 'SM벡셀 배터리팩솔루션팀 신설'이 '배터리' 가점으로
    # 통과 → 소비자 실익 없는 글. 조직·수주성 뉴스는 강한 감점)
    "신설", "출범", "조직", "본부", "사업부", "솔루션팀", "수주", "납품",
    "공급계약", "양산", "증설", "협력사", "자회사", "법인", "사옥", "공장",
    # 개발자·B2B 이벤트 (컨퍼런스/전시 = 트래픽 저조)
    "페스트", "세션", "개발자", "언리얼", "엔진", "간담회", "쇼케이스",
    "웨비나", "밋업", "해커톤", "SDK", "API", "오픈소스", "출품", "전시회",
)


def _score_headline(title: str) -> int:
    """헤드라인 소비자 관심도 점수. 소비자 신호 +, 학술/B2B/지역 신호 강한 -."""
    score = 0
    for kw in _CONSUMER_SIGNALS:
        if kw in title:
            score += 2
    for kw in _NONCONSUMER_SIGNALS:
        if kw in title:
            score -= 5
    return score


def _recency_bonus(date_str: str) -> int:
    """당일 이슈 가점(2026-07-17 벤치마킹): 검색 피크는 이슈 당일이 가장 크다.
    24h 이내 +6, 48h 이내 +3. 랭킹 전용 — 소비자 신호 없는 글의 스킵 판정은 kw 점수로만."""
    try:
        dt = parsedate_to_datetime(date_str).astimezone(KST)
        age_h = (datetime.now(KST) - dt).total_seconds() / 3600
        if age_h <= 24:
            return 6
        if age_h <= 48:
            return 3
    except Exception:
        pass
    return 0


def _realign_seed(seed: str, headline: str) -> str:
    """선정 헤드라인에 시드가 실제로 등장하는지 검증, 무관하면 헤드라인과 맞는 시드로 교체.

    네이버 뉴스 검색이 본문 매칭으로 시드와 딴 주제 기사를 반환할 수 있는데(2026-07-19 실측:
    시드 '테슬라 모델'에 갤럭시Z 폴드8 기사 선정), 시드는 카테고리 분류·쇼핑 사진 쿼리·
    사진-주제 게이트의 기준이라 어긋나면 갤럭시 글에 테슬라 모형차 사진이 붙는 사고가 남."""
    norm = re.sub(r"\s+", "", headline).lower()

    def hits(s: str) -> int:
        return sum(1 for t in re.split(r"\s+", s.lower()) if t and t in norm)

    if hits(seed) > 0:
        return seed
    best = max(TECH_SEEDS, key=hits)
    if hits(best) > 0:
        logger.info(f"시드 재정렬: [{seed}] → [{best}] (헤드라인에 원 시드 미등장)")
        return best
    return seed


def pick_tech_topic(days: int = 7, exclude: set | None = None,
                    exclude_headlines: set | None = None,
                    seeds: list | None = None) -> dict | None:
    """여러 시드의 최신 뉴스를 모아 '소비자 관심도' 최고 헤드라인을 글감으로 선정.
    학술/B2B/지역 뉴스는 감점으로 배제 → 트래픽 되는 소비자 주제로 편향.
    exclude_headlines: 최근 발행 헤드라인 — 후보에서 원천 제외(같은 글감 반복 발행 방지, 2026-07-16).
    seeds: 시드 부분집합(카테고리별 하루 1편 발행용, 2026-07-17) — 없으면 전체 TECH_SEEDS.
    반환: {seed, headline, news:[...]} — headline이 실제 글 주제.
    """
    exclude = exclude or set()
    exclude_headlines = exclude_headlines or set()
    seeds = [s for s in (seeds or TECH_SEEDS) if s not in exclude]
    random.shuffle(seeds)
    # (총점=kw+최신가점, kw점수, seed, news_item, news_list) — 스킵 판정은 kw로, 랭킹은 총점으로
    candidates = []
    for seed in seeds[:10]:
        news = _recent_tech_news(seed, days=days)
        for n in news:
            if n["title"] in exclude_headlines:
                continue
            kw = _score_headline(n["title"])
            candidates.append((kw + _recency_bonus(n.get("date", "")), kw, seed, n, news))
    # 소비자 신호 없는 헤드라인은 최신 가점만으로 뽑히지 않게 원천 배제(B2B 억지글 방지)
    candidates = [c for c in candidates if c[1] > 0]
    if not candidates:
        logger.warning("소비자 관심 주제 없음 — 오늘 발행 스킵")
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    total_score, kw_score, seed, item, news = candidates[0]
    seed = _realign_seed(seed, item["title"])
    logger.info(f"주제 선정: [{seed}] {item['title'][:40]} (kw {kw_score} + 최신가점 = {total_score})")
    # 선정 헤드라인과 같은 시드의 뉴스만 맥락으로 전달(초점 유지).
    # 선정 기사를 news 맨 앞으로 → 대표 실사진(og:image)이 '헤드라인 기사'에서 우선 추출되어
    # 본문 주제와 무관한 다른 기사 사진이 대표로 붙던 문제 방지(2026-07-16: 태양광카메라 글에
    # 폰가격 배너가 붙던 실측).
    news_ordered = [item] + [n for n in news if n is not item]
    # score: 카테고리 간 '오늘 가장 뜨거운 이슈' 비교용(tech_post가 사용, 2026-07-17)
    return {"seed": seed, "headline": item["title"], "news": news_ordered, "score": total_score}


def _build_news_block(topic: dict) -> str:
    lines = [f"[최신 뉴스 — {datetime.now(KST).strftime('%Y년 %m월 %d일')} 기준, 최근 7일 기사만]"]
    lines.append(f"주제 시드: {topic['seed']}")
    for n in topic["news"][:6]:
        lines.append(f"  · {n['date'][:16]} | {n['title']}")
        if n.get("desc"):
            lines.append(f"    → {n['desc'][:100]}")
    lines.append("\n위 뉴스 팩트에 있는 사실만 사용해라. 없는 스펙·가격·일정은 지어내지 말 것.\n")
    return "\n".join(lines)


def generate_tech_post(api_key: str, fmt: str = "breaking", topic: dict | None = None) -> dict | None:
    """테크 포스트 생성. fmt: breaking/explain/pick/compare. topic 없으면 자동 선정."""
    if fmt not in _FMT_PROMPTS:
        fmt = "breaking"
    if topic is None:
        topic = pick_tech_topic()
        if topic is None:
            logger.error("최신 테크 뉴스 없음 — 생성 중단")
            return None

    news_block = _build_news_block(topic)
    system = _FMT_PROMPTS[fmt]
    base_user = news_block + (
        f"\n위 뉴스 중 가장 화제성 있는 '{topic['headline']}' 관련 내용을 중심으로 "
        f"'{fmt}' 형식의 테크 글을 작성해라.\n"
        "- ★독자가 이 소식에서 '진짜 궁금해할 것'과 '나한테 무슨 이득·손해인지'를 먼저 떠올리고, 그걸 축으로 써라. 정보 나열 금지, 스펙은 반드시 '왜 좋은지/아쉬운지'로 해석.\n"
        "- ★재미: 도입부는 궁금증·의외성·손해회피로 확 잡고, 문체를 섞어라('~습니다' 3연속 금지, 질문·짧은 단정·대비 활용). 밋밋한 설명체 금지.\n"
        "- ★본문 1,800~2,400자. 각 소제목 4~6줄로 충실히(빈약한 한두 줄 금지).\n"
        "- ★구체 팩트: 모델명·수치·가격대·경쟁/이전 세대 비교를 뉴스 팩트 범위에서. 없는 사실 창작 금지, 확정 안 된 건 '~로 알려졌다' 톤, 기준일 표기 필수.\n"
        "- 맨 위 [사진1]은 발행 스크립트가 뉴스 실사진을 자동으로 얹는 자리다. 마커는 [사진1] 하나만 두고, 도입부에서 '사진을 보면' 식으로 이미지를 설명하지 마라."
    )

    # ✔요약박스·FAQ 제거로 본문이 짧아지는 경향 → 목표 미달 시 '더 두껍게' 피드백을 주입해 재생성.
    # 하한(TECH_BODY_MIN)은 return None 방지용 안전망, 목표(TARGET)는 품질 유도용.
    TECH_BODY_TARGET = 1700
    extra = ""
    best = None
    best_len = 0
    waits = [10, 30]
    for attempt in range(1, len(waits) + 2):
        try:
            # 실시간성 강화: Google Search Grounding 활성화(뉴스 팩트 보강)
            raw = _gen_text(api_key, base_user + extra, system, 8192, 0.85, use_search=True)
            if not raw:
                logger.warning(f"테크글 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"테크글 파싱 실패 (시도 {attempt})")
                continue
            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            # 리뷰/스펙형 빈약 가드(2026-07-19): 표가 메타(모델·가격·판매처)뿐이면 리뷰가 아니라
            # 광고 전단이다 — 실스펙 행 부족 시 검색 보강 재생성.
            if fmt == "pick":
                tbl = "\n".join(parsed.get("table_strs", []) or [])
                spec_rows = max(0, len([ln for ln in tbl.splitlines() if "|" in ln]) - 1)
                if spec_rows < 5:
                    logger.warning(f"테크글(pick) 스펙 표 빈약({spec_rows}행) — 검색 보강 재생성")
                    extra = (
                        f"\n\n[재작성 지시] 직전 원고의 스펙 표가 {spec_rows}행뿐이었다(모델·가격 메타 위주). "
                        "검색으로 제조사 공식 스펙을 확보해 성능 스펙(용량·소비전력·소음·크기·기능 등) 행을 "
                        "3개 이상 추가하고, 본문도 그 스펙 근거로 장단점을 다시 써라."
                    )
                    continue
            if body_len < TECH_BODY_MIN:
                logger.warning(f"테크글 본문 짧음 ({body_len}자, 최소 {TECH_BODY_MIN}) — 재생성")
                extra = (
                    f"\n\n[재작성 지시] 직전 원고가 {body_len}자로 너무 짧았다. 각 소제목 섹션을 4~6줄로 "
                    "늘리고 배경·이전 세대/경쟁 제품 비교·소비자 영향·구체 수치를 더 담아 전체 1,800자 "
                    "이상으로 다시 써라. 단, [최신 뉴스]에 없는 사실은 절대 지어내지 마라."
                )
                continue
            # ★반말 종결 게이트(존댓말 강제, 2026-07-27 실사고 대응 — '문체 섞기' 지시가
            # 반말 이탈을 유발하던 경로): 반말 초안은 best 후보로도 보관하지 않는다.
            banmal = banmal_gate(parsed.get("body", ""), parsed.get("faq_str", ""),
                                 parsed.get("summary_text", ""))
            if banmal:
                logger.warning(f"테크글 반말 종결 {len(banmal)}건({banmal[0]!r} 등) — 재생성")
                extra = ("\n\n[재작성 지시] 직전 원고에 반말 종결 문장이 있었다("
                         + " / ".join(repr(b) for b in banmal[:3])
                         + "). 모든 문장을 존댓말(~요/~죠/~습니다)로 종결해 다시 써라. "
                         "짧은 단정문도 반드시 존댓말('가격이 문제죠.' O / '가격이 문제다.' X). 인용문만 예외.")
                continue
            # 하한 통과 — 최장본 보관(마지막에 목표 미달이어도 최선본으로 발행)
            if body_len > best_len:
                best, best_len = parsed, body_len
            if body_len < TECH_BODY_TARGET and attempt <= len(waits):
                logger.info(f"본문 {body_len}자 — 목표({TECH_BODY_TARGET}자) 미달, 더 두껍게 재시도")
                extra = (
                    f"\n\n[재작성 지시] 직전 원고가 {body_len}자였다. 사실 왜곡·창작 없이 각 섹션의 "
                    "설명·맥락·비교를 더 풍부하게 늘려 1,800자 이상으로 다시 써라."
                )
                continue
            break  # 목표 도달 or 마지막 시도 — best 확정
        except Exception as e:
            logger.error(f"테크글 생성 실패 (시도 {attempt}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])

    if best is None:
        return None
    best["fmt"] = fmt
    best["seed"] = topic["seed"]
    best["image_strategy"] = FMT_IMAGE[fmt]
    logger.info(
        f"테크글 생성 완료 [{fmt}]: {best.get('title')!r} "
        f"(본문 {best_len}자, 표={bool(best.get('table_str'))}, "
        f"FAQ={bool(best.get('faq_str'))}, 요약={bool(best.get('summary_text'))})"
    )
    return best


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    from config import GOOGLE_API_KEY

    fmt_arg = sys.argv[1] if len(sys.argv) > 1 else "breaking"
    post = generate_tech_post(GOOGLE_API_KEY, fmt=fmt_arg)
    if not post:
        print("생성 실패")
        sys.exit(1)
    print("\n" + "=" * 70)
    print(f"[형식] {post['fmt']}  |  [이미지전략] {post['image_strategy']}  |  [시드] {post['seed']}")
    print(f"[제목] {post['title']}")
    print(f"[태그] {', '.join(post.get('tags', []))}")
    print(f"[소제목] {post.get('subheadings')}")
    print("=" * 70)
    print(post["body"])
    print("=" * 70)
    if post.get("table_strs"):
        print("[표]", post["table_strs"])
    if post.get("faq_pairs"):
        print("[FAQ]", post["faq_pairs"])
