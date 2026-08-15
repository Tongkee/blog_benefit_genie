"""
네이버 블로그 포스트 삭제 스크립트 (로컬 실행용)
사용법:
  python scripts/delete_posts.py                  # post_history.json의 모든 포스트 삭제
  python scripts/delete_posts.py --url URL        # 특정 URL만 삭제
  python scripts/delete_posts.py --all-history    # 이력 파일도 초기화
"""
import asyncio
import json
import logging
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright

from config import NAVER_ID, NAVER_PW, NAVER_COOKIES, NAVER_BLOG_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("delete_posts")

COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")
HISTORY_PATH = os.path.join(ROOT, "data", "post_history.json")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _extract_post_id(url: str) -> str | None:
    m = re.search(r"/(\d{9,})", url)
    return m.group(1) if m else None


def _get_posted_urls() -> list[str]:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)
    urls = [h["post_url"] for h in history if h.get("status") == "posted" and h.get("post_url")]
    return urls


async def _load_cookies(ctx):
    raw = None
    if NAVER_COOKIES and NAVER_COOKIES.strip():
        try:
            raw = json.loads(NAVER_COOKIES.strip())
        except Exception:
            pass
    if raw is None and os.path.exists(COOKIE_PATH):
        with open(COOKIE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    if not raw:
        return False
    clean = []
    for c in raw:
        entry = {k: c[k] for k in ("name", "value", "domain", "path") if k in c}
        for opt in ("expires", "httpOnly", "secure", "sameSite"):
            if opt in c and c[opt] != -1:
                entry[opt] = c[opt]
        clean.append(entry)
    await ctx.add_cookies(clean)
    return True


async def delete_post(page, blog_id: str, post_id: str) -> bool:
    """⚠️ 사용 금지 — 삭제되지 않는데 '성공'을 반환한다 (2026-07-31 실측).

    PostDelete.naver는 실패해도 HTTP 200에 본문으로
      `var msg = 'error!\\ncause : code: ...'`
    를 돌려준다. 아래 코드는 `res.ok`(=200)만 보므로 **항상 성공으로 판정**한다.
    2026-07-31에 이 함수로 27건을 지웠다고 로그를 남겼으나 실제로는 0건이 지워졌다.
    2026-07-13 '생애최초' 삭제 1건도 같은 이유로 실패해 있었다(이력만 deleted).

    → 실제 삭제는 **scripts/delete_posts_ui.py** 를 쓸 것. 본문의 삭제 UI를 클릭하고
      매 건 재조회로 검증한다.
    """
    manage_url = f"https://blog.naver.com/{blog_id}/{post_id}"
    logger.info(f"포스트 접근: {manage_url}")
    await page.goto(manage_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)

    # 삭제 API 직접 호출 (Naver 블로그 내부 API)
    try:
        result = await page.evaluate(f"""
            async () => {{
                const res = await fetch('https://blog.naver.com/PostDelete.naver', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                    body: 'blogId={blog_id}&logNo={post_id}&password=',
                    credentials: 'include'
                }});
                return {{ status: res.status, ok: res.ok }};
            }}
        """)
        if result.get("ok"):
            logger.info(f"✓ 삭제 성공: {post_id}")
            return True
        else:
            logger.warning(f"API 삭제 실패 (status={result.get('status')}) — UI 시도")
    except Exception as e:
        logger.warning(f"API 삭제 예외: {e} — UI 시도")

    # UI 기반 삭제 fallback
    try:
        await page.goto(
            f"https://blog.naver.com/PostList.naver?blogId={blog_id}",
            wait_until="domcontentloaded", timeout=20000
        )
        await asyncio.sleep(1)
        # 삭제 버튼 탐색
        deleted = await page.evaluate(f"""
            async () => {{
                // 글 관리 페이지에서 특정 logNo 삭제
                const res = await fetch('/PostDeleteConfirm.naver?blogId={blog_id}&logNo={post_id}', {{
                    method: 'POST', credentials: 'include'
                }});
                return res.ok;
            }}
        """)
        if deleted:
            logger.info(f"✓ UI 삭제 성공: {post_id}")
            return True
    except Exception as e:
        logger.warning(f"UI 삭제 실패: {e}")

    return False


async def main(target_urls: list[str] | None = None, clear_history: bool = False):
    blog_id = NAVER_BLOG_ID or NAVER_ID

    if target_urls is None:
        target_urls = _get_posted_urls()
        if not target_urls:
            logger.info("삭제할 포스트 없음 (post_history.json에 posted 항목 없음)")
            return

    logger.info(f"삭제 대상: {len(target_urls)}개")
    for u in target_urls:
        logger.info(f"  {u}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # 로컬 실행 — 화면 보이게
        ctx = await browser.new_context(user_agent=_UA)
        page = await ctx.new_page()

        loaded = await _load_cookies(ctx)
        if not loaded:
            logger.info("쿠키 없음 — ID/PW 로그인")
            await page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded")
            await page.locator("#id").fill(NAVER_ID)
            await page.locator("#pw").fill(NAVER_PW)
            await page.locator("#log\\.login").click()
            await asyncio.sleep(3)

        deleted_count = 0
        failed_urls = []
        for url in target_urls:
            post_id = _extract_post_id(url)
            if not post_id:
                logger.warning(f"포스트 ID 추출 실패: {url}")
                continue
            ok = await delete_post(page, blog_id, post_id)
            if ok:
                deleted_count += 1
            else:
                failed_urls.append(url)
            await asyncio.sleep(1)

        await browser.close()

    logger.info(f"삭제 완료: {deleted_count}/{len(target_urls)}개")
    if failed_urls:
        logger.warning(f"삭제 실패: {failed_urls}")

    if clear_history and os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        logger.info("post_history.json 초기화 완료")
    elif deleted_count > 0:
        # 이력에서 삭제된 포스트 status를 'deleted'로 업데이트
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
        for h in history:
            if h.get("post_url") in target_urls:
                h["status"] = "deleted"
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        logger.info("post_history.json 상태 업데이트 완료 (deleted)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="삭제할 특정 포스트 URL")
    parser.add_argument("--all-history", action="store_true", help="이력 파일도 초기화")
    args = parser.parse_args()

    urls = [args.url] if args.url else None
    asyncio.run(main(target_urls=urls, clear_history=args.all_history))
