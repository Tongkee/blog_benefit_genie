"""
Playwright 포스팅 로직만 단독 테스트 (Gemini 생략)
로컬에서: python -m scripts.test_post
"""
import asyncio
import logging
import os
import sys

# Windows cp949 인코딩 오류 방지
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import NAVER_ID, NAVER_PW, NAVER_BLOG_ID, NAVER_COOKIES
from poster.naver_blog import post_to_naver_blog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

TEST_TITLE = "🧪 인용구 및 표 고도화 테스트 포스팅"
TEST_BODY = """이 글은 네이버 스마트에디터 인용구 삽입 시의 텍스트 소실 없는 정형화 및 표 제목줄 볼드 처리 고도화를 자동화 검증하기 위한 임시저장 테스트 글입니다.

[소제목] 테스트 소제목
소제목 스타일이 에디터 제목 2 서식으로 이 단락에 정상 지정되는지 확인합니다.
[사진1]

[표삽입]

자주 묻는 질문

[FAQ삽입]"""

TEST_TAGS = ["테스트", "인용구고도화", "표자동화", "카드뉴스"]
TEST_TABLE = "구분 | 권장 교체 주기 | 청소 방법\n헤파 필터 | 6개월 ~ 1년 | 청소기 흡입만 가능 (물세척 금지)\n탈취 필터 | 1년 | 세척 불가 (교체만 가능)\n극세사 필터 | 2~4주 | 흐르는 물에 가볍게 세척 후 그늘 건조"
TEST_FAQ_QUESTIONS = [
    "Q: 공기청정기 필터는 진짜 물로 씻으면 안 되나요?",
    "Q: 교체 알림 센서는 어떻게 리셋하나요?"
]
TEST_FAQ_PAIRS = [
    ("💡 Q: 공기청정기 필터는 진짜 물로 씻으면 안 되나요?", "A: 네, 헤파필터는 물에 젖는 순간 필터 내부의 정전기적 집진 기능이 완전히 파괴되어 필터로서의 수명이 끝나므로 절대 물로 씻으면 안 됩니다."),
    ("💡 Q: 교체 알림 센서는 어떻게 리셋하나요?", "A: 보통 필터 교체 후 전원 버튼이나 리셋 버튼을 3초 이상 꾹 누르고 있으면 알림 신호음과 함께 초기화가 완료됩니다.")
]

TEST_IMAGES = [
    {
        "url": "https://images.pexels.com/photos/10827363/pexels-photo-10827363.jpeg",
        "alt_text": "공기청정기 필터 교체 가이드",
        "label": "공기청정기 필터 고르는 꿀팁"
    }
]

if __name__ == "__main__":
    print(f"NAVER_ID: {NAVER_ID}")
    print(f"NAVER_BLOG_ID: {NAVER_BLOG_ID}")
    print(f"쿠키 있음: {'예' if NAVER_COOKIES else '아니오'}")
    print("-" * 50)

    for i in range(1, 4):
        print(f"\n[{i}/3] 실전 테스트 포스팅 시도 중...")
        title = f"{TEST_TITLE} - {i}번째 테스트"
        
        # 각 테스트마다 약간 다른 레이아웃 적용
        subheadings = ["테스트 소제목", "자주 묻는 질문"]
        
        result = post_to_naver_blog(
            naver_id=NAVER_ID,
            naver_pw=NAVER_PW,
            blog_id=NAVER_BLOG_ID or NAVER_ID,
            title=title,
            body=TEST_BODY,
            tags=TEST_TAGS,
            naver_cookies=NAVER_COOKIES,
            draft=False,  # 실전 발행!
            table_str=TEST_TABLE,
            subheadings=subheadings,
            faq_questions=TEST_FAQ_QUESTIONS,
            faq_pairs=TEST_FAQ_PAIRS,
            images=[
                {
                    "url": "https://images.pexels.com/photos/10827363/pexels-photo-10827363.jpeg",
                    "alt_text": f"테스트 이미지 {i}",
                    "label": f"소제목 테스트 요약 {i}"
                }
            ],
        )

        if result:
            print(f"✅ 포스팅 {i} 성공! URL: {result.get('post_url')}")
        else:
            print(f"❌ 포스팅 {i} 실패 — 스크린샷 확인: data/screenshots/")

