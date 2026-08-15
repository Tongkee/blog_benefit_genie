"""
현지언니 블로그 기본 설정 자동화 스크립트 (로컬 1회 실행)
- 카테고리 구성
- 블로그 기본 정보 (블로그명, 닉네임, 소개글)
- 글쓰기 기본 설정 (에디터 서체/크기)

사용법: python scripts/setup_blog.py
"""
import asyncio
import json
import logging
import os
import sys

# Windows cp949 인코딩 오류 방지
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright

from config import NAVER_ID, NAVER_PW, NAVER_COOKIES, NAVER_BLOG_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_blog")

COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ─── 카테고리 구성 ────────────────────────────────────────────
CATEGORIES = [
    {"name": "살림꿀팁", "sub": [
        "청소&정리",
        "요리&식비절약",
        "인테리어&수납",
        "절약&재테크",
        "쇼핑정보",
    ]},
    {"name": "신혼일상", "sub": []},
]

# ─── 블로그 기본 정보 ─────────────────────────────────────────
BLOG_NAME = "현지언니의 살림꿀팁"
BLOG_NICKNAME = "현지언니"
BLOG_DESCRIPTION = (
    "신혼 2년차 현지언니의 찐 살림 꿀팁 🏠\n"
    "다이소·이케아 활용법, 식비 절약, 청소 루틴, 인테리어까지!\n"
    "매일 올라오는 실제 써본 살림 노하우를 나눠요 💕"
)


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


