"""
네이버 SE 링크카드(oglink) 가운데정렬 — 카드 클릭 시 뜨는 정렬 아이콘 셀렉터 확정 프로브 (로컬 headed, untracked).
실행: python -m scripts._probe_oglink
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, ROOT)
from config import NAVER_ID, NAVER_BLOG_ID
from playwright.async_api import async_playwright
import poster.naver_blog as nb

TEST_URL = "https://blog.naver.com/benefit_genie/224331602830"

DUMP = r"""() => {
  const out=[];
  for (const el of document.querySelectorAll('button,[role=button],li,a')) {
    const cls=(el.className&&el.className.baseVal!==undefined?el.className.baseVal:(el.className||''))+'';
    const dn=el.getAttribute&&el.getAttribute('data-name'); const dv=el.getAttribute&&el.getAttribute('data-value');
    const al=el.getAttribute&&el.getAttribute('aria-label'); const txt=(el.textContent||'').trim().slice(0,16);
    const hay=cls+' '+(dn||'')+' '+(dv||'')+' '+(al||'')+' '+txt;
    if(!/align|정렬|oglink|og-link|component-align|justify|center/i.test(hay)) continue;
    const r=el.getBoundingClientRect();
    out.push({tag:el.tagName.toLowerCase(),dn,dv,al,cls:cls.slice(0,50),txt,vis:!!(el.offsetParent)&&r.width>0,box:[Math.round(r.x),Math.round(r.y)]});
  }
  return out.slice(0,30);
}"""

async def main():
    async with async_playwright() as pw:
        browser=None
        for ch in ("chrome","msedge",None):
            try:
                kw=dict(headless=False,args=["--disable-blink-features=AutomationControlled"])
                if ch:kw["channel"]=ch
                browser=await pw.chromium.launch(**kw);print(f"[launch] {ch}");break
            except Exception as e:print(f"[launch] {ch} 실패:{e}")
        if not browser:return
        ctx=await browser.new_context(user_agent=nb._UA,viewport={"width":1280,"height":900},locale="ko-KR")
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page=await ctx.new_page()
        print(f"[cookies] {await nb._load_cookies(ctx,'')}")
        if not await nb._is_logged_in(page):print("로그인 실패");await browser.close();return
        wp=await nb._navigate_to_write_page(ctx,page,NAVER_ID,NAVER_BLOG_ID or NAVER_ID)
        if not wp:print("에디터 실패");await browser.close();return
        await nb._delay(1500,2500);await nb._dismiss_draft_popup(wp);await nb._close_help_panel(wp);await nb._delay(1000,1500)
        f=await nb._get_editor_frame(wp)

        # 본문 클릭 후 URL 입력 → 링크 카드 생성
        for sel in [".se-content .se-text-paragraph",".se-text-paragraph"]:
            try:
                loc=f.locator(sel).first
                if await loc.count(): await loc.click(timeout=4000); break
            except Exception: pass
        await nb._delay(300,500)
        await wp.keyboard.type(TEST_URL, delay=8)
        await wp.keyboard.press("Enter")
        print("[URL 입력 → 카드 대기]")
        await nb._delay(4000,5000)
        await nb._screenshot(wp,"probe_og_card",full_page=True)

        # 카드 요소 찾기
        card=None
        for sel in [".se-oglink",".se-module-oglink",".se-component.se-oglink","[class*='oglink']","a[class*='oglink']"]:
            try:
                loc=f.locator(sel).first
                if await loc.count():
                    card=loc; print(f"[카드 발견] {sel} (count={await loc.count()})"); break
            except Exception: pass
        if card is None:
            print("✗ 카드 못 찾음 — DOM 덤프")
            for it in await f.evaluate(DUMP): print(f"  {it}")
            await asyncio.sleep(12); await browser.close(); return

        # 카드 클릭 → 정렬 툴바
        try:
            await card.click(timeout=4000)
        except Exception:
            box=await card.bounding_box()
            if box: await wp.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
        await nb._delay(700,1000)
        await nb._screenshot(wp,"probe_og_selected",full_page=True)

        print("\n[정렬/카드 툴바 후보]")
        for it in await f.evaluate(DUMP):
            print(f"  {'👁' if it['vis'] else '·'} <{it['tag']}> dn={it['dn']!r} dv={it['dv']!r} al={it['al']!r} cls={it['cls']!r} txt={it['txt']!r} box={it['box']}")

        # 가운데정렬 시도
        for sel in ["[data-name='component-align'][data-value='center']","[data-value='center'][data-name*='align']",
                    "button[aria-label*='가운데']","[data-name='align-center']",
                    ".se-oglink-toolbar [data-value='center']","[data-name='oglink-align'][data-value='center']"]:
            try:
                loc=f.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=1000):
                    await loc.click(); print(f"\n→ 가운데정렬 클릭: {sel}"); await nb._delay(500,800); break
            except Exception as e: print(f"  {sel} 실패: {str(e)[:45]}")
        await nb._screenshot(wp,"probe_og_centered",full_page=True)
        print("[완료] 15초 후 종료")
        await asyncio.sleep(15)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
