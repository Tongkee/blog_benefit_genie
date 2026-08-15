# -*- coding: utf-8 -*-
"""네이버 블로그 댓글 자동 응답 — 스티커 1개 (2026-07-29 사용자 지시, 무지개로그 벤치마킹).

이웃 소통 신호(댓글 응답률)를 자동 유지한다. 벤치마크(무지개로그)처럼 텍스트 대댓글 대신
**스티커 하나만** 남긴다 — 자연스럽고, 생성 텍스트 품질 리스크가 없다.

동작:
  최근 글 N개(모바일 블로그 홈 파싱) → 각 글 댓글 목록 → 블로그주인 답글이 아직 없는
  최상위 댓글에 답글 스티커 등록. 이력 파일로 멱등(재실행 시 중복 방지).

실행:
  python -m scripts.naver_comment_reply              # 기본(현지언니 계정)
  DRY_RUN=true ...                                   # 등록 직전까지만(셀렉터 진단용)
  REPLY_BLOG_ID/REPLY_COOKIES_ENV 로 계정 전환 가능(형수: TECH_NAVER_COOKIES)

필요 키: NAVER_COOKIES(또는 REPLY_COOKIES_ENV가 가리키는 시크릿), NAVER_BLOG_ID
"""
import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR, NAVER_BLOG_ID, NAVER_COOKIES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("naver_comment_reply")

KST = timezone(timedelta(hours=9))
BLOG_ID = os.getenv("REPLY_BLOG_ID", "") or NAVER_BLOG_ID
COOKIES = os.getenv(os.getenv("REPLY_COOKIES_ENV", ""), "") or NAVER_COOKIES
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MAX_POSTS = int(os.getenv("REPLY_MAX_POSTS", "8"))
MAX_REPLIES = int(os.getenv("REPLY_MAX_PER_RUN", "10"))
STATE_PATH = os.path.join(DATA_DIR, "comment_reply_history.json")


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


async def _delay(a=800, b=1800):
    await asyncio.sleep(random.uniform(a / 1000, b / 1000))


async def _recent_post_ids(page) -> list[str]:
    """모바일 블로그 홈에서 최근 글 번호 수집(트랙 무관 전 글 대상)."""
    await page.goto(f"https://m.blog.naver.com/{BLOG_ID}", timeout=30000)
    await _delay(1200, 2000)
    hrefs = await page.eval_on_selector_all(
        f"a[href*='/{BLOG_ID}/']", "els => els.map(e => e.getAttribute('href'))")
    ids, seen = [], set()
    for h in hrefs or []:
        m = re.search(rf"/{re.escape(BLOG_ID)}/(\d{{9,}})", h or "")
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ids.append(m.group(1))
    return ids[:MAX_POSTS]


async def _dump_buttons(page, tag: str):
    """실패 진단용 — 보이는 버튼 후보를 로그로(다음 셀렉터 iteration 단축)."""
    try:
        btns = await page.evaluate("""() =>
            [...document.querySelectorAll('a,button,[role=button]')]
              .filter(b => b.offsetParent && /답글|스티커|등록|sticker|reply/i.test(
                (b.getAttribute('aria-label')||'')+(b.className||'')+(b.textContent||'')))
              .map(b => ({t:(b.textContent||'').trim().slice(0,12), al:b.getAttribute('aria-label'),
                          cls:(b.className||'').toString().slice(0,50)})).slice(0,15)""")
        logger.info(f"[진단 {tag}] {btns}")
    except Exception:
        pass


