"""
네이버 SE 임시저장 드래프트 목록 조회/삭제 프로브 (로컬 headed, untracked).
기본: 목록만 조회(삭제 안 함). --delete-all 주면 전체 삭제.
실행: python -m scripts._probe_drafts            (조회만)
      python -m scripts._probe_drafts --delete-all  (전체 삭제)
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, ROOT)
from config import NAVER_ID, NAVER_BLOG_ID
from playwright.async_api import async_playwright
import poster.naver_blog as nb

DELETE_ALL = "--delete-all" in sys.argv

LIST_DUMP = r"""() => {
  const out=[];
  for (const el of document.querySelectorAll('a,li,div,button,span')) {
    const cls=(el.className&&el.className.baseVal!==undefined?el.className.baseVal:(el.className||''))+'';
    const txt=(el.textContent||'').trim().slice(0,40);
    if(!/save|draft|임시|저장|list|popup|layer/i.test(cls)) continue;
    const r=el.getBoundingClientRect();
    if(r.width<5||r.height<5) continue;
    out.push({tag:el.tagName.toLowerCase(),cls:cls.slice(0,46),txt,box:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]});
  }
  return out.slice(0,40);
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

        # 저장 카운트 버튼 클릭 → 임시저장 목록 레이어
        for sel in [".save_count_btn__ZTLNa","[class*='save_count_btn']","[class*='save_count']","button[class*='save'][class*='count']"]:
            try:
                loc=wp.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=2000):
                    print(f"[저장카운트 버튼] {sel} (txt={(await loc.inner_text()).strip()!r})")
                    await loc.click(); await nb._delay(1200,1800); break
            except Exception as e: print(f"  {sel} 실패: {str(e)[:60]}")
        await nb._screenshot(wp,"probe_drafts_list",full_page=True)

        # 목록 항목 덤프 (메인 페이지 기준)
        items=await wp.evaluate(LIST_DUMP)
        print(f"\n===== 저장목록 후보 DOM {len(items)} =====")
        for it in items:
            print(f"  <{it['tag']}> cls={it['cls']!r} txt={it['txt']!r} box={it['box']}")

        if DELETE_ALL:
            print("\n[--delete-all] 전체 삭제 모드")
            # 삭제 버튼/체크박스 셀렉터는 위 덤프 확인 후 확정 (이번엔 조회 우선)
            print("  (삭제 셀렉터는 목록 DOM 확인 후 다음 실행에서 적용)")

        print("\n[완료] 20초 후 종료 (브라우저에서 직접 확인 가능)")
        await asyncio.sleep(20)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
