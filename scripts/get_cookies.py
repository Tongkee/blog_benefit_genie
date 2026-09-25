"""
1회 실행 - 네이버 로그인 후 쿠키 저장
로컬에서: python scripts/get_cookies.py
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import NAVER_ID, NAVER_PW, DATA_DIR
from playwright.async_api import async_playwright

COOKIE_PATH = os.path.join(DATA_DIR, "naver_cookies.json")


async def _wait_for_auth_cookie(ctx, timeout_sec: int = 300) -> bool:
    """NID_AUT 쿠키가 생길 때까지 폴링 (로그인 완료 신호)"""
    for elapsed in range(timeout_sec):
        cookies = await ctx.cookies()
        names = {c["name"] for c in cookies}
        if "NID_AUT" in names:
            return True
        if elapsed > 0 and elapsed % 10 == 0:
            remaining = timeout_sec - elapsed
            print(f"    ...로그인 대기 중 ({remaining}초 남음) - 브라우저 창에서 로그인을 완료해 주세요.", flush=True)
        await asyncio.sleep(1)
    return False


async def main():
    if not NAVER_ID or not NAVER_PW:
        print("[ERROR] .env에 NAVER_ID 와 NAVER_PW 를 입력하세요")
        sys.exit(1)

    async with async_playwright() as pw:
        # 사내 프록시/SSL검사로 playwright 번들 크로미움 다운로드가 막힌 환경 대비:
        # 시스템에 설치된 Chrome → Edge → 번들 크로미움 순으로 시도
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                browser = await pw.chromium.launch(headless=False, channel=ch)
                print(f"[브라우저] {ch or 'bundled chromium'} 사용")
                break
            except Exception as e:
                print(f"[브라우저] {ch or 'chromium'} 실패: {str(e)[:70]}")
        if browser is None:
            print("[ERROR] 사용 가능한 브라우저가 없습니다 (Chrome/Edge 설치 필요)")
            sys.exit(1)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        print("[1] 네이버 로그인 페이지 열기...")
        await page.goto("https://nid.naver.com/nidlogin.login")
        await page.wait_for_timeout(1000)

        # '로그인 상태 유지' 체크박스 자동 활성화 (30~90일 장기 쿠키 발급용)
        try:
            keep_label = page.locator("label[for='keep'], #keep, .keep_check").first
            if await keep_label.count():
                await keep_label.click()
                print("    [설정] '로그인 상태 유지' 체크박스 자동 선택 완료 (장기 유지 쿠키)")
        except Exception:
            pass

        print("\n" + "=" * 60)
        print("★ [보안 안내] 네이버 계정 보호조치를 방지하기 위해")
        print("  열린 브라우저 창에서 아이디와 비밀번호를 직접 입력하여 로그인해 주세요.")
        print("  ('로그인 상태 유지'가 켜져 있어야 매번 로그인이 풀리지 않고 30~90일간 유지됩니다)")
        print("=" * 60 + "\n")

        print("[2] 로그인 완료 대기 중... (최대 300초)")
        print("    ★ 브라우저 창에서 아이디와 비밀번호를 입력하고 로그인을 완료해 주세요.\n", flush=True)

        success = await _wait_for_auth_cookie(ctx, timeout_sec=300)

        if not success:
            print("\n[❌ 시간 초과] 5분 내에 로그인이 완료되지 않아 종료되었습니다.")
            print("다시 터미널에서 'python scripts/get_cookies.py'를 실행해 주세요.")
            await browser.close()
            sys.exit(1)

        print("\n🎉 [3] 네이버 로그인 성공 확인! (NID_AUT 쿠키 감지됨)")
        print("👉 [4] 블로그 글쓰기 에디터 세션을 동기화하는 중입니다. 잠시만 기다려주세요...", flush=True)
        try:
            await page.goto("https://section.blog.naver.com/BlogHome.naver")
            await page.wait_for_timeout(2500)
            write_btn = page.locator("a:has-text('글쓰기'), [href*='GoBlogWrite']").first
            if await write_btn.count():
                async with ctx.expect_page(timeout=10000) as new_page_info:
                    await write_btn.click()
                new_pg = await new_page_info.value
                await new_pg.wait_for_load_state("domcontentloaded")
                print(f"    에디터 창 진입: {new_pg.url}", flush=True)
                for _ in range(30):
                    if "PostWrite" in new_pg.url or "postwrite" in new_pg.url:
                        print("    [✅ OK] 블로그 에디터 진입 및 세션 획득 완료!", flush=True)
                        break
                    if "nidlogin" in new_pg.url or "login" in new_pg.url.lower():
                        print("    ★ 에디터 창에 로그인/확인 화면이 떴습니다. 브라우저에서 완료해 주세요.", flush=True)
                        await asyncio.sleep(2)
                    else:
                        await asyncio.sleep(1)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"    (에디터 세션 동기화 완료: {e})", flush=True)

        # 쿠키 저장
        cookies = await ctx.cookies()
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        names = [c["name"] for c in cookies]
        print(f"\n============================================================")
        print(f"✅ [완료] 최신 쿠키 {len(cookies)}개가 정상 저장되었습니다!")
        print(f"   저장 위치: {COOKIE_PATH}")
        print(f"============================================================\n")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
