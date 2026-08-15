# 🪄 블로그 혜택 지니 (Blog Benefit Genie)

네이버 블로그 **고CPC 정보성 카테고리**(정부지원금, 혜택, 금융, 절세, 부동산 등) 포스팅을 자동 생성하고 **Playwright** 브라우저 자동화를 통해 네이버 SmartEditor ONE (SE3) 에디터에 자동으로 발행하는 파이프라인 프로젝트입니다.

---

## 📌 주요 특징 (Key Features)

1. **고단가 CPC / AEO(Answer Engine Optimization) 최적화 글 생성**
   - 2030 신혼/1인가구 대상 친근하고 신뢰도 높은 "베네핏지니" 페르소나 적용
   - Gemini API 기반 고품질 정보성 콘텐트 자동 작성 (핵심 요약, 3열 비교표, 불릿 포인트, FAQ 등)
   - 네이버 D.I.A.+ 및 스마트스니펫 / 지식스니펫 우대 구조 탑재

2. **자동 포스팅 & SE3 에디터 제어**
   - Playwright 기반 브라우저 자동화 (네이버 API 폐지에 대응)
   - 소제목 Heading(제목 2) 설정, 인용구 컴포넌트, 서식 자동 적용
   - 마우스 이동 및 스크롤 휴먼 제스처 시뮬레이션으로 안정적인 자동 발행 지원

3. **자동화 스케줄링 & CI/CD**
   - GitHub Actions workflows (`daily_post.yml`, `info_post.yml` 등)를 통해 매일 지정된 시각 자동 포스팅
   - 쿠키 기반 로그인 유지 (30~90일 주기 업데이트)

4. **콘텐츠 품질 관리 & 스마트 링크 연계**
   - AI 특유의 상투어 및 기계적 표현 자동 검증/퇴고 피드백 루프
   - 동일 카테고리 내부 링크 연결을 통한 블로그 체류시간 최적화

---

## 📁 프로젝트 구조 (Directory Structure)

```
blog_benefit_genie/
├── generator/            # 콘텐츠 생성기 모듈
│   ├── info_content.py   # 정보성 포스팅 전용 글 생성 (Gemini API)
│   ├── keyword.py        # 키워드 추천 및 에버그린/시즌 키워드 관리
│   ├── quality.py        # 콘텐츠 품질 채점 및 AI 상투어 검증
│   └── image.py          # Pexels API 등 이미지 검색/다운로드
├── poster/               # 네이버 블로그 자동 포스팅 모듈
│   └── naver_blog.py     # Playwright 기반 SE3 에디터 자동화 컨트롤러
├── scripts/              # 파이프라인 실행 및 관리 스크립트
│   ├── info_post.py      # 정보성 글 생성 + 발행 메인 스크립트
│   ├── get_cookies.py    # 네이버 쿠키 1회성 추출 스크립트
│   └── run_all_info.py   # 다중 카테고리 일괄 포스팅 실행기
├── data/                 # 포스팅 이력 및 상태 관리
│   └── post_history.json # 중복 발생 방지 및 포스팅 이력 데이터
├── docs/                 # 작업 문서 및 시스템 가이드
│   ├── WRITING_SYSTEM.md # 글쓰기 체계, 페르소나 및 포맷 가이드 (Single Source of Truth)
│   ├── HANDOFF.md        # 개발 작업 및 운영 히스토리
│   └── NEXT_SESSION.md   # 다음 작업 착수 가이드
├── .github/workflows/    # GitHub Actions 자동 스케줄러
├── config.py             # 전체 환경 설정 및 카테고리 정의
└── requirements.txt      # 의존성 패키지 목록
```

---

## 🛠️ 빠른 시작 Guide

### 1. 환경 변수 설정
프로젝트 루트 경로에 `.env` 파일을 생성하고 필요한 정보들을 설정합니다 (`.env.example` 참조).

```env
NAVER_ID=your_naver_id
NAVER_PW=your_naver_password
GOOGLE_API_KEY=your_gemini_api_key
PEXELS_API_KEY=your_pexels_api_key_optional
```

### 2. 패키지 및 브라우저 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. 네이버 로그인 쿠키 추출 (최초 1회)
브라우저 창이 열리면 로그인 절차(필요 시 2차 인증)를 완료합니다.

```bash
python scripts/get_cookies.py
```
> `data/naver_cookies.json` 파일에 로그인 쿠키가 저장됩니다.

### 4. 포스팅 포스팅 실행 (로컬 테스트)

```bash
# 임시저장(Draft) 모드로 테스트 실행
DRAFT=true python scripts/info_post.py

# 바로 실시간 발행
python scripts/info_post.py
```

---

## 🔐 GitHub Secrets 설정 (자동화 배포 시)

GitHub Actions를 사용하여 매일 포스팅을 자동화하려면 Repository `Settings > Secrets and variables > Actions`에 다음 항목들을 등록해 주어야 합니다.

| Secret Name | 설명 |
|---|---|
| `NAVER_ID` | 네이버 계정 아이디 |
| `NAVER_PW` | 네이버 계정 비밀번호 |
| `NAVER_COOKIES` | `data/naver_cookies.json` 파일의 JSON 문자열 전체 내용 |
| `GOOGLE_API_KEY` | Gemini API Key |
| `PEXELS_API_KEY` | Pexels 이미지 API Key (선택 사항) |

---

## 📖 주요 문서 안내

- **글쓰기 체계 및 원칙**: [`docs/WRITING_SYSTEM.md`](file:///c:/Users/tongk/Documents/%EC%95%88%ED%8B%B0%EA%B7%B8%EB%9E%98%EB%B9%84%ED%8B%B0/02%20%ED%83%80%20%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/blog_benefit_genie/docs/WRITING_SYSTEM.md)
- **개발 및 운영 가이드**: [`CLAUDE.md`](file:///c:/Users/tongk/Documents/%EC%95%88%ED%8B%B0%EA%B7%B8%EB%9E%98%EB%B9%84%ED%8B%B0/02%20%ED%83%80%20%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/blog_benefit_genie/CLAUDE.md)
- **작업 인수인계 문서**: [`HANDOFF.md`](file:///c:/Users/tongk/Documents/%EC%95%88%ED%8B%B0%EA%B7%B8%EB%9E%98%EB%B9%84%ED%8B%B0/02%20%ED%83%80%20%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8/blog_benefit_genie/HANDOFF.md)
