"""셀 배경색 팔레트 정밀 관측 — data-value와 '실제 적용색' 매핑 확인.

E2E에서 '#b0f1ff 없음' 경고가 났는데 헤더는 #d9f7e2로 칠해져 있었다.
→ ①팔레트 스와치의 data-value가 내가 찾는 값과 다르게 표기되거나
  ②이미 다른 코드(_format_table_header)가 색을 넣는 중이거나
  ③팔레트가 '셀 배경색'이 아니라 다른 버튼의 것이었을 수 있다.
스와치를 하나씩 눌러 실제 적용색을 대조해 사실을 확정한다.

실행: python -m scripts._probe_palette
"""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import NAVER_ID, NAVER_BLOG_ID  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402
import poster.naver_blog as nb  # noqa: E402

HEX = """(c) => { const m=(c||'').match(/\\d+/g); return m&&m.length>=3 ?
  '#'+m.slice(0,3).map(x=>(+x).toString(16).padStart(2,'0')).join('') : c; }"""

ROW0_BG = """() => {
  const ts=document.querySelectorAll('table'); const t=ts[ts.length-1]; if(!t) return '';
  const r=t.querySelector('tr'); if(!r) return '';
  const c=getComputedStyle(r.children[0]).backgroundColor;
  const m=(c||'').match(/\\d+/g);
  return m&&m.length>=3 ? '#'+m.slice(0,3).map(x=>(+x).toString(16).padStart(2,'0')).join('') : c;
}"""

SWATCHES = """() => [...document.querySelectorAll('[data-value]')]
  .filter(e => e.offsetParent && /se-color-palette|se-color-swatches/.test(e.className||''))
  .map(e => { const r=e.getBoundingClientRect();
    return {v:e.getAttribute('data-value'), cls:(e.className||'').slice(0,50),
            x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}; })
  .filter(o => o.w>0 && o.x>0)"""


