<?php
/**
 * 게시글 조회수 표시 — Koko Analytics 집계(post_totals) 기반. mu-plugin.
 * 2026-07-22 사용자 요청. 방어적(테이블 없거나 0이면 아무것도 안 함 → 사이트 무영향).
 * 배포: /var/www/html/wp-content/mu-plugins/ 및 /var/www/tech/wp-content/mu-plugins/
 */
add_filter('the_content', function ($content) {
    if (!is_singular('post') || !in_the_loop() || !is_main_query()) {
        return $content;
    }
    global $wpdb;
    $table = $wpdb->prefix . 'koko_analytics_post_totals';
    $views = 0;
    try {
        $views = (int) $wpdb->get_var(
            $wpdb->prepare("SELECT SUM(pageviews) FROM `{$table}` WHERE id = %d", get_the_ID())
        );
    } catch (\Throwable $e) {
        $views = 0;
    }
    if ($views < 1) {
        return $content;
    }
    $badge = '<p class="hj-viewcount" style="color:#8a8f98;font-size:.9em;margin:0 0 14px;display:flex;align-items:center;gap:5px">'
           . '<span aria-hidden="true">👁</span> 조회 ' . number_format($views) . '회</p>';
    return $badge . $content;
});