async def _click_first(page, sels: list[str], timeout=1500) -> bool:
    for sel in sels:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=600):
                await loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def _reply_sticker_to_comment(page, item) -> bool:
    """댓글 항목(item locator)에 답글 스티커 등록. 실패 시 False(다음 댓글 진행)."""
    # 1) 답글 버튼
    try:
        rb = item.locator("a:has-text('답글'), button:has-text('답글')").first
        if not await rb.count():
            return False
        await rb.click(timeout=2000)
    except Exception:
        return False
    await _delay(700, 1300)
    # 2) 스티커 버튼(작성 툴바) — 네이버 댓글 에디터 공통 UI
    ok = await _click_first(page, [
        "button[class*='sticker']", "a[class*='sticker']",
        "button[aria-label*='스티커']", "a[aria-label*='스티커']",
        ".u_cbox_btn_sticker", "[class*='btn_sticker']",
    ])
    if not ok:
        await _dump_buttons(page, "스티커버튼")
        await page.keyboard.press("Escape")
        return False
    await _delay(800, 1400)
    # 3) 스티커 팩 첫 팩에서 랜덤 스티커 선택
    picked = False
    for sel in (".u_cbox_sticker_section img", "[class*='sticker_list'] img",
                "[class*='sticker'] li img", "[class*='sticker_item'] img"):
        try:
            imgs = page.locator(sel)
            n = await imgs.count()
            if n:
                await imgs.nth(random.randrange(min(n, 8))).click(timeout=2000)
                picked = True
                break
        except Exception:
            continue
    if not picked:
        await _dump_buttons(page, "스티커팩")
        await page.keyboard.press("Escape")
        return False
    await _delay(600, 1200)
    if DRY_RUN:
        logger.info("[DRY_RUN] 스티커 선택까지 확인 — 등록 생략")
        await page.keyboard.press("Escape")
        return True
    # 4) 등록
    ok = await _click_first(page, [
        ".u_cbox_btn_upload", "button:has-text('등록')", "a:has-text('등록')",
        "[class*='btn_register']", "[class*='btn_upload']",
    ], timeout=2500)
    if not ok:
        await _dump_buttons(page, "등록버튼")
        await page.keyboard.press("Escape")
        return False
    await _delay(1000, 1800)
    return True


async def run() -> int:
    if not BLOG_ID or not COOKIES:
        logger.error("NAVER_BLOG_ID / NAVER_COOKIES 필요 — 종료")
        return 1
    from playwright.async_api import async_playwright
    from poster.naver_blog import _load_cookies
    state = _load_state()
    replied_total = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
            viewport={"width": 390, "height": 844})
        if not await _load_cookies(ctx, COOKIES):
            logger.error("쿠키 로드 실패 — 종료")
            await browser.close()
            return 1
        page = await ctx.new_page()
        post_ids = await _recent_post_ids(page)
        logger.info(f"대상 글 {len(post_ids)}개 (blog={BLOG_ID})")
        for log_no in post_ids:
            if replied_total >= MAX_REPLIES:
                break
            url = f"https://m.blog.naver.com/CommentList.naver?blogId={BLOG_ID}&logNo={log_no}"
            try:
                await page.goto(url, timeout=30000)
            except Exception as e:
                logger.info(f"{log_no} 댓글 페이지 실패(스킵): {e.__class__.__name__}")
                continue
            await _delay(1200, 2000)
            items = page.locator(".u_cbox_comment, [class*='comment_item'], li[class*='u_cbox']")
            try:
                n = await items.count()
            except Exception:
                n = 0
            if not n:
                continue
            done_key = f"{log_no}"
            done_set = set(state.get(done_key, []))
            for i in range(n):
                if replied_total >= MAX_REPLIES:
                    break
                item = items.nth(i)
                try:
                    txt = (await item.inner_text())[:400]
                except Exception:
                    continue
                # 이미 블로그주인 답글이 달린 댓글/대댓글 자체는 스킵
                # ★2026-07-31: 본문이 `pass`여서 이 가드가 **아무 일도 하지 않았다**.
                # 그 결과 봇이 자기 답글에 또 답글을 다는 일이 생겼다(224350244455에서
                # 외부 댓글 1건에 '현지언니' 답글 3건, 그중 2건이 '@현지언니').
                # 유일한 사람-접점에서 '무인 자동 블로그' 신호를 내보내던 결함.
                if "블로그주인" in txt or ("답글쓰기" not in txt and "답글" not in txt):
                    continue
                # 작성자·본문 앞부분으로 멱등 키 구성(댓글 고유 id를 UI에서 못 얻는 경우 대비)
                ck = re.sub(r"\s+", " ", txt)[:60]
                if ck in done_set:
                    continue
                # 다음 형제에 주인 답글이 이미 있으면 스킵 — inner_text에 '블로그주인' 배지 포함됨
                try:
                    nxt = items.nth(i + 1) if i + 1 < n else None
                    if nxt and "블로그주인" in (await nxt.inner_text())[:200]:
                        done_set.add(ck)
                        continue
                except Exception:
                    pass
                if await _reply_sticker_to_comment(page, item):
                    replied_total += 1
                    done_set.add(ck)
                    logger.info(f"스티커 답글 등록: {log_no} — {ck[:24]!r}")
                    await _delay(2000, 4500)
            state[done_key] = sorted(done_set)[-60:]
        await browser.close()
    if not DRY_RUN:
        _save_state(state)
    logger.info(f"완료 — 이번 실행 스티커 답글 {replied_total}건{' [DRY_RUN]' if DRY_RUN else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
