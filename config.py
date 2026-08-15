import os
from dotenv import load_dotenv

load_dotenv()

# 네이버 계정 (Playwright 로그인용)
NAVER_ID      = os.getenv("NAVER_ID", "")       # 로그인 ID: gyhj1101
NAVER_PW      = os.getenv("NAVER_PW", "")
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "")  # 블로그 주소 ID: hyunji_unni
# GH Actions에서 쿠키 재사용 (JSON 문자열)
NAVER_COOKIES = os.getenv("NAVER_COOKIES", "")

# 형수의테크공장 블로그 (hyungsutech, khj 계정 — 현지언니와 별도 네이버 계정)
TECH_NAVER_ID      = os.getenv("TECH_NAVER_ID", "")
TECH_NAVER_PW      = os.getenv("TECH_NAVER_PW", "")
TECH_NAVER_BLOG_ID = os.getenv("TECH_NAVER_BLOG_ID", "hyungsutech")
TECH_NAVER_COOKIES = os.getenv("TECH_NAVER_COOKIES", "")

# Google (Gemini)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# 워드프레스 (REST 발행 — AWS 자가호스팅, WP_PIPELINE §5 B)
WP_URL    = os.getenv("WP_URL", "")       # 예: https://hyunjiunni.com (끝 슬래시 없이)
WP_USER   = os.getenv("WP_USER", "")      # 관리자 사용자명
WP_APP_PW = os.getenv("WP_APP_PW", "")    # 애플리케이션 비밀번호(표시된 공백 포함 그대로)

# Pexels (이미지)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# 팩트 수집 API (없어도 동작 — 있으면 최신 정보 보강)
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")      # 네이버 뉴스 검색 API
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")  # 네이버 뉴스 검색 API
FSS_API_KEY         = os.getenv("FSS_API_KEY", "")          # 금융감독원 금융상품 공시 API
PUBLIC_DATA_KEY     = os.getenv("PUBLIC_DATA_KEY", "")      # 공공데이터포털 통합키

# Dirs
ROOT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT_DIR, "data")
LOG_DIR  = os.path.join(ROOT_DIR, "logs")