async def setup_blog_info(page):
    """블로그 기본 정보 설정 (블로그명, 닉네임, 소개글)"""
    blog_id = NAVER_BLOG_ID or NAVER_ID
    url = f"https://admin.blog.naver.com/{blog_id}/config/bloginfo"
    logger.info(f"블로그 기본 정보 설정 페이지: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(4)

    # 디버그 스크린샷 저장
    shot_path = os.path.join(ROOT, "data", "screenshots", "setup_info_debug.png")
    os.makedirs(os.path.dirname(shot_path), exist_ok=True)
    await page.screenshot(path=shot_path)
    logger.info(f"디버그 스크린샷 저장: {shot_path}")

    # Naver Blog 어드민 프레임 처리 (papermain 사용)
    target = page.frame_locator("#papermain")

    # 블로그명 입력
    blog_name_sels = [
        "input[name='blogName']",
        "#blogName",
        "input[placeholder*='블로그명']",
        "input[placeholder*='블로그 이름']",
    ]
    for sel in blog_name_sels:
        try:
            el = target.locator(sel).first
            if await el.count():
                await el.fill(BLOG_NAME)
                logger.info(f"블로그명 입력: {BLOG_NAME}")
                break
        except Exception:
            continue

    # 닉네임 입력
    nick_sels = [
        "input[name='nickname']",
        "#nickname",
        "input[placeholder*='닉네임']",
        "input[placeholder*='별명']",
    ]
    for sel in nick_sels:
        try:
            el = target.locator(sel).first
            if await el.count():
                await el.fill(BLOG_NICKNAME)
                logger.info(f"닉네임 입력: {BLOG_NICKNAME}")
                break
        except Exception:
            continue

    # 소개글 입력
    intro_sels = [
        "textarea[name='introduction']",
        "#blogIntro",
        "textarea[placeholder*='소개']",
    ]
    for sel in intro_sels:
        try:
            el = target.locator(sel).first
            if await el.count():
                await el.fill(BLOG_DESCRIPTION)
                logger.info(f"소개글 입력 완료")
                break
        except Exception:
            continue

    # 저장 버튼 클릭
    save_sels = [
        "button:has-text('확인')",
        "button:has-text('저장')",
        "input[type='submit']",
    ]
    for sel in save_sels:
        try:
            btn = target.locator(sel).first
            if await btn.count() and await btn.is_visible(timeout=2000):
                await btn.click()
                await asyncio.sleep(2)
                logger.info("기본 설정 저장 완료")
                return True
        except Exception:
            continue

    logger.warning("블로그 기본 정보 자동 설정 실패 — 수동 설정 필요")
    return False


async def setup_categories(page):
    """카테고리 구성 설정"""
    blog_id = NAVER_BLOG_ID or NAVER_ID
    url = f"https://admin.blog.naver.com/{blog_id}/config/blog"
    logger.info(f"카테고리 관리 페이지: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(4)

    current_url = page.url
    if "login" in current_url or "nidlogin" in current_url:
        logger.warning("로그인 필요 — 카테고리 설정 건너뜀")
        return False

    logger.info(f"카테고리 페이지 URL: {current_url}")

    # 디버그 스크린샷 저장
    shot_path = os.path.join(ROOT, "data", "screenshots", "setup_categories_debug.png")
    os.makedirs(os.path.dirname(shot_path), exist_ok=True)
    await page.screenshot(path=shot_path)
    logger.info(f"디버그 스크린샷 저장: {shot_path}")

    # Naver Blog 어드민 프레임 처리 (papermain 사용)
    target = page.frame_locator("#papermain")

    # 카테고리 추가 버튼 탐색
    add_sels = [
        "button:has-text('카테고리 추가')",
        "a:has-text('카테고리 추가')",
        "#addCategoryBtn",
        ".btn_add",
    ]
    add_btn = None
    for sel in add_sels:
        try:
            btn = target.locator(sel).first
            if await btn.count():
                add_btn = btn
                logger.info(f"카테고리 추가 버튼 발견: {sel}")
                break
        except Exception:
            continue

    if not add_btn:
        logger.warning("카테고리 추가 버튼 없음 — 페이지 구조 확인 필요")
        # 현재 페이지의 버튼 목록 디버그
        try:
            btns = await target.evaluate("""
                () => [...document.querySelectorAll('button,a')].slice(0, 20)
                      .map(e => ({tag:e.tagName, txt:e.textContent.trim().slice(0,20)}))
            """)
            logger.info(f"페이지 버튼 목록: {btns}")
        except Exception:
            pass
        return False

    # 카테고리 추가 시도
    for cat in CATEGORIES:
        try:
            await add_btn.click()
            await asyncio.sleep(1)

            # 카테고리명 입력
            name_input = target.locator("input.input_text, input[type='text']").last
            if await name_input.count():
                await name_input.fill(cat["name"])
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.5)
                logger.info(f"카테고리 추가: {cat['name']}")

            # 하위 카테고리 추가
            for sub in cat["sub"]:
                sub_btn_sels = [
                    "button:has-text('하위 카테고리 추가')",
                    "button:has-text('하위')",
                    ".btn_sub_add",
                ]
                for sel in sub_btn_sels:
                    try:
                        sbtn = target.locator(sel).first
                        if await sbtn.count() and await sbtn.is_visible(timeout=1000):
                            await sbtn.click()
                            await asyncio.sleep(0.5)
                            sub_input = target.locator("input.input_text, input[type='text']").last
                            if await sub_input.count():
                                await sub_input.fill(sub)
                                await page.keyboard.press("Enter")
                                await asyncio.sleep(0.5)
                                logger.info(f"  하위 카테고리 추가: {sub}")
                            break
                    except Exception:
                        continue

        except Exception as e:
            logger.warning(f"카테고리 추가 실패 ({cat['name']}): {e}")

    # 저장
    save_sels = [
        "button:has-text('확인')",
        "button:has-text('저장')",
        "#saveCategoryBtn",
    ]
    for sel in save_sels:
        try:
            btn = target.locator(sel).first
            if await btn.count() and await btn.is_visible(timeout=2000):
                await btn.click()
                await asyncio.sleep(2)
                logger.info("카테고리 저장 완료")
                return True
        except Exception:
            continue

    return False


async def setup_editor_defaults(page):
    """에디터 기본 설정 (서체 16pt, 줄간격 180%)"""
    blog_id = NAVER_BLOG_ID or NAVER_ID
    url = f"https://admin.blog.naver.com/{blog_id}/config/defaulteditor"
    logger.info(f"에디터 기본 설정 페이지: {url}")
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)
        
        # 디버그 스크린샷 저장
        shot_path = os.path.join(ROOT, "data", "screenshots", "setup_editor_debug.png")
        os.makedirs(os.path.dirname(shot_path), exist_ok=True)
        await page.screenshot(path=shot_path)
        logger.info(f"디버그 스크린샷 저장: {shot_path}")

        # Naver Blog 어드민 프레임 처리 (papermain 사용)
        target = page.frame_locator("#papermain")

        # 서체 설정
        font_sels = [
            "select[name='fontFamily']",
            "#fontFamily",
            "select.font_select",
        ]
        for sel in font_sels:
            try:
                el = target.locator(sel).first
                if await el.count():
                    await el.select_option(label="나눔스퀘어")
                    logger.info("서체: 나눔스퀘어 선택")
                    break
            except Exception:
                continue

        # 글자 크기
        size_sels = [
            "select[name='fontSize']",
            "#fontSize",
            "input[name='fontSize']",
        ]
        for sel in size_sels:
            try:
                el = target.locator(sel).first
                if await el.count():
                    try:
                        await el.select_option(label="16")
                    except Exception:
                        await el.fill("16")
                    logger.info("글자 크기: 16pt")
                    break
            except Exception:
                continue

        # 줄 간격
        spacing_sels = [
            "select[name='lineHeight']",
            "#lineHeight",
        ]
        for sel in spacing_sels:
            try:
                el = target.locator(sel).first
                if await el.count():
                    await el.select_option(label="180%")
                    logger.info("줄 간격: 180%")
                    break
            except Exception:
                continue

        # 저장
        for save_sel in ["button:has-text('저장')", "button:has-text('확인')"]:
            try:
                btn = target.locator(save_sel).first
                if await btn.count() and await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(2)
                    logger.info("에디터 설정 저장 완료")
                    return True
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"에디터 설정 페이지 실패 ({url}): {e}")

    logger.warning("에디터 기본 설정 자동화 실패 — 수동 설정 필요")
    return False


async def main():
    blog_id = NAVER_BLOG_ID or NAVER_ID
    logger.info(f"현지언니 블로그 설정 시작 (blogId={blog_id})")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(user_agent=_UA)
        page = await ctx.new_page()

        loaded = await _load_cookies(ctx)
        if not loaded:
            logger.info("쿠키 없음 — 로그인 필요")
            await page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded")
            await page.locator("#id").fill(NAVER_ID)
            await page.locator("#pw").fill(NAVER_PW)
            await page.locator("#log\\.login").click()
            await asyncio.sleep(3)

        # 1. 블로그 기본 정보
        logger.info("=" * 40)
        logger.info("1. 블로그 기본 정보 설정")
        await setup_blog_info(page)

        # 2. 카테고리 구성
        logger.info("=" * 40)
        logger.info("2. 카테고리 구성")
        await setup_categories(page)

        # 3. 에디터 기본 설정
        logger.info("=" * 40)
        logger.info("3. 에디터 기본 설정")
        await setup_editor_defaults(page)

        logger.info("=" * 40)
        logger.info("설정 완료! 5초 후 브라우저가 자동으로 닫힙니다...")
        await asyncio.sleep(5)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
