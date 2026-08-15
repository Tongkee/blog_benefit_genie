"""
SE ONE 네이티브 글머리표(•) 리스트 적용 → 내어쓰기(hanging indent) 검증 프로브 (로컬 headed, untracked).
실행: python -m scripts._probe_list
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(__file__)); sys.path.insert(0, ROOT)
from config import NAVER_ID, NAVER_BLOG_ID
from playwright.async_api import async_playwright
import poster.naver_blog as nb

TOOLBAR_DUMP = r"""() => {
  const out=[];
  for (const el of document.querySelectorAll('button,[role=button],li')) {
    const cls=(el.className&&el.className.baseVal!==undefined?el.className.baseVal:(el.className||''))+'';
    const dn=el.getAttribute&&el.getAttribute('data-name');
    const al=el.getAttribute&&el.getAttribute('aria-label');
    const txt=(el.textContent||'').trim().slice(0,18);
    const hay=cls+' '+(dn||'')+' '+(al||'')+' '+txt;
    if(!/list|unordered|ordered|글머리|번호|bullet|indent|들여|내어/i.test(hay)) continue;
    const r=el.getBoundingClientRect();
    out.push({tag:el.tagName.toLowerCase(),dn,al,cls:cls.slice(0,48),txt,vis:!!(el.offsetParent)&&r.width>0,box:[Math.round(r.x),Math.round(r.y)]});
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

        # 본문에 긴 불릿 줄 3개 입력 (줄바꿈 유발용 — · 없이, 리스트가 자체 불릿 부여)
        # 보이는 본문 단락 클릭(숨김 contenteditable 회피)
        clicked=False
        for sel in [".se-content .se-text-paragraph", ".se-section-text .se-text-paragraph", ".se-text-paragraph"]:
            try:
                loc=f.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=4000); clicked=True; print(f"[본문 클릭] {sel}"); break
            except Exception as e: print(f"  {sel} 실패: {str(e)[:50]}")
        if not clicked:
            await wp.keyboard.press("Tab")  # 제목→본문 폴백
        await nb._delay(300,500)
        lines = [
            "나이 조건은 만 39세 이상 만 49세 이하로 신청일 기준 주민등록상 연령을 따집니다",
            "소득 기준은 중위소득 100퍼센트 이하이며 맞벌이는 160퍼센트까지 완화 적용됩니다",
            "거주 요건은 신청일 현재 해당 시군구에 주민등록이 되어 있어야 인정됩니다",
        ]
        for i,ln in enumerate(lines):
            await wp.keyboard.type(ln, delay=6)
            if i < len(lines)-1: await wp.keyboard.press("Enter")
        await nb._delay(500,800)
        await nb._screenshot(wp,"probe_list_before",full_page=True)

        # 방금 입력한 3줄 선택 (Shift+위로 + Home/End) — 전체 선택으로 단순화
        await wp.keyboard.press("Control+a")
        await nb._delay(300,500)

        print("\n[리스트/들여쓰기 툴바 후보]")
        for it in await f.evaluate(TOOLBAR_DUMP):
            print(f"  {'👁' if it['vis'] else '·'} <{it['tag']}> dn={it['dn']!r} al={it['al']!r} cls={it['cls']!r} txt={it['txt']!r} box={it['box']}")

        # ① 목록 드롭다운 열기 (메인 툴바 [data-name='list'])
        opened=False
        for sel in [".se-property-toolbar-drop-down-button[data-name='list']","[data-name='list']"]:
            try:
                loc=f.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=1500):
                    await loc.click(); opened=True; print(f"\n→ 목록 드롭다운 열기: {sel}"); await nb._delay(600,900); break
            except Exception as e: print(f"  {sel} 실패: {str(e)[:50]}")
        await nb._screenshot(wp,"probe_list_dropdown",full_page=True)

        # ② 드롭다운 옵션 덤프 (data-value / option 버튼)
        print("\n[드롭다운 옵션 후보]")
        opts = await f.evaluate(r"""() => {
          const out=[];
          for (const el of document.querySelectorAll("[data-name='list'],[class*='list-toolbar'],[class*='toolbar-option'] ,button")) {
            const cls=(el.className||'')+''; const dv=el.getAttribute&&el.getAttribute('data-value'); const dn=el.getAttribute&&el.getAttribute('data-name');
            if(!/list|unordered|ordered|bullet/i.test(cls+' '+(dn||''))) continue;
            const r=el.getBoundingClientRect();
            if(r.width<3) continue;
            out.push({dn,dv,cls:cls.slice(0,46),vis:!!(el.offsetParent),box:[Math.round(r.x),Math.round(r.y)]});
          }
          return out.slice(0,20);
        }""")
        for o in opts: print(f"  {'👁' if o['vis'] else '·'} dn={o['dn']!r} dv={o['dv']!r} cls={o['cls']!r} box={o['box']}")

        # ③ 불릿(unordered) 옵션 클릭
        applied=False
        for sel in ["[data-name='list'][data-value='unordered']","[data-name='list'][data-value='bullet']",
                    "[class*='se-list-bull'][data-value]","[data-name='list'] [data-value='unordered']",
                    "button[class*='unordered']","[data-value='unordered']"]:
            try:
                loc=f.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=1200):
                    await loc.click(); applied=True; print(f"→ 불릿 옵션 클릭: {sel}"); await nb._delay(600,900); break
            except Exception as e: print(f"  opt {sel} 실패: {str(e)[:45]}")
        if not applied: print("✗ 불릿 옵션 못 찾음 — 드롭다운 옵션 덤프 참고")
        await nb._screenshot(wp,"probe_list_after",full_page=True)

        # 결과 DOM: li / hanging indent 여부
        info = await f.evaluate(r"""() => {
          const lis=document.querySelectorAll('.se-component-content li, .se-text-paragraph');
          const sample=[...document.querySelectorAll('li')].slice(0,3).map(li=>({
            cls:(li.className||'').slice(0,40),
            ti:getComputedStyle(li).textIndent, pl:getComputedStyle(li).paddingLeft, ml:getComputedStyle(li).marginLeft,
            ls:getComputedStyle(li).listStylePosition}));
          return {li_count:document.querySelectorAll('li').length, sample};
        }""")
        print(f"\n[결과] li 개수={info['li_count']}, 샘플={info['sample']}")
        print("[완료] 18초 후 종료")
        await asyncio.sleep(18)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
