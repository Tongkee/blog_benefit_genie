"""
형수의테크공장(hyungsutech, khj 계정) 쿠키 저장 — 1회 실행.
로컬에서: python scripts/get_cookies_tech.py

현지언니 get_cookies.py와 달리 자동 로그인 안 함 → 열린 브라우저에서
'직접' khj 계정으로 로그인(2단계 인증·캡챠 포함)하면 쿠키를 저장한다.
저장 후 안내대로 .env의 TECH_NAVER_COOKIES 및 GitHub Secret에 등록.
"""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR
from playwright.async_api import async_playwright

COOKIE_PATH = os.path.join(DATA_DIR, "tech_naver_cookies.json")


async def _wait_for_auth_cookie(ctx, timeout_sec: int = 240) -> bool:
    for _ in range(timeout_sec):
        cookies = await ctx.cookies()
        if "NID_AUT" in {c["name"] for c in cookies}:
            return True
        await asyncio.sleep(1)
    return False


async def main():
    async with async_playwright() as pw:
        browser = None
        for ch in ("chrome", "msedge", None):
            try:
                browser = await pw.chromium.launch(headless=False, channel=ch)
                print(f"[브라우저] {ch or 'bundled chromium'} 사용")
                break
            except Exception as e:
                print(f"[브라우저] {ch or 'chromium'} 실패: {str(e)[:70]}")
        if browser is None:
            print("[ERROR] 사용 가능한 브라우저 없음 (Chrome/Edge 설치 필요)")
            sys.exit(1)

        ctx = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ))
        page = await ctx.new_page()

        print("\n[1] 네이버 로그인 페이지를 엽니다.")
        print("    ★ 열린 창에서 '형수의테크공장(hyungsutech) 계정 = khj'로 직접 로그인하세요.")
        print("    ★ 2단계 인증/캡챠가 나오면 그대로 처리하면 됩니다. (최대 4분 대기)\n")
        await page.goto("https://nid.naver.com/nidlogin.login")

        success = await _wait_for_auth_cookie(ctx, timeout_sec=240)
        if success:
            print("[2] 로그인 완료! (NID_AUT 확인)")
            await asyncio.sleep(2)
        else:
            print("[경고] 4분 내 인증 쿠키 미확인 — 현재 상태로 저장 시도")

        cookies = await ctx.cookies()
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(COOKIE_PATH, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        names = [c["name"] for c in cookies]
        print(f"\n[완료] 쿠키 저장: {COOKIE_PATH}  (총 {len(cookies)}개)")

        if "NID_AUT" in names and "NID_SES" in names:
            print("[OK] 인증 쿠키 확인 완료.")
            print("\n다음 중 하나로 등록하세요:")
            print(f"  · 로컬 발행:  .env 에 아래 한 줄 추가 (파일 내용을 한 줄 JSON으로)")
            print(f"       TECH_NAVER_COOKIES=<{os.path.basename(COOKIE_PATH)} 내용>")
            print(f"  · 자동 발행:  GitHub Secret 'TECH_NAVER_COOKIES' 에 파일 내용 등록")
        else:
            print("[경고] 인증 쿠키 없음 — 로그인 실패 상태일 수 있음. 재실행 필요")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
