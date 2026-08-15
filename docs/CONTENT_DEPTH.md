# 콘텐츠 심화 전략 (2026-07-08)

## 심화 정보 담을 수 있나?

**예.** 플랫폼별 역할이 다릅니다.

| 플랫폼 | 기존 목표 | 변경 후 | 심화 수단 |
|--------|-----------|---------|-----------|
| **네이버 info** | 1,800~2,400자 | **2,200~2,800자** | 계산 예시 2~3개, 출처 1줄, FSS·뉴스 팩트 |
| **네이버 gov** | 2,000~2,500자 | **2,200~2,800자** | 지원금 시뮬레이션, 뉴스·복지로 출처 |
| **WP 심층** | 2,500~4,000자 | **2,800~4,500자** | 계산 2케이스+, 팩트 출처, 관련글 링크 |

- **네이버**: 모바일 스캔형 6소제목 구조 유지(§6). 길이·계산·출처로 깊이 확장.
- **WP**: 구글 SEO용 — 네이버보다 30~80% 길게, 의사결정 프레임·흔한 오해 섹션.

## 하드 게이트 (2026-07-08 강화)

| 파이프라인 | prose 최소 | 재생성 트리거 |
|------------|-----------|---------------|
| info | **2,000자** | 길이·계산·출처·구조·무근거 |
| gov | **2,000자** | 길이·계산·출처 |
| WP deep | **2,500자** | 길이·계산·AI패턴·표·FAQ·무근거 |

## 코드 변경 요약

- `generator/info_content.py` — `INFO_BODY_MIN=2000`, 계산·출처 게이트
- `generator/content.py` (`generate_gov_post`) — `GOV_BODY_MIN=2000`, 계산·출처
- `generator/info_collector.py` — 뉴스 6건, 공식 출처·계산 힌트
- `generator/source_refs.py` — 카테고리별 공식 URL
- `generator/deep_content.py` — 2,800자+ 게이트, 계산 2케이스
- `generator/wp_render.py` — ol 연속 번호, 관련글 블록
- `scripts/wp_post.py` — 같은 카테고리 내부 링크

## DRAFT 검증 권장

```bash
# 네이버 (GitHub Actions)
gh workflow run info_post.yml -f category=세금절세 -f draft=true

# WP
gh workflow run wp_dry.yml -f topic=earn_income_credit
```

## 사용자만 가능

- Google Search Console (`docs/SETUP_GSC.md`)
- NAVER_COOKIES 재발급 (6/22 등록)
