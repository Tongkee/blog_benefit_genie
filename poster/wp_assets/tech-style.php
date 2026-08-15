<?php
/**
 * 형수의테크공장(tech.hyunjiunni.com) 공용 스타일 — mu-plugin.
 * 2026-07-22: 홈 hj-* 디자인 이식 + 사이드바 폰트 축소·최신댓글 숨김·광고 슬롯.
 * 서버 배포: /var/www/tech/wp-content/mu-plugins/tech-style.php (repo는 백업/버전관리용).
 */
add_action('wp_head', function () {
    ?>
    <style id="tech-style">
    :root{
      --tk-accent:#2a78d6; --tk-accent-deep:#1c5cab; --tk-accent-bg:#eef4fb;
      --tk-line:#e5e8eb; --tk-muted:#5b6570; --tk-fg:#111827;
    }
    /* ── 홈 히어로 ── */
    .hj-hero{background:var(--tk-accent-bg);border:1px solid var(--tk-line);border-radius:14px;padding:2.4rem 1.6rem 2rem;margin:0 0 .5rem;}
    .hj-hero h1{font-size:clamp(1.7rem,4vw,2.2rem);font-weight:800;color:var(--tk-accent-deep);margin:0 0 .5rem;line-height:1.25;letter-spacing:-.02em;}
    .hj-hero-tagline{font-size:1.02rem;color:var(--tk-muted);margin:0 0 1.3rem;line-height:1.6;max-width:42rem;}
    .hj-hero-chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:0;padding:0;list-style:none;}
    .hj-hero-chips li{margin:0;padding:0;list-style:none;}
    .hj-hero-chips a{display:inline-block;padding:.4rem .95rem;border-radius:999px;background:#fff;border:1px solid var(--tk-accent);color:var(--tk-accent);font-size:.86rem;font-weight:600;text-decoration:none;line-height:1.4;transition:transform .15s ease,background .15s ease;}
    .hj-hero-chips a:hover{background:var(--tk-accent);color:#fff;transform:translateY(-2px);}
    /* ── 섹션 헤딩 ── */
    .hj-home-heading{margin-top:2.2rem;margin-bottom:.5rem;font-weight:800;font-size:1.3rem;color:var(--tk-fg);border-left:4px solid var(--tk-accent);padding-left:.6rem;line-height:1.3;}
    .hj-home-desc{color:var(--tk-muted);font-size:.92em;margin:-2px 0 14px;}
    .hj-home-desc a{color:var(--tk-accent);text-decoration:none;font-weight:600;}
    /* ── 지금 많이 보는 글(랭킹) ── */
    .hj-popular:has(ul:empty){display:none;}
    .hj-popular ul{list-style:none;padding:0;margin:0;counter-reset:hj-rank;}
    .hj-popular li{counter-increment:hj-rank;padding:12px 2px;border-bottom:1px solid var(--tk-line);font-weight:600;display:flex;align-items:center;}
    .hj-popular li::before{content:counter(hj-rank);display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;margin-right:12px;border-radius:8px;background:var(--tk-accent);color:#fff;font-size:.82em;flex:none;}
    .hj-popular li a{text-decoration:none;color:inherit;}
    .hj-popular li a:hover{color:var(--tk-accent);}
    /* ── 최신/허브 글 카드 그리드 ── */
    .wp-block-latest-posts.is-grid{gap:16px;}
    .wp-block-latest-posts.is-grid li{border:1px solid var(--tk-line);border-radius:12px;overflow:hidden;background:#fff;transition:box-shadow .18s ease,transform .18s ease;}
    .wp-block-latest-posts.is-grid li:hover{box-shadow:0 6px 20px rgba(17,24,39,.09);transform:translateY(-2px);}
    .wp-block-latest-posts__featured-image img{width:100%;aspect-ratio:1200/630;object-fit:cover;display:block;}
    .wp-block-latest-posts.is-grid li a.wp-block-latest-posts__post-title{display:block;padding:12px 14px 4px;font-weight:700;line-height:1.4;color:var(--tk-fg);text-decoration:none;}
    .wp-block-latest-posts.is-grid li a.wp-block-latest-posts__post-title:hover{color:var(--tk-accent);}
    .wp-block-latest-posts__post-date{padding:0 14px 12px;color:var(--tk-muted);font-size:.82em;}
    /* ── 소개 ── */
    .hj-about-strip{margin-top:40px;padding:20px 24px;background:#f6f8fa;border-radius:12px;font-size:.93em;color:var(--tk-muted);}
    /* ── 사이드바: 폰트 축소 + sticky(광고 상시 노출) ── */
    @media(min-width:1025px){#secondary .sidebar-inner-wrap{position:sticky;top:40px;}}
    #secondary{font-size:.9rem;line-height:1.55;}
    #secondary .widget-title,#secondary .widget h2,#secondary h2.widget-title{font-size:1rem;margin-bottom:.6rem;}
    #secondary .widget{margin-bottom:1.6rem;}
    #secondary li{margin-bottom:.3rem;}
    /* 최신 댓글 위젯 숨김(사용자 요청 2026-07-22) */
    #secondary .widget_recent_comments{display:none!important;}
    /* 광고 슬롯 자리 — 인아티클/사이드바 공통 */
    .hj-ad-slot,.ad-slot,.adsbygoogle{display:block;margin:24px auto;min-height:100px;text-align:center;clear:both;}
    /* 홈 상단 '홈' 페이지타이틀 배너 숨김(사용자 요청 2026-07-22) */
    body.home .entry-hero,body.home .page-hero-section{display:none;}
    /* 형광펜 음영 강조 — {{...}} → mark.hj-hl (2026-07-22 변환 구현) */
    .entry-content mark.hj-hl,.entry-content .hj-hl{
      background:linear-gradient(180deg,transparent 55%,#fff0a6 55%);
      color:inherit;font-weight:600;padding:0 2px;border-radius:2px;
    }
    </style>
    <?php
});
