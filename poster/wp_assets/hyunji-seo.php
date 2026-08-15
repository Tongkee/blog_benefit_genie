<?php
/**
 * Plugin Name: Hyunji SEO (mu-plugin)
 * Description: 메타 description·Open Graph·robots·XML sitemap ping — Rank Math 없이 기본 SEO.
 * 배포: /var/www/html/wp-content/mu-plugins/hyunji-seo.php
 */
if (!defined('ABSPATH')) {
    exit;
}

define('HYUNJI_SITE_DESC', '2030 신혼·1인가구를 위한 정부지원·금융·세금·보험·주거·주식 심층 정보 — 현지언니');

/** head: description + OG + Twitter */
add_action('wp_head', function () {
    if (is_singular()) {
        global $post;
        $title = wp_get_document_title();
        $desc = has_excerpt($post) ? wp_strip_all_tags(get_the_excerpt($post)) : HYUNJI_SITE_DESC;
        $desc = mb_substr(trim($desc), 0, 160);
        $url = get_permalink($post);
        $img = get_site_icon_url(512);
        if (!$img) {
            $img = home_url('/wp-content/mu-plugins/hyunji-favicon.png');
        }
    } else {
        $title = get_bloginfo('name') . ' — ' . get_bloginfo('description');
        $desc = HYUNJI_SITE_DESC;
        $url = home_url('/');
        $img = get_site_icon_url(512) ?: home_url('/wp-content/mu-plugins/hyunji-favicon.png');
    }
    echo '<meta name="description" content="' . esc_attr($desc) . '">' . "\n";
    echo '<meta property="og:type" content="' . (is_singular('post') ? 'article' : 'website') . '">' . "\n";
    echo '<meta property="og:title" content="' . esc_attr($title) . '">' . "\n";
    echo '<meta property="og:description" content="' . esc_attr($desc) . '">' . "\n";
    echo '<meta property="og:url" content="' . esc_url($url) . '">' . "\n";
    echo '<meta property="og:site_name" content="현지언니">' . "\n";
    echo '<meta property="og:locale" content="ko_KR">' . "\n";
    if ($img) {
        echo '<meta property="og:image" content="' . esc_url($img) . '">' . "\n";
    }
    echo '<meta name="twitter:card" content="summary">' . "\n";
    echo '<meta name="twitter:title" content="' . esc_attr($title) . '">' . "\n";
    echo '<meta name="twitter:description" content="' . esc_attr($desc) . '">' . "\n";
    $gsc = get_option('hyunji_gsc_verification', '');
    if ($gsc) {
        echo '<meta name="google-site-verification" content="' . esc_attr($gsc) . '">' . "\n";
    }
}, 5);

/** robots.txt — WP 기본 sitemap 안내 */
add_filter('robots_txt', function ($output, $public) {
    if (!$public) {
        return $output;
    }
    $sitemap = home_url('/wp-sitemap.xml');
    $extra = "Sitemap: {$sitemap}\n";
    if (strpos($output, 'Sitemap:') === false) {
        $output .= "\n" . $extra;
    }
    return $output;
}, 10, 2);

/** 발행·수정 시 sitemap ping (best-effort) */
add_action('transition_post_status', function ($new, $old, $post) {
    if ($new !== 'publish' || $post->post_type !== 'post') {
        return;
    }
    wp_remote_get(home_url('/wp-sitemap.xml'), ['timeout' => 5, 'blocking' => false]);
}, 10, 3);
