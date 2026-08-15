"""라이브 네이버 블로그 글 본문 추출 프로브 (untracked 로컬 검증 도구).
공개 글은 PostView.naver 직접 접근으로 iframe 없이 본문 텍스트를 뽑는다.
사용: python scripts/_probe_live_post.py 224338391607 224338289614 ...
"""
import io
import sys
from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BLOG_ID = "hyunji_unni"


def probe(logno: str, page):
    url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={logno}"
    page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        page.wait_for_selector(".se-main-container", timeout=10000)
    except Exception:
        pass
    body = page.eval_on_selector(
        ".se-main-container",
        "el => el.innerText",
    ) if page.query_selector(".se-main-container") else "(본문 컨테이너 없음)"
    imgs = page.query_selector_all(".se-main-container img")
    print(f"\n{'='*70}\nlogNo {logno}  |  이미지 {len(imgs)}개  |  {len(body)}자\n{'='*70}")
    print(body)


def main(lognos):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 430, "height": 900})
        for ln in lognos:
            try:
                probe(ln, page)
            except Exception as e:
                print(f"\n[ERROR] {ln}: {e}")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["224338391607"])
