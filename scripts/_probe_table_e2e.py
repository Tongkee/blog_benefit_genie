"""표 꾸미기 E2E 검증 — 실제 발행 함수(_insert_table/_insert_faq_table)로 렌더 확인.

probe(_probe_table_style/_probe_table_merge)는 '개별 조작이 되는가'를 봤고,
이 스크립트는 '발행 코드에 배선된 상태로 실제 표가 제대로 나오는가'를 본다.
발행하지 않고 에디터 상태만 검사(임시저장도 안 함) — 관측 후 브라우저만 닫는다.

검사 항목:
  ① 일반 표: 헤더행 배경색이 실제 적용됐나(computedStyle)
  ② FAQ 표: 첫 행 병합(colspan) + 헤더 색
  ③ 셀 내용이 밀리거나 유실되지 않았나(행/열 수, 첫 행 텍스트)

실행: python -m scripts._probe_table_e2e
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

TABLE_STATE = """() => {
  const ts = document.querySelectorAll('table');
  const t = ts[ts.length-1]; if (!t) return null;
  const hex = c => { const m = (c||'').match(/\\d+/g); return m && m.length>=3 ?
    '#' + m.slice(0,3).map(x => (+x).toString(16).padStart(2,'0')).join('') : c; };
  return {
    tables: ts.length,
    rows: [...t.querySelectorAll('tr')].map(r => ({
      cells: r.children.length,
      colspans: [...r.children].map(c => c.getAttribute('colspan')||'1').join('/'),
      bg: [...r.children].map(c => hex(getComputedStyle(c).backgroundColor)).join(' '),
      text: [...r.children].map(c => (c.innerText||'').trim().slice(0,18)).join(' | '),
    })),
  };
}"""


async def show(t, label):
    st = await t.evaluate(TABLE_STATE)
    print(f"\n══ {label} ══")
    if not st:
        print("   (표 없음)")
        return None
    print(f"   표 {st['tables']}개")
    for i, r in enumerate(st["rows"]):
        print(f"   {i}행 셀{r['cells']} colspan[{r['colspans']}] bg[{r['bg']}]")
        print(f"        텍스트: {r['text']}")
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
                break
            except Exception:
                continue
        if not browser:
            print("브라우저 실행 실패")
            return
        ctx = await browser.new_context(user_agent=nb._UA, viewport={"width": 1280, "height": 900},
                                        locale="ko-KR")
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        await nb._load_cookies(ctx, "")
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
        t = await nb._get_editor_frame(wp)

        # ── ① 일반 표(_insert_table): 헤더 배경색 배선 확인 ──
        await wp.keyboard.type("표 E2E 검증")
        await wp.keyboard.press("Enter")
        await nb._delay(400, 700)
        print("\n[①] _insert_table 호출 (3열 표 + 헤더 배경색)")
        await nb._insert_table(wp, "구분 | 대상 | 지원금액\n청년 | 만19~34세 | 월 20만원\n신혼 | 7년이내 | 월 30만원",
                               "표 E2E 검증")
        await asyncio.sleep(1.5)
        st1 = await show(t, "① 일반 표 결과")

        # ── ② FAQ 표(_insert_faq_table): 병합 + 색 ──
        # 앵커는 '에디터에 이미 있는 단락 텍스트'여야 _move_cursor_after_text가 찾는다.
        # (앞 회차 실패 원인: Enter로 새 줄만 만들고 앵커 문구를 확정하지 못함)
        # ★표 밖으로 커서 빼기: Control+End는 표 안 마지막 셀에 머무를 수 있어(실측) 표 셀에
        # 텍스트가 들어갔다. Escape로 표 편집 종료 후 문서 끝으로 이동한다.
        await wp.keyboard.press("Escape")
        await nb._delay(300, 500)
        await wp.keyboard.press("Control+End")
        await nb._delay(300, 500)
        in_table = await t.evaluate("""() => {
          const s = document.getSelection(); if (!s || !s.anchorNode) return false;
          let n = s.anchorNode; while (n) { if (n.tagName === 'TABLE') return true; n = n.parentElement; }
          return false;
        }""")
        if in_table:
            print("   (커서가 표 안 — 아래쪽 빈 단락으로 이동 시도)")
            await wp.keyboard.press("Escape")
            await wp.keyboard.press("Control+End")
            await nb._delay(300, 500)
        await wp.keyboard.press("Enter")
        await wp.keyboard.type("FAQ 검증 앵커")
        await wp.keyboard.press("Enter")
        await wp.keyboard.type("(아래에 FAQ 박스가 들어갑니다)")
        await nb._delay(700, 1000)
        print("\n[②] _insert_faq_table 호출 (1열 박스 + 병합 + 색)")
        ok = await nb._insert_faq_table(
            wp,
            [("실업급여는 언제 신청하나요?", "퇴직 다음 날부터 12개월 이내에 신청해야 해요."),
             ("자진 퇴사도 받을 수 있나요?", "정당한 사유가 인정되면 가능해요.")],
            "FAQ 검증 앵커")
        print(f"   _insert_faq_table 반환: {ok}")
        await asyncio.sleep(1.5)
        st2 = await show(t, "② FAQ 표 결과")

        # ── 판정 ──
        print("\n══ 판정 ══")
        if st1:
            hdr_colored = st1["rows"][0]["bg"] not in ("", None) and "#ffffff" not in st1["rows"][0]["bg"]
            print(f"   ① 일반표 헤더 채색: {'✅' if hdr_colored else '❌'} ({st1['rows'][0]['bg']})")
            print(f"   ① 행/열 유지: {len(st1['rows'])}행 (내용 밀림 없어야)")
        if st2:
            merged = any(int(c) > 1 for c in st2["rows"][0]["colspans"].split("/")
                         if c.isdigit()) or st2["rows"][0]["cells"] == 1
            print(f"   ② FAQ 첫행 병합: {'✅' if merged else '❌'} (colspan {st2['rows'][0]['colspans']})")
            print(f"   ② FAQ 헤더 채색: {st2['rows'][0]['bg']}")

        print("\n25초 후 닫힘(눈으로 확인). 발행/임시저장 안 함.")
        await asyncio.sleep(25)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
