"""네이버 라이브 글 '수정하기' 진입 가능성 probe (읽기·관측만, 발행 안 함).

배경: 2026-07-30 사용자 지적 — "네이버 self-heal이 기술적으로 불가한 게 아니라
우리가 안 만든 것 아니냐, 수정하기 버튼 되잖아. try 해봤냐."
→ 실제로 수정 에디터에 진입해 표 셀(** 누출분)에 접근되는지까지만 확인한다.

진입 경로 후보:
  A. https://blog.naver.com/PostUpdateForm.naver?blogId=..&logNo=..  (구형 수정폼)
  B. PostView에서 '수정하기' 링크/버튼 클릭
관측: 에디터 프레임 잡히는지 → .se-main-container 편집가능한지 → 표 셀에 ** 있는지.

사용: python scripts/_probe_naver_edit.py <logNo>
"""
import asyncio
import json
import os
import sys

sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright  # noqa: E402
import poster.naver_blog as nb  # noqa: E402

BLOG_ID = "hyunji_unni"


async def main():
    logno = sys.argv[1] if len(sys.argv) > 1 else "224362055349"
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
        ctx = await browser.new_context(user_agent=nb._UA, viewport={"width": 1280, "height": 900},
                                        locale="ko-KR")
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        print(f"[쿠키] {await nb._load_cookies(ctx, '')}")
        if not await nb._is_logged_in(page):
            print("❌ 로그인 실패 — 쿠키 갱신 필요")
            await browser.close()
            return

        # ── 방법 A: PostUpdateForm 직접 진입 ──
        url = f"https://blog.naver.com/PostUpdateForm.naver?blogId={BLOG_ID}&logNo={logno}"
        print(f"\n[A] 수정폼 직접: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(4)
            print(f"   최종 URL: {page.url[:90]}")
        except Exception as e:
            print(f"   goto 실패: {e}")

        await nb._dismiss_draft_popup(page)
        await asyncio.sleep(1.5)

        # 에디터 프레임·본문 접근 확인
        frame = await nb._get_editor_frame(page)
        info = {}
        try:
            info = await frame.evaluate("""() => {
              const main = document.querySelector('.se-main-container');
              const cells = document.querySelectorAll('table td, table th, .se-cell [contenteditable]');
              const body = main ? (main.innerText||'') : '';
              return {
                hasMain: !!main,
                editable: main ? main.closest('[contenteditable]') !== null
                                 || document.querySelectorAll('[contenteditable=true]').length > 0 : false,
                cellCount: cells.length,
                starHits: (body.match(/\\*\\*/g)||[]).length,
                bodyLen: body.length,
                sample: body.slice(0, 120)
              };
            }""")
        except Exception as e:
            info = {"err": str(e)[:80]}
        print(f"   에디터 진입: main={info.get('hasMain')} editable={info.get('editable')} "
              f"셀={info.get('cellCount')} **={info.get('starHits')} 본문{info.get('bodyLen')}자")
        print(f"   미리보기: {info.get('sample','')}")
        if info.get("err"):
            print(f"   (프레임 오류: {info['err']})")

        # 표 셀 중 ** 포함 셀 위치 덤프(수정 대상 확인)
        try:
            leaks = await frame.evaluate("""() =>
              [...document.querySelectorAll('table td, table th')]
                .map((c,i) => ({i, t:(c.innerText||'').trim().slice(0,30)}))
                .filter(o => o.t.includes('**'))
            """)
            if leaks:
                print(f"\n   ★ ** 포함 표 셀 {len(leaks)}개:")
                for lk in leaks:
                    print(f"      셀[{lk['i']}] {lk['t']}")
        except Exception:
            pass

        print("\n관찰 완료 — 25초 후 닫힘(수정·발행 안 함). 눈으로 에디터 확인.")
        await asyncio.sleep(25)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
