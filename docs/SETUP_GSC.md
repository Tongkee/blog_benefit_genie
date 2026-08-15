# Google Search Console 등록 가이드 (hyunjiunni.com)

> 자동화 불가 항목 — **사용자가 Google 계정으로 1회만** 진행하면 됩니다.

## 1. 사전 확인

- 사이트: https://hyunjiunni.com
- XML Sitemap: https://hyunjiunni.com/wp-sitemap.xml
- robots.txt: https://hyunjiunni.com/robots.txt (Sitemap 줄 포함)
- 사이트 공개: WordPress `blog_public=1`, 검색엔진 색인 허용

## 2. Search Console 속성 추가

1. https://search.google.com/search-console 접속
2. **속성 추가** → **URL 접두어** 선택 → `https://hyunjiunni.com` 입력
3. 소유권 확인 방법 (택1):

### 방법 A — DNS TXT (권장, 가비아)

1. GSC에서 **도메인** 또는 **DNS TXT** 확인 선택
2. 가비아 → hyunjiunni.com → DNS 관리 → **TXT 레코드** 추가
3. GSC가 제공한 `google-site-verification=...` 값 붙여넣기
4. 전파 후 GSC에서 **확인**

### 방법 B — HTML 메타 태그

1. GSC에서 HTML 태그 방식 선택 → `content="..."` 값 복사
2. 서버에서 한 번만 실행:
   ```bash
   sudo -u www-data wp --path=/var/www/html option update hyunji_gsc_verification '여기에_content값'
   ```
   (mu-plugin `hyunji-seo.php`가 해당 옵션을 `<meta name="google-site-verification">`으로 출력)
3. 또는 WordPress 관리자 → **외모 → 테마 파일 편집** 대신 mu-plugin에 직접 추가

## 3. Sitemap 제출

1. GSC → **Sitemaps** → 새 사이트맵: `wp-sitemap.xml`
2. 상태 **성공** 확인 (글 수에 따라 수분~수일)

## 4. 애드센스 연동 (2026-07-31 이후 예정)

- Search Console 속성과 **동일 Google 계정** 사용 권장
- 애드센스 승인 후: **사이트 → ads.txt** 또는 AdSense 코드 — WP mu-plugin 또는 Insert Headers 플러그인으로 `<head>` 삽입
- 현재는 콘텐츠 축적·품질 리뷰 기간 — 애드센스 연결 전

## 5. 점검 체크리스트

- [ ] GSC 속성 확인 완료
- [ ] Sitemap 제출·색인 시작
- [ ] 대표 URL: https://hyunjiunni.com/ (http→https 리다이렉트 확인)
- [ ] 모바일 사용성 — GSC **모바일 사용편의성** 오류 없음
- [ ] (선택) Bing Webmaster Tools — 동일 sitemap 제출

## 6. 자동화와의 관계

- **네이버 블로그**와 **워드프레스**는 별도 색인 — canonical은 WP 쪽만 관리
- WP 매일 09:05 KST `wp_post.yml` 발행 → sitemap 자동 갱신
- 주제 풀: `scripts/wp_dry.py` `TOPICS` (7종 로테이션)
