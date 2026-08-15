"""WP 본문 HTML 잔여 마크다운 보정 (2026-07-21 형수테크 WP 리터럴 노출 버그 대응).

배경: wp_tech_post 의 LLM 프롬프트는 <h2>/<h3> 구조만 HTML로 지시하고 강조·목록 형식은
지시하지 않아, LLM이 본문 강조를 **bold**, 목록을 '*   ' 마크다운으로 내는 경우가 있었다.
변환 단계가 없어 그대로 발행 → WordPress wpautop이 <p>로만 감싸 리터럴 '**'·'*'가 그대로
노출됐다(hipass 62개·chatgpt 48개). ott/windows11은 LLM이 우연히 HTML로 내서 정상이었다.

`normalize_residual_md` 는 이 잔여 마크다운(**, 줄머리 '* '/'- ')을 <strong>·<ul><li>로 변환한다.
이미 HTML이면 무영향(멱등) — 정상 글에 돌려도 안전.
"""
from __future__ import annotations

import re

_BOLD = re.compile(r"\*\*(?!\s)([^*\n]+?)\*\*")
_BULLET = re.compile(r"^[\*\-]\s+(.+)$")
_TRAIL_BR = re.compile(r"(?:<br\s*/?>)+\s*$")
# 소제목 화이트리스트: h4~h6(여는/닫는) → h3 강등. 여는 그룹1=선택적 '/', 그룹2=속성.
_HEADING_DEMOTE = re.compile(r"<(/?)h[4-6]\b([^>]*)>")


def normalize_residual_md(html: str) -> str:
    """LLM이 낸 잔여 마크다운(**강조**, 줄머리 불릿)을 HTML로 변환. 멱등.

    발행 payload(wpautop 전 raw 본문)를 가정. 이미 발행된 글은 rendered_to_raw로 환원 후 전달.
    """
    if not html:
        return html
    # 0) 소제목 화이트리스트 강제: 프롬프트 허용은 h2/h3뿐인데 LLM이 h4~h6로 과분할하는 경우가
    #    있어(2026-07-23 '자동차 배터리' 26개·h4 다수) h4↓를 h3로 강등. 이미 h2/h3면 무영향.
    html = _HEADING_DEMOTE.sub(r"<\1h3\2>", html)
    # 1) 볼드: **text** → <strong>text</strong> (개행/별표 미포함, 비탐욕)
    html = _BOLD.sub(r"<strong>\1</strong>", html)
    # 1-1) 음영 강조: {{문장}} → 형광펜 <mark> (프롬프트만 있고 변환 미구현이던 버그 수정, 2026-07-22)
    html = re.sub(r"\{\{\s*(.+?)\s*\}\}", r'<mark class="hj-hl">\1</mark>', html, flags=re.DOTALL)
    # 2) 줄머리 불릿('* ', '- ', '*   ') 연속행 → <ul><li> 그룹
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            items = "".join("<li>%s</li>" % _TRAIL_BR.sub("", x).strip() for x in buf)
            out.append("<ul>%s</ul>" % items)
            buf.clear()

    for ln in html.split("\n"):
        s = ln.strip()
        m = _BULLET.match(s)
        if m:
            buf.append(m.group(1))
        elif not s and buf:
            # 리스트 도중 빈 줄 → 그룹 유지(다음도 불릿이면 이어붙임)
            continue
        else:
            flush()
            out.append(ln)
    flush()
    return "\n".join(out)


def rendered_to_raw(rendered: str) -> str:
    """이미 발행된 content.rendered(wpautop 적용됨)를 줄 단위 판정 가능한 raw로 환원.

    <br> → 개행, </p><p> → 빈 줄, 나머지 <p> 제거. PUT 업데이트 시 WP가 wpautop 재적용.
    """
    c = re.sub(r"<br\s*/?>", "\n", rendered)
    c = re.sub(r"</p>\s*<p[^>]*>", "\n\n", c)
    c = re.sub(r"</?p[^>]*>", "\n", c)
    return c


def has_residual_md(rendered: str) -> bool:
    """content.rendered 에 미변환 마크다운(리터럴 '**' 또는 줄머리 '* ')이 있는지."""
    if "**" in rendered:
        return True
    raw = rendered_to_raw(rendered)
    return any(_BULLET.match(ln.strip()) for ln in raw.split("\n"))
