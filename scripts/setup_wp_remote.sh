#!/bin/bash
# hyunjiunni.com 워드프레스 초기 설정 — 수익 허브 6종 (2026-07-09)
set -euo pipefail
WP="sudo -u www-data wp --path=/var/www/html"
BASE="https://hyunjiunni.com"

echo "== 사이트 옵션 =="
$WP option update blogname '현지언니'
$WP option update blogdescription '정부 제도·세금·연금·보험·주거를 공식 자료 기준으로 분석하는 생활금융 칼럼'
$WP option update timezone_string 'Asia/Seoul'
$WP option update permalink_structure '/%postname%/'
$WP option update WPLANG 'ko_KR'
$WP option update blog_public 1
$WP option update default_comment_status closed
$WP option update posts_per_page 10
$WP option update show_on_front posts
$WP option update date_format 'Y년 n월 j일'
$WP option update time_format 'G:i'
$WP option update start_of_week 1

echo "== 수익 허브 카테고리 =="
declare -A CAT_SLUG=(
  ['연금·절세 설계']='pension-tax'
  ['대출·신용 전략']='loan-credit'
  ['보험·리스크 설계']='insurance-risk'
  ['세금·환급 가이드']='tax-refund'
  ['주거·청약 전략']='housing-plan'
  ['제도·복지 해설']='policy-benefit'
)
declare -A CAT_DESC=(
  ['연금·절세 설계']='ISA·연금저축·IRP·퇴직연금 세액공제와 장기 절세 전략 심층 분석'
  ['대출·신용 전략']='전세·담보·대환대출 금리 비교와 신용점수 개선 시뮬레이션'
  ['보험·리스크 설계']='실손·자동차·진단비 보장 구조 비교와 갱신·전환 의사결정'
  ['세금·환급 가이드']='연말정산·근로장려금·양도세 환급 시뮬레이션과 절세 순서'
  ['주거·청약 전략']='청약·전세·취득세·LTV 통합 프레임과 5년 주거비 시뮬'
  ['제도·복지 해설']='실업급여·주거급여·에너지 지원 자격 경계값 계산'
)
for name in "${!CAT_SLUG[@]}"; do
  slug="${CAT_SLUG[$name]}"
  desc="${CAT_DESC[$name]}"
  tid=$($WP term list category --name="$name" --field=term_id 2>/dev/null | head -1 || true)
  if [ -n "$tid" ]; then
    $WP term update category "$tid" --slug="$slug" --description="$desc"
  else
    $WP term create category "$name" --slug="$slug" --description="$desc"
  fi
done

echo "== 레거시 카테고리 정리(빈 카테고리 삭제) =="
for old in "정부지원·혜택" "금융·재테크" "세금·절세" "보험" "부동산·주거" "주식"; do
  tid=$($WP term list category --name="$old" --field=term_id 2>/dev/null | head -1 || true)
  if [ -n "$tid" ]; then
    cnt=$($WP term get category "$tid" --field=count 2>/dev/null || echo 1)
    if [ "$cnt" = "0" ]; then
      $WP term delete category "$tid" 2>/dev/null && echo "deleted category: $old" || true
    else
      $WP term update category "$tid" --description="(구 카테고리 — 신규 글은 수익 허브 사용)" 2>/dev/null || true
    fi
  fi
done

