# -*- coding: utf-8 -*-
"""라이브 WP 기존글 결함 일괄 수리 (2026-07-29, 사용자 지시 '기존글 오류 다 수정').

배경: 07-29 전수 감사(docs/AUDIT_2026-07-29.md)에서 드러난 결함 중 생성기 수리는
'앞으로 나갈 글'에만 적용됨. 이미 라이브인 글은 그대로라 직접 수리한다.

수리 항목:
  ① 오해카드 반말 — <p class="hj-myth-q">에 인용부호가 없어 글쓴이 단언으로 읽힘
     → "…" 로 감싸 인용문으로 만듦(홈 세션이 생성기에 넣은 규칙과 동일한 결과).
     ※'오해: …?' 물음표형은 이미 정상 → 건너뜀(감사 오탐분).
  ② 본문 이미지 0장 — 별도 처리(--images, wp_body_images 재사용). 기본은 ①만.

같은 post ID에 PUT(슬러그·URL·대표이미지 유지, WP 리비전 남음).
DRY_RUN=1이면 변경 없이 진단만.

실행(자격 있는 환경 — EC2):
  DRY_RUN=1 python scripts/wp_repair_live.py --site hyunji
  python scripts/wp_repair_live.py --site hyunji
  python scripts/wp_repair_live.py --site tech
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

DRY = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True")

SITES = {
    # site key: (base url, user env, pw env, 기본 계정)
    "hyunji": ("https://hyunjiunni.com", "WP_USER", "WP_APP_PW", ""),
    "tech": (os.environ.get("TECH_WP_URL", "https://tech.hyunjiunni.com"),
             "TECH_WP_APP_USER", "TECH_WP_APP_PW", "hyungsu_admin"),
}

# 이미 인용/물음표로 처리된 것(정상) — 건드리지 않음
_OK_QUOTED = re.compile(r'^\s*[“"\'‘]|[?？]\s*$')
_MYTH_Q = re.compile(r'(<p class="hj-myth-q">)(.*?)(</p>)', re.S)


# 라이브 잔존 반말 — 생성기는 수리됐으나 기발행분에 남은 개별 표현(2026-07-29 감사 잔여분).
# 문맥 안전한 완전일치·경계 패턴만(오탐 방지). 프롬프트 예시 인용문 등은 대상 아님.
_BANMAL_FIX: list[tuple[re.Pattern, str]] = [
    # 청약 판정 라벨 — 프롬프트 하드코딩 반말(홈 세션이 생성기는 교체함)
    (re.compile(r"(현지언니 판단[^<]{0,12}?)해볼 만하다"), r"\1해볼 만해요"),
    (re.compile(r">해볼 만하다<"), ">해볼 만해요<"),
    # 테크 표 항목 서술형 반말(항목: 설명 꼴)
    (re.compile(r"넓게 볼수록 놓치는 것이 적다(?![.\w])"), "넓게 볼수록 놓치는 부분이 적어요"),
]


def fix_banmal_leftovers(html: str) -> tuple[str, int]:
    """라이브 잔존 반말 표현 치환. (수정본, 변경 건수)"""
    n = 0
    for rx, repl in _BANMAL_FIX:
        html, k = rx.subn(repl, html)
        n += k
    return html, n


def fix_myth_quotes(html: str) -> tuple[str, int]:
    """오해카드 질문문을 인용부호로 감싼다. (수정본, 변경 건수)"""
    n = 0

    def _rep(m):
        nonlocal n
        head, inner, tail = m.group(1), m.group(2).strip(), m.group(3)
        plain = re.sub(r"<[^>]+>", "", inner).strip()
        if not plain or _OK_QUOTED.search(plain):
            return m.group(0)          # 이미 정상(인용·물음표) → 유지
        n += 1
        return f'{head}“{inner}”{tail}'

    return _MYTH_Q.sub(_rep, html), n


def backfill_images(post: dict, base: str, auth) -> tuple[str, int]:
    """본문 이미지 0장인 기존글에 섹션 일러스트 주입(테크 WP 전용).
    wp_tech_post._inject_body_images를 그대로 재사용 — 신규 발행과 동일한 결과물."""
    content = post.get("content", {})
    raw = content.get("raw") or content.get("rendered", "")
    if "<img" in raw or "<figure" in raw:
        return raw, 0                     # 이미 이미지 있음
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        return raw, 0
    try:
        from scripts.wp_tech_post import _inject_body_images
    except Exception as e:
        print(f"    (이미지 주입 모듈 불가: {e})")
        return raw, 0
    # topic: 제목·슬러그로 최소 구성(생성기는 keyword만 사용)
    title = re.sub(r"<[^>]+>", "", (post.get("title") or {}).get("raw", "")
                   or (post.get("title") or {}).get("rendered", "")).strip()
    topic = {"keyword": title or post.get("slug", ""), "category": ""}
    new = _inject_body_images(raw, topic, api_key, post.get("slug", ""))
    return new, (1 if new != raw else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", choices=list(SITES), default="hyunji")
    ap.add_argument("--per-page", type=int, default=50)
    ap.add_argument("--images", action="store_true",
                    help="본문 이미지 0장 글에 섹션 일러스트 백필(테크 WP, Gemini 필요)")
    ap.add_argument("--limit", type=int, default=0, help="이미지 백필 최대 글 수(0=제한없음)")
    a = ap.parse_args()

    base, uenv, penv, udef = SITES[a.site]
    user = os.environ.get(uenv, udef)
    pw = os.environ.get(penv, "")
    if not pw:
        print(f"[중단] {penv} 없음 — 자격 있는 환경(EC2)에서 실행하세요.")
        return 1
    auth = (user, pw)

    fixed = scanned = 0
    page = 1
    while True:
        r = requests.get(f"{base}/wp-json/wp/v2/posts", auth=auth, timeout=60,
                         params={"per_page": a.per_page, "page": page, "context": "edit",
                                 "status": "publish", "_fields": "id,slug,content,title"})
        if r.status_code != 200:
            print(f"목록 조회 실패 p{page}: {r.status_code} {r.text[:150]}")
            break
        batch = r.json()
        if not batch:
            break
        for p in batch:
            scanned += 1
            content = p.get("content", {})
            raw = content.get("raw") or content.get("rendered", "")
            new, n = fix_myth_quotes(raw)
            new, n2 = fix_banmal_leftovers(new)
            n3 = 0
            if a.images and (not a.limit or fixed < a.limit):
                img_html, n3 = backfill_images({**p, "content": {"raw": new}}, base, auth)
                if n3:
                    new = img_html
                    print(f"  [{p['slug'][:44]}] 본문 이미지 백필{' (DRY)' if DRY else ''}")
            if not (n or n2 or n3):
                continue
            parts = []
            if n3 and not (n or n2):
                parts.append("이미지 백필")
            if n:
                parts.append(f"오해카드 {n}건 인용부호")
            if n2:
                parts.append(f"잔존 반말 {n2}건 존댓말화")
            print(f"  [{p['slug'][:44]}] {' + '.join(parts)}{' (DRY)' if DRY else ''}")
            if DRY:
                fixed += 1
                continue
            u = requests.post(f"{base}/wp-json/wp/v2/posts/{p['id']}", auth=auth,
                              timeout=60, json={"content": new})
            if u.status_code in (200, 201):
                fixed += 1
                print("     ✅ 업데이트 완료")
            else:
                print(f"     ❌ 실패 {u.status_code}: {u.text[:120]}")
        if len(batch) < a.per_page:
            break
        page += 1

    print(f"\n[{a.site}] 스캔 {scanned}글 · 수리 {fixed}글{' (DRY_RUN)' if DRY else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
