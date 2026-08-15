# -*- coding: utf-8 -*-
"""글 존재 여부 실검증 — 삭제된 글은 alert + 블로그 홈 리다이렉트로 판정.

★판정 근거(2026-07-31 실측): 삭제된 글 URL을 열면 네이버가
  alert('게시물이 삭제되었거나 다른 페이지로 변경되었습니다.') 를 띄우고
  블로그 루트로 리다이렉트한다. alert는 DOM 텍스트가 아니라 dialog라
  innerText 검사로는 절대 안 잡힌다(이걸 놓쳐 '삭제 실패'로 오판했다).
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from playwright.async_api import async_playwright  # noqa: E402

from scripts.delete_posts import _UA, _load_cookies  # noqa: E402

BLOG = "benefit_genie"


async def check(page, box, post_id):
    box.clear()
    try:
        await page.goto(f"https://blog.naver.com/{BLOG}/{post_id}",
                        wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await asyncio.sleep(1.6)
    msg = " ".join(box)
    if "삭제" in msg or "변경되었습니다" in msg:
        return "DELETED"
    url = page.url.rstrip("/")
    if url.endswith(BLOG) or "logNo" not in url and post_id not in url:
        return "DELETED"          # 글 URL을 유지 못하고 홈으로 튕김
    return "ALIVE"


async def main():
    ids = json.load(open(sys.argv[1], encoding="utf-8"))
    if isinstance(ids[0], dict):
        ids = [(x["logno"], x.get("title", "")[:40]) for x in ids]
    else:
        ids = [(x, "") for x in ids]
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        ctx = await br.new_context(user_agent=_UA)
        await _load_cookies(ctx)
        page = await ctx.new_page()
        box = []
        page.on("dialog", lambda d: (box.append(d.message),
                                     asyncio.ensure_future(d.accept())))
        alive, gone = [], []
        for pid, title in ids:
            st = await check(page, box, pid)
            (gone if st == "DELETED" else alive).append(pid)
            print(f"  {pid} {st:8s} {title}")
        await br.close()
    print(f"\n삭제됨 {len(gone)} / 살아있음 {len(alive)}")
    if alive:
        print("아직 살아있는 글:", alive)


asyncio.run(main())
