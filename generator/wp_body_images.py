"""WP 본문 일러스트 삽입 (2026-07-17 사용자 지시: 본문 이미지 + 주제 어긋남 절대 금지).

정책:
  · 본문엔 '주제 맞춤 AI 일러스트'만 사용 — 스톡 실사진은 주제와 어긋난 전력이 있어
    (gov/info의 Pexels 폐기와 동일 판단) 쓰지 않는다.
  · 장면은 '주제 키워드 + 해당 소제목'에서 생성해 섹션 문맥과 일치시키고,
    무관 소품·배경은 illustration.py 장면 프롬프트에서 금지.
  · 위치는 소제목(h2) 바로 다음 '두괄식 첫 문단' 뒤 — 지식스니펫 문단이 이미지에 밀리지 않게.
  · 요약/FAQ/출처성 소제목은 제외. 실패는 전부 무시(발행을 막지 않는다).
"""
import logging
import re
from html import escape

logger = logging.getLogger("wp_body_images")

# 이미지가 어울리지 않는 소제목(부분일치) — 본문 '내용' 섹션에만 삽입
_SKIP_H2 = ("요약", "자주 묻는", "FAQ", "출처", "마무리", "총평", "체크리스트")


def _pick_targets(h2_matches: list, max_imgs: int) -> list:
    """삽입 대상 h2 선정 — 본문 중반(2번째, 있으면 4번째)에 분산 배치."""
    eligible = [m for m in h2_matches if not any(k in m.group(2) for k in _SKIP_H2)]
    if not eligible:
        return []
    if len(eligible) == 1:
        return eligible[:1]
    idxs = [1]
    if len(eligible) >= 4:
        idxs.append(3)
    elif len(eligible) >= 3:
        idxs.append(2)
    return [eligible[i] for i in idxs[:max_imgs]]


def add_body_illustrations(content_html: str, keyword: str, category: str,
                           api_key: str, slug: str = "", max_imgs: int = 2) -> str:
    """렌더된 content_html의 소제목 1~2곳 아래에 주제 맞춤 일러스트 <figure> 삽입.
    실패 시 원본 그대로 반환(best-effort)."""
    try:
        h2s = list(re.finditer(r'<h2 id="(sec-\d+)">([^<]+)</h2>', content_html))
        targets = _pick_targets(h2s, max_imgs)
        if not targets:
            logger.info("본문 일러스트: 대상 소제목 없음 — 생략")
            return content_html

        from poster.illustration import generate_editorial_illustration
        from poster.wp_publish import upload_media_info

        new_html = content_html
        inserted = 0
        for m in targets:
            sub = m.group(2).strip()
            # 장면 = 주제 + 소제목 문맥 (주제 어긋남 방지의 핵심)
            il = generate_editorial_illustration(f"{keyword} — {sub}", category, api_key)
            if not il:
                continue
            alt = f"{keyword} {sub} 일러스트"
            fname = f"illust-{slug or 'post'}-{m.group(1)}.png"  # ascii slug — 한글 파일명 헤더 오류 방지
            info = upload_media_info(il, fname, alt_text=alt)
            if not info or not info.get("source_url"):
                continue
            fig = (
                f'<figure class="wp-block-image size-large hj-body-illust">'
                f'<img src="{escape(info["source_url"])}" alt="{escape(alt)}" loading="lazy"/>'
                f"</figure>"
            )
            h2_html = m.group(0)
            seg = new_html.find(h2_html)
            if seg < 0:
                continue
            after = new_html[seg + len(h2_html):]
            pm = re.match(r"\s*<p>.*?</p>", after, flags=re.S)
            ins_at = seg + len(h2_html) + (pm.end() if pm else 0)
            new_html = new_html[:ins_at] + "\n" + fig + new_html[ins_at:]
            inserted += 1
            logger.info(f"본문 일러스트 삽입: '{sub[:20]}' 아래 (media id={info['id']})")
        logger.info(f"본문 일러스트 {inserted}/{len(targets)}곳 완료")
        return new_html
    except Exception as e:
        logger.warning(f"본문 일러스트 삽입 실패(원본 유지): {e}")
        return content_html
