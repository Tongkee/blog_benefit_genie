# -*- coding: utf-8 -*-
"""'함께 보면 좋은 글' 내부링크 재연결 (2026-07-31 신설).

배경: 2026-07-31에 오류·중복 글 33건을 삭제했더니, 살아남은 글 47건의
'함께 보면 좋은 글' 링크카드 51개가 지워진 글을 가리키게 됐다. 링크가 죽는 것보다
나쁜 건 카드 미리보기에 '신혼부부 취득세 감면 최대 200만원'처럼 **폐지된 제도 문구가
그대로 노출**된다는 점이다.

방식: 지우기만 하면 내부링크의 회유·SEO 이점을 잃으므로 **현행 관련글로 교체**한다.
  수정 에디터 진입 → '함께 보면 좋은 글' 소제목 문단 끝에 커서 →
  Ctrl+Shift+End 로 그 뒤(링크카드 전체) 선택·삭제 → 새 URL 타이핑(네이버가 카드로 렌더)
  → 수정 발행 → 재조회 검증.
소제목 문단 자체는 남겨 회색바 서식(§5)을 보존한다.

사용: py -3 scripts/fix_related_links.py <plan.json> [--dry]
  plan.json: [{"logno":..., "urls":[...], "titles":[...]}]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from playwright.sync_api import sync_playwright  # noqa: E402

BLOG = os.environ.get("NAVER_BLOG_ID") or "benefit_genie"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
HEAD = "함께 보면 좋은 글"

# 소제목 문단을 찾아 그 끝으로 커서를 옮긴다(문단 자체는 보존)
FOCUS_JS = """
(head) => {
  const ps = [...document.querySelectorAll('p.se-text-paragraph')];
  const p = ps.find(x => (x.innerText || '').trim() === head);
  if (!p) return false;
  const r = document.createRange();
  r.selectNodeContents(p);
  r.collapse(false);              // 문단 끝
  const s = window.getSelection();
  s.removeAllRanges();
  s.addRange(r);
  p.scrollIntoView({block: 'center'});
  return true;
}
"""


def _dismiss_overlays(pg) -> None:
    """에디터 첫 진입 시 뜨는 '도움말' 패널 등을 닫는다.

    ★이걸 안 닫으면 발행 버튼 클릭이 가로막힌다 —
    '<h1 class="se-help-title">도움말</h1> ... intercepts pointer events'(2026-07-31 실측).
    """
    for sel in (".se-help-panel-close-button", "button.se-help-panel-close-button",
                ".se-popup-close-button", "button:has-text('닫기')",
                "[class*='help'] [class*='close']"):
        try:
            loc = pg.locator(sel).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=2000)
                pg.wait_for_timeout(400)
        except Exception:
            continue
    try:
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
    except Exception:
        pass


TAIL_JS = """
(head) => {
  const clean = s => (s || '').split('\\n').join(' ').replace(/  +/g, ' ').trim();
  const comps = [...document.querySelectorAll('.se-component')];
  const hi = comps.findIndex(c => clean(c.innerText).indexOf(head) >= 0);
  if (hi < 0) return -1;
  // 소제목 이후 컴포넌트 중 링크카드(oglink) 또는 네이버 URL만 든 것
  let n = 0;
  for (let i = hi; i < comps.length; i++) {
    const c = comps[i];
    const t = clean(c.innerText);
    const isCard = /oglink/i.test(c.className) || /blog\\.naver\\.com/.test(t);
    if (isCard) n++;
  }
  return n;
}
"""


def _delete_link_cards(pg) -> int:
    """링크카드(.se-component.se-oglink)를 하나씩 선택·삭제. 삭제 수 반환.

    ★셀렉터 주의: `.se-component` + has_text("blog.naver.com") 필터는 생 URL이 든
    **텍스트 컴포넌트까지 매칭**한다. 텍스트 컴포넌트를 Delete하면 본문이 통째로
    날아갈 수 있어 카드 전용 클래스(se-oglink)로 한정한다(2026-07-31 밤 수리)."""
    removed = 0
    for _ in range(15):
        cards = pg.locator(".se-component.se-oglink")
        if not cards.count():
            break
        try:
            card = cards.last
            card.scroll_into_view_if_needed(timeout=4000)
            card.click(timeout=4000)
            pg.wait_for_timeout(350)
            pg.keyboard.press("Delete")
            pg.wait_for_timeout(500)
            removed += 1
        except Exception:
            break
    return removed


# URL만 든 문단 탐색(생 URL 텍스트 오염 — 2026-07-31 낮 시도들이 남긴 것)
_URL_PARA_JS = """
() => {
  const ps = [...document.querySelectorAll('p.se-text-paragraph')];
  const i = ps.findIndex(p => {
    const t = (p.innerText || '').replace(/\\s+/g, '');
    return t && /^(https?:\\/\\/\\S+)+$/.test(t) && t.indexOf('blog.naver.com') >= 0;
  });
  if (i < 0) return null;
  ps[i].scrollIntoView({block: 'center'});
  return i;
}
"""


def _delete_raw_url_paras(pg) -> int:
    """생 URL만 든 문단을 줄 단위로 삭제(빈 줄까지 정리). 삭제 수 반환."""
    removed = 0
    for _ in range(20):
        idx = pg.evaluate(_URL_PARA_JS)
        if idx is None:
            break
        try:
            para = pg.locator("p.se-text-paragraph").nth(idx)
            para.click(timeout=4000)
            pg.keyboard.press("End")
            pg.keyboard.press("Shift+Home")
            pg.keyboard.press("Delete")
            pg.wait_for_timeout(250)
            pg.keyboard.press("Backspace")   # 빈 줄 제거(카드는 이미 지워 병합 안전)
            pg.wait_for_timeout(400)
            removed += 1
        except Exception:
            break
    return removed


def fix_one(pg, logno: str, urls: list) -> str:
    pg.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={BLOG}&logNo={logno}",
            wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(7000)
    _dismiss_overlays(pg)
    # ★SE ONE은 컴포넌트 단위 편집기다. 텍스트 문단에서 Ctrl+Shift+End를 눌러도
    # 선택이 컴포넌트 경계를 넘지 못해 링크카드가 안 지워진다(2026-07-31 실측).
    # → ①링크카드(se-oglink)를 하나씩 선택·삭제 ②생 URL 문단을 줄 단위 삭제.
    removed = _delete_link_cards(pg)
    raw_removed = _delete_raw_url_paras(pg)
    print(f"    카드 {removed}장 · 생URL 문단 {raw_removed}개 정리")
    pg.wait_for_timeout(500)
    # 소제목 문단으로 커서 — 이전 시도로 소제목이 사라진 글은 본문 끝에 다시 타이핑
    head_p = pg.locator("p.se-text-paragraph", has_text=HEAD).first
    try:
        if head_p.count():
            head_p.scroll_into_view_if_needed(timeout=5000)
            head_p.click(timeout=5000)
            pg.wait_for_timeout(400)
            pg.keyboard.press("End")
        else:
            last_p = pg.locator("p.se-text-paragraph").last
            last_p.scroll_into_view_if_needed(timeout=5000)
            last_p.click(timeout=5000)
            pg.wait_for_timeout(300)
            pg.keyboard.press("Control+End")
            pg.keyboard.press("Enter")
            pg.keyboard.type(HEAD, delay=25)
            pg.wait_for_timeout(300)
    except Exception as e:
        return f"커서 배치 실패({e.__class__.__name__})"
    pg.wait_for_timeout(300)
    # ★링크 삽입은 툴바 '링크 추가' 다이얼로그로만 한다. 본문에 URL을 타이핑하면
    # 카드가 생겨도 생 URL 텍스트가 함께 남는다(2026-07-31 실측).
    # 다이얼로그는 **커서가 본문 안에 있어야** 열린다(위에서 실클릭으로 보장) —
    # 셀렉터는 .se-toolbar-item-oglink button 이 정답(2026-07-31 밤 프로브 실측).
    for u in urls:
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(250)
        before = pg.locator(".se-component.se-oglink").count()
        clicked = False
        for sel in (".se-toolbar-item-oglink button", "button.se-oglink-toolbar-button"):
            try:
                pg.locator(sel).first.click(timeout=4000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            return "링크 버튼 클릭 실패"
        try:
            pg.wait_for_timeout(700)
            box = pg.locator("input.se-popup-oglink-input").first
            box.fill(u, timeout=5000)
            pg.wait_for_timeout(300)
            # ★Enter는 팝업 안 '미리보기'만 만든다 — 카드 삽입은 '확인' 버튼이 한다
            # (2026-07-31 밤 프로브 실측: Enter만으로는 카드 0, 확인 클릭 시 +1).
            box.press("Enter")
            pg.wait_for_timeout(1800)          # 미리보기(OG 메타) 로딩 대기
            pg.locator("button.se-popup-button-confirm").first.click(timeout=5000)
        except Exception as e:
            return f"링크 입력 실패({e.__class__.__name__})"
        made = False
        for _ in range(16):
            pg.wait_for_timeout(500)
            if pg.locator(".se-component.se-oglink").count() > before:
                made = True
                break
        if not made:
            return f"카드 미생성({u[-14:]})"
        pg.wait_for_timeout(800)
    pg.wait_for_timeout(900)
    _dismiss_overlays(pg)
    # 수정 발행
    for sel in ("button[class*='publish_btn']", "button:has-text('발행')", ".se-publish-btn"):
        try:
            loc = pg.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1500):
                loc.click(timeout=3000)
                pg.wait_for_timeout(2500)
                for cs in ("button:has-text('발행')", "button:has-text('확인')"):
                    try:
                        c2 = pg.locator(cs).last
                        if c2.count() and c2.is_visible(timeout=1500):
                            c2.click(timeout=3000)
                            break
                    except Exception:
                        continue
                pg.wait_for_timeout(5000)
                break
        except Exception:
            continue
    return "OK" if ("isAfterUpdate" in pg.url or "Redirect=View" in pg.url or
                    "PostView" in pg.url) else f"발행확인실패({pg.url[:60]})"


def verify_one(pg, logno: str, expect_cards: int) -> str:
    """수정 발행 후 재진입해 카드 수·생 URL 잔존을 실측 검증(2026-07-31 §5-4 원칙)."""
    pg.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={BLOG}&logNo={logno}",
            wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(7000)
    cards = pg.locator(".se-component.se-oglink").count()
    raw = pg.evaluate(_URL_PARA_JS)
    ok = cards == expect_cards and raw is None
    return (f"검증 {'OK' if ok else 'FAIL'} — 카드 {cards}/{expect_cards}"
            f" · 생URL {'없음' if raw is None else '잔존!'}")


def main():
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    dry = "--dry" in sys.argv
    print(f"대상 {len(plan)}건 (dry={dry})")
    if dry:
        for it in plan[:5]:
            print(f"  {it['logno']} -> {it['titles']}")
        return
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 900},
                            locale="ko-KR")
        ctx.add_cookies(json.load(open(os.path.join(ROOT, "data", "naver_cookies.json"),
                                       encoding="utf-8")))
        pg = ctx.new_page()
        pg.on("dialog", lambda d: d.accept())
        for i, it in enumerate(plan, 1):
            try:
                r = fix_one(pg, it["logno"], it["urls"])
                if r == "OK":
                    pg.wait_for_timeout(2500)
                    r = f"OK · {verify_one(pg, it['logno'], len(it['urls']))}"
            except Exception as e:
                r = f"오류 {e.__class__.__name__}"
            results[it["logno"]] = r
            print(f"[{i}/{len(plan)}] {it['logno']} {r}")
            pg.wait_for_timeout(5000)   # 과요청 방지 페이스
        b.close()
    out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "relink_result.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(1 for v in results.values() if str(v).startswith("OK"))
    print(f"\n성공 {ok} / 실패 {len(results) - ok}")


if __name__ == "__main__":
    main()
