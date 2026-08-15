# naver_blog 프로젝트 컨텍스트

> # ▶▶ 세션 시작 시 가장 먼저: `docs/NEXT_SESSION.md` 를 읽는다 ◀◀
> 2026-07-31 회사 PC 세션에서 확정한 **착수 순서(A→B→C→D)**, 보류 항목,
> 반복하면 안 되는 실수가 거기 정리돼 있다. 다른 작업을 시작하기 전에 이 파일을 먼저 확인하고,
> 사용자가 다른 지시를 하지 않으면 **A항목(발행 이력 A/S 4필드)부터 착수**한다.
> 날짜별 상세 기록은 `docs/HANDOFF.md`, 분석 원본은 `docs/benchmark/`.

> ## ⚠️ 작업 전 필수 규칙 (글쓰기/프롬프트/품질 관련 모든 작업)
> 1. **[docs/WRITING_SYSTEM.md](docs/WRITING_SYSTEM.md)를 먼저 끝까지 읽고** 시작한다. 특히 §5·§6(모바일 가독성 원칙)·§7(미해결 검토사항). 글쓰기 방향은 항상 이 문서와 충돌하지 않아야 한다.
> 2. 글쓰기 방식에 대한 **새 지시·검토사항·미해결 이슈가 생기면 즉시 WRITING_SYSTEM.md에 추가**한다(검토사항은 §7). 이 문서를 단일 기준점(single source of truth)으로 유지해 작업마다 일관성을 보장한다.
> 3. 프롬프트(content.py 등) 수정 시 품질 게이트(quality.py)와의 정합성도 함께 확인한다.

## 프로젝트 개요
네이버 블로그 **고CPC 정보성** 자동 포스팅 파이프라인 (Playwright 브라우저 자동화)

**블로그:** blog.naver.com/benefit_genie
**네이버 계정 ID:** benefit_genie
**블로그명/닉네임:** 베네핏지니

### ★현재 방향 (2026-06-30 피벗, 2026-07-03 고단가 재편): 고CPC 정보성 카테고리
- **주제:** 2030 신혼·1인가구가 꼭 알아야 할 **돈·제도 정보** (생활밀착 고정보)
- **활성 공개 카테고리:** ①정부지원·혜택 ②금융·재테크 ③세금·절세 ④보험 ⑤부동산·주거 (전부 고CPC). **⑥건강·의료는 2026-07-03부터 비공개 전환 + health_post 크론 정지**(고단가 카테고리 위주 재편, 코드/품질 문제 아님 — 보관 상태, 재개 시 CLAUDE.md·workflow 원복).
- **페르소나:** **"놓치기 쉬운 돈·혜택·건강 정보를 직접 발품 팔아 쉽게 정리해주는 똑부러진 28세 생활정보 언니 '베네핏지니'."** 친근하되 **정확·신뢰**가 최우선. "제가 직접 알아보니", "저도 처음엔 헷갈렸는데" 같은 1인칭 경험은 자연스럽게만(과하지 않게, D.I.A.+ 경험성 점수용). 살림주부 색채(다이소·집들이 에피소드) 제거.
- **수익 구조:** 네이버 애드포스트(고CPC) → 이후 동일 자료로 **티스토리+구글 애드센스** 확장(정보성은 애드센스 단가 훨씬↑).
- **엔진:** [generator/info_content.py](generator/info_content.py)(범용, ④⑤⑥과 ③), gov/health는 기존 개별 생성기. 검증된 구조=요약블록+1개3열표+자격·주의불릿+방법①②③+FAQ+소제목번호없음+글머리'· '+헤더카드만.

### 보관(삭제 금지): 살림 잡블로그 자료 (추후 별도 블로그용)
- 살림(`_SYSTEM`/daily_post)·레시피(recipe.py)·일상 프롬프트·스크립트 **전부 유지**. 크론만 정지.
- 살림 페르소나(20대 후반 신혼주부, 다이소/이케아 가성비 살림)는 그 블로그용으로 보존.

---