echo "== 네비게이션 =="
NAV_FILE=$(mktemp)
cat > "$NAV_FILE" << 'NAVEOF'
<!-- wp:navigation-link {"label":"홈","url":"https://hyunjiunni.com/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"연금·절세","url":"https://hyunjiunni.com/category/pension-tax/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"대출·신용","url":"https://hyunjiunni.com/category/loan-credit/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"보험·리스크","url":"https://hyunjiunni.com/category/insurance-risk/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"세금·환급","url":"https://hyunjiunni.com/category/tax-refund/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"주거·청약","url":"https://hyunjiunni.com/category/housing-plan/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"제도·복지","url":"https://hyunjiunni.com/category/policy-benefit/","kind":"custom","isTopLevelLink":true} /-->
NAVEOF
$WP post update 4 --post_content="$(cat "$NAV_FILE")"
rm -f "$NAV_FILE"

echo "== 소개 페이지 =="
ABOUT_ID=$($WP post list --post_type=page --name=about --field=ID --format=ids 2>/dev/null || true)
if [ -n "$ABOUT_ID" ]; then
  $WP post update "$ABOUT_ID" --post_content='<!-- wp:paragraph --><p><strong>현지언니</strong>는 정부 제도·세금·연금·보험·주거를 <strong>공식 자료 기준</strong>으로 분석하는 생활금융 칼럼입니다.</p><!-- /wp:paragraph --><!-- wp:paragraph --><p>네이버 블로그의 실용 가이드와 달리, 이 사이트는 비교·계산·상황별 판단 기준을 깊게 다룹니다. 수치는 국세청·금감원·국토부 등 공시 자료를 우선 인용합니다.</p><!-- /wp:paragraph -->'
fi

echo "== 작성자 URL =="
$WP user update 1 --user_url="$BASE" 2>/dev/null || true

echo "== 파비콘 =="
ICON_ID=$($WP option get site_icon 2>/dev/null || echo 0)
if [ -z "$ICON_ID" ] || [ "$ICON_ID" = "0" ]; then
  NEW_ICON=$($WP media import /var/www/html/wp-content/mu-plugins/hyunji-favicon.png \
    --title='현지언니' --porcelain 2>/dev/null || true)
  if [ -n "$NEW_ICON" ]; then
    $WP option update site_icon "$NEW_ICON"
  fi
else
  echo "site_icon=$ICON_ID (기존 유지)"
fi

echo "== 사이트 로고 =="
LOGO_ID=$($WP option get custom_logo 2>/dev/null || echo 0)
ICON_ID=$($WP option get site_icon 2>/dev/null || echo 0)
if [ -z "$LOGO_ID" ] || [ "$LOGO_ID" = "0" ]; then
  if [ -n "$ICON_ID" ] && [ "$ICON_ID" != "0" ]; then
    LOGO_ID="$ICON_ID"
    $WP option update custom_logo "$LOGO_ID"
    echo "custom_logo=$LOGO_ID (site_icon 재사용)"
  else
    LOGO_ID=$($WP media import /var/www/html/wp-content/mu-plugins/hyunji-favicon.png \
      --title='현지언니 로고' --porcelain 2>/dev/null || true)
    if [ -n "$LOGO_ID" ]; then
      $WP option update custom_logo "$LOGO_ID"
      $WP option update site_icon "$LOGO_ID"
      echo "custom_logo=$LOGO_ID (신규 import)"
    fi
  fi
else
  echo "custom_logo=$LOGO_ID (기존 유지)"
fi
export LOGO_ID

echo "== 헤더 템플릿 =="
HEADER_FILE=$(mktemp)
cat > "$HEADER_FILE" << HEADEREOF
<!-- wp:group {"align":"full","layout":{"type":"default"}} -->
<div class="wp-block-group alignfull">
<!-- wp:group {"layout":{"type":"constrained"}} -->
<div class="wp-block-group">
<!-- wp:group {"align":"wide","style":{"spacing":{"padding":{"top":"var:preset|spacing|30","bottom":"var:preset|spacing|30"}}},"layout":{"type":"flex","flexWrap":"nowrap","justifyContent":"space-between","verticalAlignment":"center"}} -->
<div class="wp-block-group alignwide" style="padding-top:var(--wp--preset--spacing--30);padding-bottom:var(--wp--preset--spacing--30)">
<!-- wp:group {"style":{"spacing":{"blockGap":"var:preset|spacing|20"}},"layout":{"type":"flex","flexWrap":"nowrap","verticalAlignment":"center"}} -->
<div class="wp-block-group">
<!-- wp:site-title {"level":0} /-->
</div>
<!-- /wp:group -->
<!-- wp:navigation {"ref":4,"overlayBackgroundColor":"base","overlayTextColor":"contrast","layout":{"type":"flex","justifyContent":"right","flexWrap":"wrap"}} /-->
</div>
<!-- /wp:group -->
</div>
<!-- /wp:group -->
</div>
<!-- /wp:group -->
HEADEREOF
HEADER_CONTENT=$(cat "$HEADER_FILE")
rm -f "$HEADER_FILE"
HEADER_ID=$($WP post list --post_type=wp_template_part --name=header --field=ID --format=ids 2>/dev/null | head -1 || true)
if [ -n "$HEADER_ID" ]; then
  $WP post update "$HEADER_ID" --post_content="$HEADER_CONTENT"
else
  HEADER_ID=$($WP post create --post_type=wp_template_part --post_title='Header' --post_name='header' \
    --post_status=publish --post_content="$HEADER_CONTENT" --porcelain)
fi
$WP term create wp_theme twentytwentyfive --slug=twentytwentyfive 2>/dev/null || true
$WP term create wp_template_part_area header --slug=header 2>/dev/null || true
$WP post term set "$HEADER_ID" wp_theme twentytwentyfive 2>/dev/null || true
$WP post term set "$HEADER_ID" wp_template_part_area header 2>/dev/null || true

echo "== 홈 템플릿(히어로+최신글) =="
HOME_FILE=$(mktemp)
cat > "$HOME_FILE" << 'HOMEEOF'
<!-- wp:template-part {"slug":"header"} /-->

<!-- wp:group {"tagName":"main","style":{"spacing":{"margin":{"top":"0"}}},"layout":{"type":"constrained"}} -->
<main class="wp-block-group" style="margin-top:0">
<!-- wp:group {"align":"wide","className":"hj-hero","layout":{"type":"constrained"}} -->
<div class="wp-block-group alignwide hj-hero">
<!-- wp:heading {"level":1} -->
<h1 class="wp-block-heading">현지언니</h1>
<!-- /wp:heading -->

<!-- wp:paragraph {"className":"hj-hero-tagline"} -->
<p class="hj-hero-tagline">놓치기 쉬운 돈·제도 정보를 발품 팔아 쉽게 정리합니다</p>
<!-- /wp:paragraph -->

<!-- wp:html -->
<ul class="hj-hero-chips">
<li><a href="https://hyunjiunni.com/category/pension-tax/">연금·절세</a></li>
<li><a href="https://hyunjiunni.com/category/loan-credit/">대출·신용</a></li>
<li><a href="https://hyunjiunni.com/category/insurance-risk/">보험·리스크</a></li>
<li><a href="https://hyunjiunni.com/category/tax-refund/">세금·환급</a></li>
<li><a href="https://hyunjiunni.com/category/housing-plan/">주거·청약</a></li>
<li><a href="https://hyunjiunni.com/category/policy-benefit/">제도·복지</a></li>
</ul>
<!-- /wp:html -->
</div>
<!-- /wp:group -->

<!-- wp:heading {"level":2,"className":"hj-home-heading"} -->
<h2 class="wp-block-heading hj-home-heading">최신 칼럼</h2>
<!-- /wp:heading -->

<!-- wp:pattern {"slug":"twentytwentyfive/template-query-loop"} /-->
</main>
<!-- /wp:group -->

<!-- wp:template-part {"slug":"footer"} /-->
HOMEEOF
HOME_CONTENT=$(cat "$HOME_FILE")
rm -f "$HOME_FILE"
HOME_ID=$($WP post list --post_type=wp_template --name=home --field=ID --format=ids 2>/dev/null | head -1 || true)
if [ -n "$HOME_ID" ]; then
  $WP post update "$HOME_ID" --post_content="$HOME_CONTENT"
else
  HOME_ID=$($WP post create --post_type=wp_template --post_title='Home' --post_name='home' \
    --post_status=publish --post_content="$HOME_CONTENT" --porcelain)
fi
$WP post term set "$HOME_ID" wp_theme twentytwentyfive 2>/dev/null || true

echo "== 푸터 템플릿 =="
FOOTER_FILE=$(mktemp)
cat > "$FOOTER_FILE" << 'FOOTEREOF'
<!-- wp:group {"style":{"spacing":{"padding":{"top":"var:preset|spacing|60","bottom":"var:preset|spacing|50"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group" style="padding-top:var(--wp--preset--spacing--60);padding-bottom:var(--wp--preset--spacing--50)">
<!-- wp:group {"align":"wide","layout":{"type":"default"}} -->
<div class="wp-block-group alignwide">
<!-- wp:columns -->
<div class="wp-block-columns">
<!-- wp:column {"width":"100%"} -->
<div class="wp-block-column" style="flex-basis:100%">
<!-- wp:site-title {"level":2} /-->
<!-- wp:site-tagline /-->
</div>
<!-- /wp:column -->
</div>
<!-- /wp:columns -->
<!-- wp:group {"style":{"spacing":{"blockGap":"var:preset|spacing|40"}},"layout":{"type":"flex","flexWrap":"wrap","justifyContent":"space-between","verticalAlignment":"top"}} -->
<div class="wp-block-group">
<!-- wp:navigation {"ref":4,"overlayMenu":"never","layout":{"type":"flex","orientation":"vertical"}} /-->
<!-- wp:group {"layout":{"type":"flex","orientation":"vertical"}} -->
<div class="wp-block-group">
<!-- wp:paragraph -->
<p><a href="https://hyunjiunni.com/about/">소개</a></p>
<!-- /wp:paragraph -->
<!-- wp:paragraph -->
<p><a href="https://hyunjiunni.com/privacy/">개인정보 처리방침</a></p>
<!-- /wp:paragraph -->
</div>
<!-- /wp:group -->
</div>
<!-- /wp:group -->
<!-- wp:paragraph {"fontSize":"small"} -->
<p class="has-small-font-size">© 2026 현지언니 — 공식 자료 기반 생활금융 칼럼</p>
<!-- /wp:paragraph -->
</div>
<!-- /wp:group -->
</div>
<!-- /wp:group -->
FOOTEREOF
FOOTER_CONTENT=$(cat "$FOOTER_FILE")
rm -f "$FOOTER_FILE"
FOOTER_ID=$($WP post list --post_type=wp_template_part --name=footer --field=ID --format=ids 2>/dev/null | head -1 || true)
if [ -n "$FOOTER_ID" ]; then
  $WP post update "$FOOTER_ID" --post_content="$FOOTER_CONTENT"
else
  FOOTER_ID=$($WP post create --post_type=wp_template_part --post_title='Footer' --post_name='footer' \
    --post_status=publish --post_content="$FOOTER_CONTENT" --porcelain)
fi
$WP term create wp_theme twentytwentyfive --slug=twentytwentyfive 2>/dev/null || true
$WP term create wp_template_part_area footer --slug=footer 2>/dev/null || true
$WP post term set "$FOOTER_ID" wp_theme twentytwentyfive 2>/dev/null || true
$WP post term set "$FOOTER_ID" wp_template_part_area footer 2>/dev/null || true

echo "== rewrite flush =="
$WP rewrite flush

echo "== 완료 =="
$WP term list category --fields=term_id,name,slug,count

