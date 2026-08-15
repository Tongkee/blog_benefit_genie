# -*- coding: utf-8 -*-
"""네이버 블로그 글 삭제 — UI 경로 + **삭제 후 실검증** (2026-07-31 신설).

기존 scripts/delete_posts.py는 PostDelete.naver에 POST를 던지고 res.ok(HTTP 200)만
보고 성공으로 판정했다. 네이버는 실패해도 200에 본문으로 `msg='error! cause: code:...'`
를 돌려주기 때문에 **27건 전부 '삭제 성공' 로그를 남기고 하나도 안 지워졌다**.
(2026-07-30 인계의 '청약 중복 4건 삭제'도 같은 경로라 실제 삭제 여부 재확인 필요.)

여기서는 사람이 하는 것과 같은 경로로 지운다:
  본문 mainFrame의 `a._deletePost._param(<logNo>|...)` 클릭 → 확인 레이어/네이티브 confirm 수락
그리고 **매 건 삭제 후 글을 다시 조회해 사라졌는지 확인**한다. 확인 못 하면 실패로 센다.

사용: py -3 scripts/delete_posts_ui.py <delete_list.json> [--dry]
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from playwright.async_api import async_playwright  # noqa: E402

from scripts.delete_posts import _UA, _load_cookies  # noqa: E402

BLOG = os.environ.get("NAVER_BLOG_ID") or "hyunji_unni"


async def _still_alive(page, blog_id: str, post_id: str, box: list) -> bool:
    """글이 아직 살아 있으면 True.

    ★삭제된 글은 alert('게시물이 삭제되었거나 다른 페이지로 변경되었습니다.') 후
    블로그 루트로 리다이렉트된다. alert는 **DOM 텍스트가 아니라 dialog**라
    innerText 검사로는 절대 안 잡힌다 — 이걸 놓쳐 멀쩡히 지워진 글을
    '삭제 실패'로 오판했다(2026-07-31). 리다이렉트된 홈의 최신글 본문을
    글 본문으로 착각하는 함정도 같이 있었다.
    """
    box.clear()
    try:
        await page.goto(f"https://blog.naver.com/{blog_id}/{post_id}",
                        wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    await asyncio.sleep(1.6)
    msg = " ".join(box)
    if "삭제" in msg or "변경되었습니다" in msg:
        return False
    return post_id in page.url


async def delete_one(page, blog_id: str, post_id: str) -> bool:
    await page.goto(f"https://blog.naver.com/{blog_id}/{post_id}",
                    wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)
    f = page.frame(name="mainFrame")
    if not f:
        return False
    clicked = await f.evaluate(f"""() => {{
        const el = [...document.querySelectorAll('a')].find(a =>
            (a.className||'').includes('_deletePost') &&
            (a.className||'').includes('_param({post_id}|'));
        if (!el) return false;
        el.click();
        return true;
    }}""")
    if not clicked:
        return False
    await asyncio.sleep(2)
    # 확인 레이어(있으면) 수락 — '삭제' / '확인' 버튼
    for fr in page.frames:
        try:
            ok = await fr.evaluate("""() => {
                const cands = [...document.querySelectorAll('a,button')].filter(b => {
                    const t = (b.innerText||'').trim();
                    return (t === '삭제' || t === '확인') && (b.offsetWidth || b.offsetHeight);
                });
                const btn = cands.find(b => !(b.className||'').includes('_deletePost'));
                if (!btn) return false;
                btn.click();
                return true;
            }}""".replace("}}", "}"))
            if ok:
                break
        except Exception:
            continue
    await asyncio.sleep(2)
    return True


async def main():
    path = sys.argv[1]
    dry = "--dry" in sys.argv
    items = json.load(open(path, encoding="utf-8"))
    print(f"대상 {len(items)}건 (dry={dry})")

    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        ctx = await br.new_context(user_agent=_UA)
        if not await _load_cookies(ctx):
            print("쿠키 로드 실패 — 중단")
            return
        page = await ctx.new_page()
        box: list = []
        page.on("dialog", lambda d: (box.append(d.message),
                                     asyncio.ensure_future(d.accept())))

        done, failed = [], []
        for i, it in enumerate(items, 1):
            pid = it["logno"]
            if not await _still_alive(page, BLOG, pid, box):
                print(f"[{i}/{len(items)}] {pid} 이미 없음 — 건너뜀")
                done.append(pid)
                continue
            if dry:
                print(f"[{i}/{len(items)}] {pid} 살아있음(DRY, 삭제 안 함)")
                continue
            await delete_one(page, BLOG, pid)
            alive = await _still_alive(page, BLOG, pid, box)
            if alive:
                failed.append(pid)
                print(f"[{i}/{len(items)}] {pid} ✗ 삭제 실패(검증에서 여전히 살아있음)")
            else:
                done.append(pid)
                print(f"[{i}/{len(items)}] {pid} ✓ 삭제 확인")
        await br.close()

    print(f"\n삭제 확인 {len(done)}건 / 실패 {len(failed)}건")
    if failed:
        print("실패:", failed)
    json.dump({"deleted": done, "failed": failed},
              open(os.path.join(os.path.dirname(path), "delete_result.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)


asyncio.run(main())
