import asyncio
import json
import os
import sys
from playwright.async_api import async_playwright

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

COOKIE_PATH = os.path.join(ROOT, "data", "naver_cookies.json")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

async def main():
    with open(COOKIE_PATH, encoding="utf-8") as f:
        cookies = json.load(f)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_UA)
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        url = "https://admin.blog.naver.com/hyunji_unni/config/blog"
        await page.goto(url)
        await asyncio.sleep(5)

        frame = None
        for f in page.frames:
            if "papermain" in (f.name or ""):
                frame = f
                break
                
        if frame:
            elements = await frame.evaluate("""
                () => {
                    const elList = [...document.querySelectorAll('a, button, input, img, span, div')];
                    // Filter to only elements that look like buttons or inputs or links
                    return elList
                        .filter(e => {
                            const tag = e.tagName.toLowerCase();
                            const cls = (e.className || '').toString();
                            const id = e.id || '';
                            const role = e.getAttribute('role') || '';
                            return tag === 'a' || tag === 'button' || tag === 'input' || 
                                   cls.includes('btn') || id.includes('btn') || role.includes('button');
                        })
                        .map(e => ({
                            tag: e.tagName,
                            id: e.id,
                            cls: e.className,
                            txt: e.textContent.trim().slice(0, 50),
                            val: e.value || '',
                            alt: e.alt || '',
                            html: e.outerHTML.slice(0, 150)
                        }));
                }
            """)
            print(f"총 {len(elements)}개의 버튼/입력/클릭 가능 요소 발견")
            for i, el in enumerate(elements):
                print(f"[{i}] Tag: {el['tag']}, ID: {el['id']}, Class: {el['cls']}, Text: {el['txt']}, Val: {el['val']}, Alt: {el['alt']}")
                print(f"    HTML: {el['html']}")
        else:
            print("papermain 프레임을 찾지 못했습니다.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
