"""네이버 라이브 글 리터럴 마크다운(**·__) in-place 수리 + 재발행 (2026-07-30).

배경: 표 셀 등 별도 타이핑 경로가 '**'를 안 벗겨 라이브 노출(224362055349 표셀 6개).
게이트는 _strip_markers로 강화(다음 발행분부터 재발 없음)했고, '이미 나간 글'은 이 도구로 수리.
사용자 지적: "네이버도 수정하기 버튼 있으니 self-heal 가능하잖아, try 해봐." → 구현.

방식(표 전체 재삽입 X, 최소침습):
  PostUpdateForm 진입 → 에디터 프레임의 표 셀/문단 중 '**'·'__' 포함 요소를 찾아
  DOM 텍스트에서 리터럴만 제거(JS로 직접 치환) → 발행(수정완료).
  ※ 잦은 수정=누락 위험(카페 §10-3) 있으므로 '리터럴 있는 글만' 수리하고 1회로 끝낸다.

사용:
  DRY_RUN=1 python scripts/naver_repair_live.py <logNo>   # 진입·탐지만(발행 안 함)
  python scripts/naver_repair_live.py <logNo>             # 실제 수리·발행
"""
import asyncio
import os
import sys

sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from playwright.async_api import async_playwright  # noqa: E402
import poster.naver_blog as nb  # noqa: E402

BLOG_ID = os.environ.get("NAVER_BLOG_ID", "hyunji_unni")
DRY = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True")

# 라이브에서 제거할 리터럴(강조 마크다운). [[]]는 앞뒤 텍스트 유지하며 껍데기만.
# ★수정 에디터엔 .se-main-container가 없다(main=0). 편집영역 루트를 여러 후보로 잡고,
#   없으면 document.body 전체 텍스트노드를 순회한다(표 셀 td/th 포함).
STRIP_JS = r"""() => {
  const root = document.querySelector(
    '.se-main-container, [class*="se-content"], .se-viewer, .se-container') || document.body;
  if (!root) return {ok:false, reason:'no-root'};
  let changed = 0, before = 0;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    const t = n.nodeValue;
    if (!t) continue;
    const stars = (t.match(/\*\*/g)||[]).length + (t.match(/(?<!_)__(?!_)/g)||[]).length;
    if (!stars && !/\[\[.+?\]\]/.test(t)) continue;
    before += stars;
    let nt = t.replace(/\[\[(.+?)\]\]/g, '$1')
              .replace(/\*\*/g, '')
              .replace(/(?<!_)__(?!_)/g, '');
    if (nt !== t) { n.nodeValue = nt; changed++; }
  }
  return {ok:true, changed, before,
          after:(root.innerText.match(/\*\*/g)||[]).length};
}"""


async def find_editor_frame(page):
    """수정 에디터의 contenteditable 프레임을 잡는다(_get_editor_frame 보강)."""
    # 수정 에디터는 표 셀(td/th)이 있는 프레임이 편집영역. se-main-container 없을 수 있음.
    for _ in range(6):
        for frame in list(page.frames):
            try:
                if await frame.locator("table td, table th").count():
                    return frame
            except Exception:
                pass
        await asyncio.sleep(1.2)
    return page


async def main():
    logno = sys.argv[1] if len(sys.argv) > 1 else ""
    if not logno:
        print("사용법: python scripts/naver_repair_live.py <logNo>")
        return 1
    print(f"네이버 라이브 수리 {logno}{' [DRY_RUN]' if DRY else ''}")

    async with async_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                kw = dict(headless=DRY is False and False or False,
                          args=["--disable-blink-features=AutomationControlled"])
                kw["headless"] = False   # 수정은 항상 headed로 눈 확인
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
            return 1

        url = f"https://blog.naver.com/PostUpdateForm.naver?blogId={BLOG_ID}&logNo={logno}"
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4)
        await nb._dismiss_draft_popup(page)
        await asyncio.sleep(1.5)

        frame = await find_editor_frame(page)
        # 진단 — body 전체 기준(se-main-container 없음)
        pre = await frame.evaluate(
            r"""() => (document.body.innerText.match(/\*\*/g)||[]).length""")
        print(f"   수정 전 ** 개수: {pre}")
        if pre <= 0:
            print("   리터럴 없음(또는 컨테이너 못 찾음) — 수리 불필요/불가. 종료.")
            await asyncio.sleep(3)
            await browser.close()
            return 0

        if DRY:
            print("   [DRY_RUN] 실제 제거·발행 생략. 진입·탐지 성공 확인됨.")
            await asyncio.sleep(20)
            await browser.close()
            return 0

        # ── 리터럴 제거: DOM 텍스트노드 직접 치환은 SE 내부모델과 어긋날 수 있어,
        #    표 셀을 '실제로 클릭 → 전체선택 → 재타이핑'해 에디터 모델까지 반영시킨다. ──
        leak_cells = await frame.evaluate(r"""() =>
          [...document.querySelectorAll('table td, table th')]
            .map((c,i) => ({i, t:(c.innerText||'')}))
            .filter(o => /\*\*|(?<!_)__(?!_)|\[\[.+?\]\]/.test(o.t))
            .map(o => ({i:o.i,
              clean:o.t.replace(/\[\[(.+?)\]\]/g,'$1').replace(/\*\*/g,'')
                       .replace(/(?<!_)__(?!_)/g,'').trim()}))
        """)
        print(f"   수리 대상 표 셀 {len(leak_cells)}개")
        cells_loc = frame.locator("table td, table th")
        for lc in leak_cells:
            try:
                cell = cells_loc.nth(lc["i"])
                await cell.click()
                await asyncio.sleep(0.2)
                await page.keyboard.press("Control+a")
                await asyncio.sleep(0.1)
                await page.keyboard.type(lc["clean"], delay=15)
                print(f"      셀[{lc['i']}] → {lc['clean'][:26]}")
            except Exception as e:
                print(f"      셀[{lc['i']}] 재타이핑 실패: {str(e)[:50]}")
        await asyncio.sleep(1.0)
        remain = await frame.evaluate(r"()=>(document.body.innerText.match(/\*\*/g)||[]).length")
        print(f"   재타이핑 후 남은 **: {remain}")

        # ── 발행(수정완료): _publish 재사용(카테고리 미지정=기존 유지) ──
        try:
            res_url = await nb._publish(page, tags=None, draft=False, category="")
            print(f"   _publish 반환: {res_url}")
        except Exception as e:
            print(f"   _publish 예외: {e} — 발행 버튼 직접 클릭 폴백")
            for sel in ["button:has-text('발행')", ".publish_btn", ".se-publish-btn"]:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() and await loc.is_visible(timeout=1500):
                        await loc.click(timeout=3000)
                        await asyncio.sleep(2.5)
                        break
                except Exception:
                    continue

        await asyncio.sleep(4)
        print(f"\n   최종 URL: {page.url[:90]}")
        print("   ✅ 수리·발행 시도 완료. 15초 후 닫힘.")
        await asyncio.sleep(15)
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
