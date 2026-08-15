"""
SE ONE 표 열삭제 v5 — se-selection 오버레이 pointer-events 무력화 후 정상 클릭 (로컬 headed, untracked).
실행: python -m scripts._probe_table_col
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, ROOT)
from config import NAVER_ID, NAVER_BLOG_ID
from playwright.async_api import async_playwright
import poster.naver_blog as nb

DISABLE_OVERLAY = """() => {
  let s = document.getElementById('__probe_style');
  if (!s) { s = document.createElement('style'); s.id='__probe_style'; document.head.appendChild(s); }
  s.textContent = '.se-selection,.se-selection *{pointer-events:none !important;}';
  return true;
}"""

async def cols(t):
    return await t.evaluate("""()=>{const a=document.querySelectorAll('.se-section-table table,table');if(!a.length)return 0;const r=a[a.length-1].querySelector('tr');return r?r.children.length:0;}""")

async def menu_state(t):
    return await t.evaluate("""()=>{const b=[...document.querySelectorAll('.se-cell-context-menu-item,.se-cell-context-menu-button')].filter(e=>(e.textContent||'').trim()==='삭제')[0];if(!b)return null;const r=b.getBoundingClientRect();return {x:Math.round(r.x),y:Math.round(r.y),onscreen:r.x>0&&r.y>0&&r.x<1280&&r.y<900};}""")

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
        await nb._insert_table(wp,"항목 | 내용\n신청나이 | 만39세\n소득 | 중위100%","표프로브")
        await nb._delay(1500,2000)
        t=await nb._get_editor_frame(wp)
        print(f"\n[삽입 후 열 수] {await cols(t)}")

        # ★ se-selection 오버레이 pointer-events 무력화
        await t.evaluate(DISABLE_OVERLAY)
        print("[오버레이 pointer-events 무력화 주입]")
        await nb._delay(300,500)

        sel=t.locator(".se-cell-controlbar-item .se-cell-select-button")
        labels=[(await sel.nth(i).inner_text()).strip() for i in range(await sel.count())]
        col_idx=[i for i,x in enumerate(labels) if '열 선택' in x]
        last=col_idx[-1]
        print(f"[열 선택] {[labels[i] for i in col_idx]} → nth({last})={labels[last]!r}")

        # 네이티브 클릭 (오버레이 제거됐으니 닿아야 함)
        clicked=False
        for how in ("native","force"):
            try:
                if how=="native":
                    await sel.nth(last).click(timeout=4000)
                else:
                    await sel.nth(last).click(force=True,timeout=3000)
                print(f"  ✓ 열선택 {how} 클릭"); clicked=True; break
            except Exception as e:
                print(f"  ✗ {how} 실패: {str(e)[:80]}")
                await t.evaluate(DISABLE_OVERLAY)  # 재주입
        await nb._delay(700,1100)
        print(f"[삭제 메뉴 상태] {await menu_state(t)}")
        await nb._screenshot(wp,"probe_v5_after_select",full_page=True)

        # 삭제 클릭
        delbtn=t.locator(".se-cell-context-menu-button:has-text('삭제'), .se-cell-context-menu-item:has-text('삭제')").first
        ms=await menu_state(t)
        if ms and ms.get("onscreen"):
            for how in ("native","force"):
                try:
                    if how=="native": await delbtn.click(timeout=4000)
                    else: await delbtn.click(force=True,timeout=3000)
                    print(f"  ✓ 삭제 {how} 클릭"); break
                except Exception as e: print(f"  ✗ 삭제 {how} 실패: {str(e)[:80]}")
        else:
            print(f"  삭제 버튼 off-screen({ms}) — page.mouse 강행")
            box=await delbtn.bounding_box()
            if box and box["x"]>0:
                await wp.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
                print("  page.mouse 삭제 시도")
        await nb._delay(900,1300)
        await nb._screenshot(wp,"probe_v5_after_delete",full_page=True)
        print(f"\n[최종 열 수] {await cols(t)}  (목표 2)")
        print("[완료] 18초 후 종료")
        await asyncio.sleep(18)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
