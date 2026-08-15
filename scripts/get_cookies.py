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


async def _wait_for_auth_cookie(ctx, timeout_sec: int = 120) -> bool:
    """NID_AUT 쿠키가 생길 때까지 폴링 (로그인 완료 신호)"""
    for _ in range(timeout_sec):
        cookies = await ctx.cookies()
        names = {c["name"] for c in cookies}
        if "NID_AUT" in names:
            return True
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
        # ID/PW 자동 입력 — 실패해도 수동 로그인으로 진행(네이버 폼 구조 변경 대비, 2026-07-29)
        for sel, val in (("#id", NAVER_ID), ("#pw", NAVER_PW)):
            try:
                await page.locator(sel).fill(val, timeout=5000)
                await page.wait_for_timeout(400)
            except Exception:
                print(f"    (입력 실패 {sel} — 브라우저에서 직접 입력해 주세요)")

        print("[2] 로그인 버튼 클릭...")
        # 셀렉터가 자주 바뀜 → 여러 후보 + Enter 폴백. 전부 실패해도 수동 로그인 대기로 넘어간다.
        clicked = False
        for sel in ("button[type='submit'].btn_login", "#log\\.login",
                    "button.btn_login", "[data-testid='login-button']",
                    "button:has-text('로그인')", "input[type='submit']"):
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=4000)
                    clicked = True
                    print(f"    로그인 버튼 클릭: {sel}")
                    break
            except Exception:
                continue
        if not clicked:
            try:
                await page.locator("#pw").press("Enter")
                clicked = True
                print("    (버튼 못 찾음 — Enter로 제출 시도)")
            except Exception:
                print("    (자동 제출 실패 — 브라우저에서 직접 로그인해 주세요)")

        print("[3] 로그인 완료 대기 중... (최대 180초)")
        print("    ★캡챠·2단계 인증·자동입력 실패 시 브라우저에서 직접 로그인하면 됩니다")

        success = await _wait_for_auth_cookie(ctx, timeout_sec=180)

        if not success:
            print("[경고] 120초 내 인증 쿠키 미확인 - 현재 상태로 저장 시도")
        else:
            print("[3] 로그인 완료! (NID_AUT 확인)")
            await asyncio.sleep(2)  # 쿠키 완전 세팅 대기

        # 쿠키 저장
        cookies = await ctx.cookies()
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        names = [c["name"] for c in cookies]
        print(f"\n[완료] 쿠키 저장: {COOKIE_PATH}")
        print(f"       총 {len(cookies)}개: {names}")

        if "NID_AUT" in names and "NID_SES" in names:
            print("\n[OK] 인증 쿠키 확인 완료 - 정상 저장됨")
            print("data/naver_cookies.json 파일 내용을 GitHub Secret 'NAVER_COOKIES'에 등록하세요")
        else:
            print("\n[경고] 인증 쿠키 없음 - 로그인 실패 상태일 수 있음. 재실행 필요")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