## 포스팅 방식
- Naver Blog API 폐지됨 → Playwright로 SE3 에디터 직접 조작
- 쿠키 기반 세션 재사용 (get_cookies.py로 1회 발급 → GitHub Secret에 저장)

---

## 핵심 파일 구조

```
generator/
  keyword.py      — 에버그린 키워드 + 시즌 키워드 풀
  content.py      — Gemini 2.5 Flash 블로그 글 생성 (plain text)
  image.py        — Pexels API 이미지 (추후 활용)
poster/
  naver_blog.py   — Playwright SE3 에디터 자동 포스팅
scripts/
  daily_post.py   — 메인 실행 (매일 1회)
  get_cookies.py  — 초기 쿠키 발급 (로컬 1회 실행, headless=False)
data/
  post_history.json    — 포스팅 이력 (중복 방지)
  naver_cookies.json   — 로컬 쿠키 저장 (GH Actions는 Secret 사용)
.github/workflows/
  daily_post.yml  — GitHub Actions 스케줄러
```

---

## GitHub Secrets 필요 목록

| Secret | 설명 |
|---|---|
| `NAVER_ID` | benefit_genie |
| `NAVER_PW` | 네이버 비밀번호 |
| `NAVER_COOKIES` | get_cookies.py 실행 후 출력되는 JSON (쿠키 만료 시 재발급) |
| `GOOGLE_API_KEY` | Gemini API 키 |
| `PEXELS_API_KEY` | Pexels 이미지 API 키 (없어도 동작) |

---

## 초기 셋업 순서

1. .env 파일 생성 (NAVER_ID, NAVER_PW, GOOGLE_API_KEY 입력)
2. `pip install -r requirements.txt && playwright install chromium`
3. `python scripts/get_cookies.py` 실행 → 브라우저에서 로그인 → 쿠키 저장
4. data/naver_cookies.json 내용 전체를 GitHub Secret `NAVER_COOKIES`에 등록
5. 나머지 Secrets 등록 (NAVER_ID, NAVER_PW, GOOGLE_API_KEY)
6. GitHub Actions 활성화

---

## 알려진 설계 결정

- 중복 방지: data/post_history.json 날짜 기준 (당일 1회)
- 쿠키 만료: 약 30~90일 → get_cookies.py 재실행 후 Secret 업데이트
- 이미지: 1단계는 텍스트 위주 포스팅, 추후 이미지 삽입 자동화 추가 예정
- 쿠팡 링크: coupang_hints 로깅만 (추후 자동 링크 삽입 추가 예정)

---

## 2026-06-24 작업 이력 (Antigravity에서 작성)

