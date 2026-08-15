"""SE ONE 표 조작 v6 — '셀 병합' 경로 탐색 (로컬 headed, untracked 성격).

배경(2026-07-29 사용자 지적): 지금까지 '열 삭제'만 5종 시도해 전부 실패했는데,
사용자가 실제 에디터에서 쓰는 방법은 ①셀을 드래그로 선택 → ②뜨는 메뉴에서 '셀 병합'.
3열을 지울 필요 없이 한 행의 3칸을 병합하면 1칸(=1열 박스행)이 된다.

기존 probe가 시도한 것: 컨트롤바 '3열 선택' 버튼 클릭(native/force/page.mouse/오버레이무력화).
★이번에 새로 시도하는 것:
  A. 드래그 선택(mouse.down → move → up) — 사람이 하는 실제 제스처
  B. Shift+클릭 범위 선택
  C. 선택 후 뜨는 컨텍스트 메뉴에서 '셀 병합' 클릭
각 단계마다 DOM 상태(선택된 셀 수 / 메뉴 위치·표시 여부 / colspan)를 찍어
'어디서 막히는지'를 좌표·수치로 남긴다.

실행: python -m scripts._probe_table_merge     (headed 브라우저, 네이버 쿠키 필요)
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

DISABLE_OVERLAY = """() => {
  let s = document.getElementById('__probe_style');
  if (!s) { s = document.createElement('style'); s.id='__probe_style'; document.head.appendChild(s); }
  s.textContent = '.se-selection,.se-selection *{pointer-events:none !important;}';
  return true;
}"""

# 선택된 셀 수·병합 상태를 한 번에 관측
STATE_JS = """() => {
  const ts = document.querySelectorAll('.se-section-table table, table');
  const t = ts[ts.length-1];
  if (!t) return {tables:0};
  const rows = [...t.querySelectorAll('tr')];
  const sel = document.querySelectorAll('.se-cell-selected, td[class*="selected"], .se-selected-cell');
  const menuItems = [...document.querySelectorAll(
      '.se-cell-context-menu-item, .se-cell-context-menu-button')]
    .map(e => { const r = e.getBoundingClientRect();
      return {t:(e.textContent||'').trim(), x:Math.round(r.x), y:Math.round(r.y),
              on: r.x>0 && r.y>0 && r.x<1280 && r.y<900}; });
  return {
    tables: ts.length,
    grid: rows.map(r => [...r.children].map(c => c.getAttribute('colspan')||'1').join('/')),
    selectedCells: sel.length,
    menu: menuItems,
  };
}"""


async def dump(t, label):
    st = await t.evaluate(STATE_JS)
    print(f"\n── {label} ──")
    print(f"   표 {st.get('tables')}개 | 행별 colspan: {st.get('grid')}")
    print(f"   선택된 셀: {st.get('selectedCells')}")
    for m in (st.get("menu") or []):
        print(f"   메뉴 '{m['t']}' @({m['x']},{m['y']}) 화면안={m['on']}")
    return st


async def main():
    async with async_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                kw = dict(headless=False, args=["--disable-blink-features=AutomationControlled"])
                if ch:
                    kw["channel"] = ch
                browser = await pw.chromium.launch(**kw)
                print(f"[launch] {ch}")
                break
            except Exception as e:
                print(f"[launch] {ch} 실패: {e}")
        if not browser:
            return
        ctx = await browser.new_context(user_agent=nb._UA, viewport={"width": 1280, "height": 900},
                                        locale="ko-KR")
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        print(f"[cookies] {await nb._load_cookies(ctx, '')}")
        if not await nb._is_logged_in(page):
            print("로그인 실패 — 쿠키 갱신 필요")
            await browser.close()
            return
        wp = await nb._navigate_to_write_page(ctx, page, NAVER_ID, NAVER_BLOG_ID or NAVER_ID)
        if not wp:
            print("에디터 진입 실패")
            await browser.close()
            return
        await nb._delay(1500, 2500)
        await nb._dismiss_draft_popup(wp)
        await nb._close_help_panel(wp)
        await nb._delay(1000, 1500)

        # 빈 표 생성(셀 채우기 전 = 되돌리기 쉬움)
        await wp.keyboard.type("표 병합 프로브")
        await wp.keyboard.press("Enter")
        t = await nb._get_editor_frame(wp)
        for sel in [".se-table-toolbar-button", "[data-name='table']",
                    "button[data-name='table']", "[aria-label='표']"]:
            try:
                loc = t.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=2000):
                    await loc.click(timeout=3000)
                    break
            except Exception:
                continue
        await asyncio.sleep(2.0)
        await dump(t, "표 생성 직후")

        await t.evaluate(DISABLE_OVERLAY)
        print("\n[오버레이 pointer-events 무력화 주입]")

        # ── 첫 행 셀들의 좌표 확보 ──
        cells = t.locator("table tr:first-child td, table tr:first-child th")
        n = await cells.count()
        print(f"[첫 행 셀 수] {n}")
        if n < 2:
            print("셀 부족 — 중단")
            await browser.close()
            return
        b0 = await cells.nth(0).bounding_box()
        bl = await cells.nth(n - 1).bounding_box()
        print(f"   첫 셀 @({b0['x']:.0f},{b0['y']:.0f})  마지막 셀 @({bl['x']:.0f},{bl['y']:.0f})")

        # ── A. 드래그 선택 (사람이 하는 제스처) ──
        print("\n[A] 드래그 선택 시도: 첫 셀 → 마지막 셀")
        await wp.mouse.move(b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2)
        await wp.mouse.down()
        steps = 12
        for i in range(1, steps + 1):
            await wp.mouse.move(
                b0["x"] + (bl["x"] - b0["x"]) * i / steps + bl["width"] / 2,
                b0["y"] + b0["height"] / 2, steps=1)
            await asyncio.sleep(0.05)
        await wp.mouse.up()
        await asyncio.sleep(1.2)
        st = await dump(t, "A. 드래그 선택 후")

        # ── C. 메뉴에서 '셀 병합' 클릭 ──
        merge = [m for m in (st.get("menu") or []) if "병합" in m["t"]]
        if merge and merge[0]["on"]:
            print(f"\n[C] '셀 병합' 클릭 시도 @({merge[0]['x']},{merge[0]['y']})")
            await wp.mouse.click(merge[0]["x"] + 30, merge[0]["y"] + 10)
            await asyncio.sleep(1.2)
            await dump(t, "C. 병합 클릭 후 (colspan 확인)")
        else:
            print(f"\n[C] '셀 병합' 메뉴 사용 불가 (발견={bool(merge)}, "
                  f"화면안={merge[0]['on'] if merge else '-'})")
            # ── B. Shift+클릭 대안 ──
            print("\n[B] Shift+클릭 범위 선택 시도")
            await wp.mouse.click(b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2)
            await asyncio.sleep(0.4)
            await wp.keyboard.down("Shift")
            await wp.mouse.click(bl["x"] + bl["width"] / 2, bl["y"] + bl["height"] / 2)
            await wp.keyboard.up("Shift")
            await asyncio.sleep(1.2)
            st2 = await dump(t, "B. Shift+클릭 후")
            mg = [m for m in (st2.get("menu") or []) if "병합" in m["t"]]
            if mg and mg[0]["on"]:
                print(f"[B-C] '셀 병합' 클릭 @({mg[0]['x']},{mg[0]['y']})")
                await wp.mouse.click(mg[0]["x"] + 30, mg[0]["y"] + 10)
                await asyncio.sleep(1.2)
                await dump(t, "B-C. 병합 클릭 후")

        print("\n관찰 완료 — 브라우저는 20초 후 닫힘(눈으로 확인 가능)")
        await asyncio.sleep(20)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
