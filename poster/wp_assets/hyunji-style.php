<?php
/**
 * Plugin Name: Hyunji Style (mu-plugin)
 * Description: 심층분석 컴포넌트(.hj-*) 스타일 로드 — 테마 독립. 원본은 repo poster/wp_assets/.
 * 배포 위치: /var/www/html/wp-content/mu-plugins/ (hyunji-style.css와 함께)
 */
add_action('wp_enqueue_scripts', function () {
    // 한글 웹폰트 Pretendard (dynamic subset — 필요한 글리프만 로드)
    wp_enqueue_style(
        'pretendard',
        'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css',
        [],
        '1.3.9'
    );
    $css = WPMU_PLUGIN_DIR . '/hyunji-style.css';
    if (file_exists($css)) {
        wp_enqueue_style(
            'hyunji-style',
            WPMU_PLUGIN_URL . '/hyunji-style.css',
            ['pretendard'],
            (string) filemtime($css)  // 파일 변경 시 캐시 자동 무효화
        );
    }
});