async def main():
    async with async_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                kw = dict(headless=False, args=["--disable-blink-features=AutomationControlled"])
                if ch:
                    kw["channel"] = ch
                browser = await pw.chromium.launch(**kw)
                break
            except Exception:
                continue
        if not browser:
            return
        ctx = await browser.new_context(user_agent=nb._UA, viewport={"width": 1280, "height": 900},
                                        locale="ko-KR")
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        await nb._load_cookies(ctx, "")
        if not await nb._is_logged_in(page):
            print("로그인 실패")
            await browser.close()
            return
        wp = await nb._navigate_to_write_page(ctx, page, NAVER_ID, NAVER_BLOG_ID or NAVER_ID)
        if not wp:
            await browser.close()
            return
        await nb._delay(1500, 2500)
        await nb._dismiss_draft_popup(wp)
        await nb._close_help_panel(wp)
        await nb._delay(1000, 1500)
        t = await nb._get_editor_frame(wp)

        await wp.keyboard.type("팔레트 관측")
        await wp.keyboard.press("Enter")
        await nb._insert_table(wp, "A | B | C\n1 | 2 | 3", "팔레트 관측")
        await asyncio.sleep(1.5)
        print(f"\n[표 삽입 직후] 0행 배경 = {await t.evaluate(ROW0_BG)}")
        print("  ※ _insert_table의 헤더 채색이 이미 돌았을 수 있음")

        # 2행(데이터행)을 대상으로 — 헤더 채색과 섞이지 않게
        print("\n[2행 드래그 선택 → 셀 배경색 버튼]")
        await nb._drag_select_cells(wp, row_idx=1)
        opened = False
        for sel in ("[data-name='cell-background-color']",
                    ".se-cell-background-color-toolbar-button"):
            try:
                for fr in (t, wp):
                    loc = fr.locator(sel).first
                    if await loc.count() and await loc.is_visible(timeout=700):
                        await loc.click(timeout=2000)
                        opened = True
                        print(f"  버튼 클릭: {sel}")
                        break
                if opened:
                    break
            except Exception:
                continue
        if not opened:
            print("  ❌ 셀 배경색 버튼 못 찾음")
            await browser.close()
            return
        await asyncio.sleep(0.9)

        # 진단: 어느 프레임에 팔레트가 렌더되는지 전수 확인
        print("\n[팔레트 진단]")
        sw = []
        for fr, nm in ((t, "iframe"), (wp, "page")):
            try:
                info = await fr.evaluate("""() => {
                  const all=[...document.querySelectorAll('[data-value]')];
                  const vis=all.filter(e=>e.offsetParent);
                  const pal=[...document.querySelectorAll(
                      '[class*=color-palette],[class*=color-swatches]')];
                  return {dvAll:all.length, dvVis:vis.length,
                          palAll:pal.length, palVis:pal.filter(e=>e.offsetParent).length,
                          sample: vis.slice(0,6).map(e =>
                            (e.getAttribute('data-value')||'-')+' / '+(e.className||'').slice(0,30))};
                }""")
                print(f"   [{nm}] data-value 전체{info['dvAll']}/보임{info['dvVis']} | "
                      f"palette 전체{info['palAll']}/보임{info['palVis']}")
                for x in info["sample"]:
                    print(f"        {x}")
                # 팔레트 요소의 실제 DOM 구조 덤프(색이 어느 속성에 있나)
                raw = await fr.evaluate("""() =>
                  [...document.querySelectorAll(
                      '[class*=color-palette],[class*=color-swatches]')]
                    .filter(e => e.offsetParent)
                    .slice(0, 12)
                    .map(e => { const r=e.getBoundingClientRect(); const cs=getComputedStyle(e);
                      const at={}; for (const a of e.attributes) at[a.name]=a.value.slice(0,24);
                      return {tag:e.tagName, cls:(e.className||'').slice(0,42),
                              bg:cs.backgroundColor, attrs:at,
                              x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)}; })
                """)
                print(f"   [{nm}] 팔레트 요소 구조 {len(raw)}개:")
                for o in raw[:10]:
                    print(f"        <{o['tag']}> bg={o['bg']} @({o['x']},{o['y']},w{o['w']}) "
                          f"{o['cls'][:34]}")
                    print(f"           attrs={o['attrs']}")
                got = await fr.evaluate(SWATCHES)
                if got and not sw:
                    sw = got
                    print(f"   → [{nm}]에서 스와치 {len(got)}개 확보")
            except Exception as e:
                print(f"   [{nm}] 진단실패: {e}")
        print(f"\n[스와치 {len(sw)}개]")
        for o in sw[:20]:
            print(f"   {str(o['v']):<12} @({o['x']},{o['y']}) {o['cls'][:44]}")

        # 몇 개를 실제로 눌러 적용색 대조
        for want in ("#fff8b2", "#b0f1ff", "#e3fdc8"):
            cand = [o for o in sw if (o["v"] or "").lower() == want]
            if not cand:
                print(f"\n   {want}: 스와치 목록에 없음")
                continue
            o = cand[0]
            await wp.mouse.click(o["x"] + o["w"] / 2, o["y"] + o["h"] / 2)
            await asyncio.sleep(0.8)
            got = await t.evaluate("""() => {
              const ts=document.querySelectorAll('table'); const t=ts[ts.length-1];
              const r=t.querySelectorAll('tr')[1]; if(!r) return '';
              const c=getComputedStyle(r.children[0]).backgroundColor;
              const m=(c||'').match(/\\d+/g);
              return m&&m.length>=3 ? '#'+m.slice(0,3).map(x=>(+x).toString(16).padStart(2,'0')).join('') : c;
            }""")
            print(f"\n   클릭 {want} → 2행 실제색 {got}  {'✅일치' if got==want else '❌불일치'}")
            # 다음 색 적용 위해 다시 선택+팔레트 열기
            await nb._drag_select_cells(wp, row_idx=1)
            for sel in ("[data-name='cell-background-color']",
                        ".se-cell-background-color-toolbar-button"):
                try:
                    for fr in (t, wp):
                        loc = fr.locator(sel).first
                        if await loc.count() and await loc.is_visible(timeout=600):
                            await loc.click(timeout=1500)
                            break
                    break
                except Exception:
                    continue
            await asyncio.sleep(0.7)
            sw = await t.evaluate(SWATCHES) or sw

        print("\n20초 후 닫힘")
        await asyncio.sleep(20)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