- **글쓰기 체계 및 가이드라인 정립**:
  - [docs/WRITING_SYSTEM.md](file:///C:/박관용/CLAUDE/ai-agent/benefit_genie_blog/docs/WRITING_SYSTEM.md) 생성 (페르소나 톤앤매너, 모바일 단락 최적화, 5대 도입부 유형, 표/FAQ 구조 명세).
- **품질 채점 기준 고도화 ([quality.py](file:///C:/박관용/CLAUDE/ai-agent/benefit_genie_blog/generator/quality.py))**:
  - `_AI_PATTERNS`에 흔히 발생하는 AI/Gemini 말투 패턴 대거 추가 ("다양한 ~", "도움이 되길", "기억하세요", 기계적 번호 열거 등).
- **프롬프트 및 퇴고 엔진 연동 ([content.py](file:///C:/박관용/CLAUDE/ai-agent/benefit_genie_blog/generator/content.py), [recipe.py](file:///C:/박관용/CLAUDE/ai-agent/benefit_genie_blog/generator/recipe.py))**:
  - `_SYSTEM`, `_REFINE_SYSTEM`, `_RECIPE_SYSTEM` 프롬프트에 금지된 AI 상투어 및 대안 표현 반영하여 초안 생성 및 2차 퇴고 과정 개선.
- **임시저장 검증 모드 테스트**:
  - `DRAFT=true` 모드로 로컬 테스트 실행 및 검증 중.
- **AEO/GEO 및 자동화 고도화 적용 (A, B, C 반영)**:
  - **A. 휴먼 제스처 시뮬레이션 (`_simulate_human_review`)**: 발행/임시저장 전 마우스 랜덤 이동 및 스크롤 다운/업 제스처를 수행하여 봇 탐지 우회 안정성 강화.
  - **B. 네이버 에디터 인용구 & 제목 컴포넌트 연동**: 소제목에는 에디터 내 Heading 스타일(제목 2)을, FAQ 질문에는 인용구(Quotation) 컴포넌트를 Playwright 조작으로 우선 적용(실패 시 font size/bold 서식으로 fallback).
  - **C. AEO 정보 밀도 검증기 고도화 (`quality.py`)**: 단순히 구체적 팩트 키워드 수만 세던 방식에서, 전체 문장 중 수치/단위/브랜드 등 팩트 데이터를 포함한 문장의 비율(AEO Density)을 분석하도록 채점 로직 고도화.
- **최신 2026 네이버 검색 개편 대응 완결형 포스팅 추가 고도화 (Action 1, 2, 3 반영)**:
  - **Action 1 (이미지 ALT 텍스트 자동 기입)**: Pexels API 등 이미지 삽입 성공 시 이미지 설명 캡션 입력창에 AI가 작성한 alt_text 설명글을 자동 입력하도록 `_fill_image_caption` 개발.
  - **Action 2 (지식스니펫용 두괄식 프롬프트 규칙 주입)**: `content.py` 및 `recipe.py` 템플릿에 "모든 소제목 바로 다음 단락의 1~2문장은 질문이나 소제목 주제에 대한 결론/정의 형식으로 명확하게 즉시 답변할 것" 지침 주입.
  - **Action 3 (과거 포스팅 링크 연계기 개발)**: `daily_post.py`와 `recipe_post.py`에 `_append_internal_links`를 탑재하여 동일 카테고리/주제의 과거 성공 글의 링크와 제목을 마지막 사진 마커(`[사진N]`) 직전에 자동으로 연결하여 체류시간 최적화.
- **추가 최적화 기능 적용 (피드백 루프 & 쿠팡 쇼핑가이드 삽입)**:
  - **품질 피드백 루프 (Feedback loop)**: `daily_post.py`와 `recipe_post.py` 생성 루프에 품질 점수 검증 및 재생성 시 이전의 탈락 원인(이슈들)을 LLM에 `feedback` 매개변수로 주입하여 퇴고 정확도를 극대화하는 보완 피딩 루프 구축.
  - **쿠팡 우회 쇼핑가이드 자동 생성**: 본문에 `coupang_hints`가 존재할 시, 광고/어뷰징 누락 필터를 우회하기 위해 텍스트 기반의 안전한 최저가 검색 안내 문구(`_append_shopping_guide`)를 본문 하단(마지막 사진 직전)에 자동 조립 삽입.
- **이미지 퀄리티 및 가독성 품질 고도화**:
  - **뜬금없는 인물 사진(외국인 모델 등) 완전 배제**: `generator/image.py` 의 `_OFFTOPIC_RE` 정규식을 확장하여 `person`, `people`, `man`, `woman`, `model`, `face`, `hand` 등 인물 요소가 매칭되는 이미지를 철저히 필터링하고 제외.
  - **레시피 이미지 한식화 쿼리 보정**: 요리/조리 관련 키워드 검색 시 자동으로 `korean` 수식어가 덧붙도록 `generator/image.py` 의 `_keyword_to_en`을 개선하여 뜬금없는 양식/스톡 사진 매칭 차단.
  - **문장 쪼개짐 방지 규칙 탑재**: 본문 내 `[사진N]` 마커가 문장 중간에 삽입되어 가독성이 깨지던 현상을 해소하기 위해 `content.py` 와 `recipe.py` 시스템 프롬프트에 "반드시 마침표 뒤 독립된 개행(새로운 줄)에 단독으로만 사진 마커를 배치할 것" 절대 규칙 주입.

