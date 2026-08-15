"""SE ONE 표 꾸미기 관측 probe — 표 스타일·셀 배경색 (2026-07-29 사용자 지시).

셀 병합 돌파(_merge_row_cells)와 같은 원리로 접근한다:
  "드래그로 셀을 선택하면 컨텍스트 메뉴·서식 툴바가 정상 좌표로 들어온다"

관측 목표:
  A. 표 삽입 시 '표 스타일' 팔레트가 있는가 (SE ONE 표 디자인 프리셋)
  B. 셀 드래그 선택 후 배경색(형광펜/셀 색) 버튼·팔레트가 화면 안에 오는가
  C. 실제로 색을 적용하면 DOM(style/background-color)에 반영되는가
전부 좌표·DOM 값으로 남겨서 '어디까지 되는지'를 사실로 확정한다.

실행: python -m scripts._probe_table_style   (headed, 네이버 쿠키 필요)
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

# 화면에 보이는 '표/색/스타일' 관련 버튼 전수 덤프
BTN_DUMP = """() => {
  const hit = /color|배경|색|style|스타일|형광|table|표|테마|theme|palette/i;
  return [...document.querySelectorAll('button,[role=button],li,a')]
    .filter(b => b.offsetParent)
    .map(b => {
      const r = b.getBoundingClientRect();
      const s = (b.getAttribute('aria-label')||'')+'|'+(b.getAttribute('data-name')||'')+'|'
              + (b.getAttribute('data-value')||'')+'|'+(b.className||'')+'|'+(b.textContent||'').trim();
      return {s: s.slice(0,90), x:Math.round(r.x), y:Math.round(r.y),
              w:Math.round(r.width), on: r.x>0&&r.y>0&&r.width>0&&r.x<1400};
    })
    .filter(o => hit.test(o.s) && o.on)
    .slice(0, 40);
}"""

CELL_STYLE_JS = """() => {
  const ts = document.querySelectorAll('table');
  const t = ts[ts.length-1]; if (!t) return null;
  return [...t.querySelectorAll('tr')].map(r =>
    [...r.children].map(c => {
      const cs = getComputedStyle(c);
      return {bg: cs.backgroundColor, cls:(c.className||'').slice(0,30),
              st:(c.getAttribute('style')||'').slice(0,50)};
    }));
}"""


async def dump_btns(t, page, label):
    print(f"\n── {label} ──")
    seen = set()
    for fr in (t, page):
        try:
            for b in await fr.evaluate(BTN_DUMP):
                key = b["s"][:50]
                if key in seen:
                    continue
                seen.add(key)
                print(f"   @({b['x']:>4},{b['y']:>4}) {b['s'][:78]}")
        except Exception as e:
            print(f"   (덤프 실패: {e})")


async def dump_cells(t, label):
    st = await t.evaluate(CELL_STYLE_JS)
    print(f"\n── {label} (셀 배경) ──")
    for i, row in enumerate(st or []):
        print(f"   {i}행: " + " | ".join(f"{c['bg']}" for c in row))


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

        await wp.keyboard.type("표 스타일 프로브")
        await wp.keyboard.press("Enter")
        t = await nb._get_editor_frame(wp)

        # ── A. 표 삽입 직전/직후 '표 스타일' UI 유무 ──
        await dump_btns(t, wp, "A-1. 표 삽입 전 툴바")
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
        await dump_btns(t, wp, "A-2. 표 삽입 직후 (표 스타일 팔레트 있나)")
        await dump_cells(t, "A-3. 삽입 직후")

        await t.evaluate(DISABLE_OVERLAY)

        # ── B. 첫 행 드래그 선택 후 서식 UI ──
        cells = t.locator("table tr:first-child td, table tr:first-child th")
        n = await cells.count()
        if n >= 2:
            b0 = await cells.nth(0).bounding_box()
            bl = await cells.nth(n - 1).bounding_box()
            print(f"\n[B] 첫 행 드래그 선택 ({n}칸)")
            await wp.mouse.move(b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2)
            await wp.mouse.down()
            for i in range(1, 13):
                await wp.mouse.move(b0["x"] + (bl["x"] - b0["x"]) * i / 12 + bl["width"] / 2,
                                    b0["y"] + b0["height"] / 2, steps=1)
                await asyncio.sleep(0.04)
            await wp.mouse.up()
            await asyncio.sleep(1.0)
            await dump_btns(t, wp, "B-1. 드래그 선택 후 (배경색 버튼 화면 안?)")

            # ── C. 배경색 버튼 클릭 → 팔레트 관측 ──
            for sel in ("[data-name='cell-background-color']",
                        ".se-cell-background-color-toolbar-button",
                        ".se-toolbar-item-cell-background-color"):
                try:
                    for fr in (t, wp):
                        loc = fr.locator(sel).first
                        if await loc.count() and await loc.is_visible(timeout=800):
                            await loc.click(timeout=2000)
                            print(f"\n[C] 배경색 버튼 클릭: {sel}")
                            await asyncio.sleep(1.0)
                            await dump_btns(t, wp, "C-1. 셀 배경색 팔레트 열림?")
                            # 팔레트 색 스와치 덤프 → 첫 유효 색 클릭
                            sw = await t.evaluate("""() =>
                              [...document.querySelectorAll('[data-value],[data-color],.se-color-item,button')]
                                .filter(e => e.offsetParent)
                                .map(e => { const r=e.getBoundingClientRect();
                                  return {v:(e.getAttribute('data-value')||e.getAttribute('data-color')||''),
                                          cls:(e.className||'').slice(0,40),
                                          x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width)}; })
                                .filter(o => o.v && /^#[0-9a-f]{6}$/i.test(o.v) && o.w>0 && o.x>0
                             && /se-color-palette|se-color-swatches/.test(o.cls)).slice(0,25)
                            """)
                            print(f"   [스와치 {len(sw)}개]")
                            for o in sw[:14]:
                                print(f"      {o['v']:<12} @({o['x']},{o['y']}) {o['cls'][:32]}")
                            if sw:
                                pick = sw[min(3, len(sw)-1)]   # 파스텔 색 하나
                                print(f"   → 색 클릭: {pick['v']} @({pick['x']},{pick['y']})")
                                await wp.mouse.click(pick['x']+5, pick['y']+5)
                                await asyncio.sleep(1.0)
                            raise StopIteration
                except StopIteration:
                    break
                except Exception:
                    continue
            await dump_cells(t, "C-2. 색 적용 시도 후")

        print("\n관찰 완료 — 20초 후 닫힘")
        await asyncio.sleep(20)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
