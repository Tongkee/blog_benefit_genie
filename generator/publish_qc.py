"""발행 직후 품질 게이트 (2026-07-23 신설, 2026-07-24 보완).

각 채널 발행 스크립트가 발행 성공 직후 호출 → 점검 기준(기호누출·소제목·상투어·이미지/표·
본문길이)을 자동 검사하고 data/qc_log.jsonl 에 기록. WP는 리터럴 마크다운·h4가 라이브에
남아있으면 self-heal(normalize 재PUT). 절대 발행을 막지 않는다(사후 점검·자가교정·로깅).

2026-07-24 보완:
- 네이버는 소스텍스트가 아니라 라이브(PostView 프로브)로 실측 → 에디터 렌더 실패(이미지/표 유실) 탐지.
- FAIL은 qc_fail.jsonl 로 분리(감시 쉽게) + qc_log 롤링(무한증가 방지).
- 이미지 0장·소제목 계층역전·본문 과소 경고 추가. 상투어 정규식에 해요체 변형 포함.
- (옵트인) QC_LLM_JUDGE=1 이면 캡션↔주제 의미 일치를 LLM으로 1콜 판정.

판정: FAIL=즉시 교정 대상(마커/h4/렌더유실), WARN=품질 저하, OK.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from generator.wp_html import normalize_residual_md, rendered_to_raw

logger = logging.getLogger("publish_qc")
KST = timezone(timedelta(hours=9))
_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_QC_LOG = os.path.join(_DATA, "qc_log.jsonl")
_QC_FAIL = os.path.join(_DATA, "qc_fail.jsonl")
_MAX_LINES = 800          # qc_log 롤링 상한(최근 N줄 유지)
_MAX_FAIL_LINES = 300

# 교과서체 종결 상투어 — '-합니다체'와 해요체 변형 모두(2026-07-24). '해야 합니다' 등 흔한 건 제외.
_CLICHE = re.compile(
    r"것이 (?:중요|좋)|게 좋(?:습니다|아요)|하시면 (?:됩니다|돼요)|도움이 (?:되(?:길|었)|돼요)|"
    r"기억하세요|이처럼|이로써|혁신적|극대화|탁월")
_MD_BULLET = re.compile(r"(?:^|\n|>)\*[ \t]+\S")


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def check_wp_html(html: str, expect_images: bool = False) -> tuple[list[tuple[str, str]], dict]:
    """WP 본문(content.rendered/raw) 점검. (issues, metrics)."""
    issues: list[tuple[str, str]] = []
    if "**" in html:
        issues.append(("FAIL", f"리터럴 마크다운 ** x{html.count('**')}"))
    if _MD_BULLET.search(html):
        issues.append(("FAIL", "미변환 마크다운 불릿 '* '"))
    if "[[" in html:
        issues.append(("FAIL", "위키링크 [[ 누출"))
    if re.search(r"\{\{.*?\}\}", html):
        issues.append(("WARN", "미변환 {{ }} 마커"))
    h4 = len(re.findall(r"<h[4-6]\b", html))
    if h4:
        issues.append(("FAIL", f"화이트리스트 이탈 h4+ x{h4}"))
    heads = len(re.findall(r"<h[23]\b", html))
    if heads > 18:
        issues.append(("WARN", f"소제목 과다 x{heads}"))
    # 계층 역전: 첫 h3가 첫 h2보다 앞(또는 h2가 아예 없음)
    m2, m3 = re.search(r"<h2\b", html), re.search(r"<h3\b", html)
    if m3 and (not m2 or m3.start() < m2.start()):
        issues.append(("WARN", "소제목 계층 역전(h2 없이 h3 시작)"))
    img = html.count("<img")
    if expect_images and img == 0:
        issues.append(("WARN", "이미지 0장(유실 의심)"))
    chars = len(_plain(html))
    if chars < 1500:
        issues.append(("WARN", f"본문 과소 {chars}자(생성 이상 의심)"))
    cl = len(_CLICHE.findall(html))
    if cl > 3:
        issues.append(("WARN", f"교과서체 상투어 x{cl}"))
    metrics = {"h2h3": heads, "h4plus": h4, "img": img,
               "table": html.count("<table"), "cliche": cl, "chars": chars}
    return issues, metrics


def check_naver_text(text: str, img_count: int | None = None,
                     table_count: int | None = None) -> tuple[list[tuple[str, str]], dict]:
    """네이버 본문 점검. 라이브 프로브면 img/table 개수를 함께 넘겨 유실 탐지."""
    issues: list[tuple[str, str]] = []
    if "**" in text:
        issues.append(("FAIL", f"리터럴 마크다운 ** x{text.count('**')}"))
    if "[[" in text:
        issues.append(("FAIL", "위키링크 [[ 누출"))
    if re.search(r"(?:^|\n)\*[ \t]+\S", text):
        issues.append(("WARN", "마크다운 불릿 '* '"))
    if "##" in text or re.search(r"(?:^|\n)#{1,6}\s", text):
        issues.append(("WARN", "마크다운 헤더 '#'"))
    if img_count == 0:
        issues.append(("FAIL", "이미지 0장(에디터 삽입 실패 의심)"))
    if len(text) < 800:
        issues.append(("WARN", f"본문 과소 {len(text)}자"))
    cl = len(_CLICHE.findall(text))
    if cl > 4:
        issues.append(("WARN", f"교과서체 상투어 x{cl}"))
    metrics = {"chars": len(text), "cliche": cl}
    if img_count is not None:
        metrics["img"] = img_count
    if table_count is not None:
        metrics["table"] = table_count
    return issues, metrics


def check_caption(text: str) -> tuple[list[tuple[str, str]], dict]:
    """스레드/단문 캡션 점검(마커 위주)."""
    issues: list[tuple[str, str]] = []
    for mk in ("**", "[[", "]]", "##"):
        if mk in text:
            issues.append(("FAIL", f"기호 누출 '{mk}'"))
    return issues, {"chars": len(text)}


def verdict(issues: list[tuple[str, str]]) -> str:
    if any(s == "FAIL" for s, _ in issues):
        return "FAIL"
    if any(s == "WARN" for s, _ in issues):
        return "WARN"
    return "OK"


def _append_rolling(path: str, rec: dict, cap: int) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 롤링: 상한 초과 시 최근 cap줄만 유지(가끔만 발생)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > cap * 1.25:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-cap:])
    except Exception as e:
        logger.warning(f"QC 로그 기록 실패({os.path.basename(path)}): {e}")


def record(channel: str, ident: str, issues: list[tuple[str, str]], metrics: dict,
           healed: bool = False) -> str:
    """qc_log.jsonl append(+FAIL이면 qc_fail.jsonl) + 로그 출력. 판정 반환."""
    v = verdict(issues)
    rec = {"ts": datetime.now(KST).isoformat(timespec="seconds"), "channel": channel,
           "id": ident, "verdict": v, "healed": healed,
           "issues": [f"{s}:{m}" for s, m in issues], "metrics": metrics}
    _append_rolling(_QC_LOG, rec, _MAX_LINES)
    if v == "FAIL" and not healed:
        _append_rolling(_QC_FAIL, rec, _MAX_FAIL_LINES)
    tag = {"OK": "✅", "WARN": "⚠️", "FAIL": "🔴"}.get(v, "?")
    detail = "; ".join(f"{s}:{m}" for s, m in issues) or "clean"
    logger.info(f"[QC {tag} {v}] {channel} {ident}{' (self-healed)' if healed else ''} — {detail}")
    return v


def qc_wp_live(wp_url: str, post_id: int, auth, channel: str, ident: str,
               heal: bool = True, expect_images: bool = False) -> str:
    """발행된 WP 글을 라이브로 재fetch(context=edit)→점검→FAIL(마커/h4)이면 self-heal 재PUT."""
    import requests
    base = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    try:
        r = requests.get(base, params={"context": "edit", "_fields": "content"},
                         auth=auth, timeout=45)
        content = r.json().get("content", {})
        raw = content.get("raw") or rendered_to_raw(content.get("rendered", ""))
    except Exception as e:
        logger.warning(f"[QC] 라이브 재fetch 실패 {channel} {ident}: {e}")
        return "ERROR"
    issues, metrics = check_wp_html(raw, expect_images=expect_images)
    healed = False
    if heal and any(s == "FAIL" for s, _ in issues) and (
            "**" in raw or _MD_BULLET.search(raw) or re.search(r"<h[4-6]\b", raw)):
        fixed = normalize_residual_md(raw)
        if fixed != raw:
            try:
                u = requests.post(base, json={"content": fixed}, auth=auth, timeout=45)
                if u.status_code in (200, 201):
                    healed = True
                    issues, metrics = check_wp_html(fixed, expect_images=expect_images)
                    logger.info(f"[QC] self-heal 완료 {channel} {ident}")
                else:
                    logger.warning(f"[QC] self-heal PUT 실패 {u.status_code}")
            except Exception as e:
                logger.warning(f"[QC] self-heal 오류: {e}")
    return record(channel, ident, issues, metrics, healed=healed)


def qc_naver_live(blog_id: str, logno: str) -> dict | None:
    """발행된 네이버 글을 PostView로 재접속해 렌더된 본문/이미지/표를 실측(공개글=로그인 불필요).

    소스텍스트 검사로는 못 잡는 '에디터 렌더 실패(이미지/표 유실)'를 탐지. 실패 시 None(폴백).
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={logno}"
    import time
    for attempt in range(2):
        # 발행 직후엔 PostView 전파 전이라 컨테이너가 안 잡혀 소스폴백만 됨 → 전파 대기(2026-07-27).
        time.sleep(6 if attempt == 0 else 10)
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                pg = b.new_page(viewport={"width": 430, "height": 900})
                pg.goto(url, wait_until="networkidle", timeout=30000)
                try:
                    pg.wait_for_selector(".se-main-container", timeout=10000)
                except Exception:
                    pass
                cont = pg.query_selector(".se-main-container")
                if not cont:
                    b.close()
                    if attempt == 0:
                        continue
                    return None
                out = {"text": cont.inner_text(),
                       "img": len(pg.query_selector_all(".se-main-container img")),
                       "table": len(pg.query_selector_all(".se-main-container table"))}
                b.close()
                return out
        except Exception as e:
            logger.warning(f"[QC] 네이버 라이브 프로브 실패({attempt}) {blog_id}/{logno}: {e}")
    return None


# self-heal 대상 리터럴(강조 마크다운) — 표 셀·요약 등 별도경로 누출분(2026-07-30)
_LIVE_MD_RE = re.compile(r"\*\*|(?<!_)__(?!_)|\[\[.+?\]\]")

# 편집 페이지에서 표 셀·문단의 리터럴만 제거하고 재타이핑하는 JS(SE 내부모델 반영 위해
# 실제로는 아래 파이썬이 셀 클릭·재입력을 하고, 이 JS는 '무엇을 고칠지' 목록만 뽑는다).
_LEAK_CELLS_JS = r"""() =>
  [...document.querySelectorAll('table td, table th')]
    .map((c,i) => ({i, t:(c.innerText||'')}))
    .filter(o => /\*\*|(?<!_)__(?!_)|\[\[.+?\]\]/.test(o.t))
    .map(o => ({i:o.i,
      clean:o.t.replace(/\[\[(.+?)\]\]/g,'$1').replace(/\*\*/g,'')
               .replace(/(?<!_)__(?!_)/g,'').trim()}))"""


def qc_naver_selfheal(blog_id: str, logno: str, cookies_path: str = "") -> bool:
    """발행된 네이버 글에 리터럴 마크다운(**·__·[[]])이 남아있으면 수정 에디터로 자동 정정.

    WP의 qc_wp_live self-heal에 대응하는 네이버판(2026-07-30 신설). 표 셀 별도 타이핑 경로가
    '**'를 못 벗겨 라이브 노출된 사고(info 보험 224362055349) 재발 시 스스로 고친다.
    PostUpdateForm 진입 → 리터럴 있는 표 셀을 실제 클릭·재타이핑 → _publish(수정발행).
    쿠키 필요(비공개/수정은 로그인). 실패해도 예외 안 냄(사후 자가교정, 발행 흐름 무영향).

    반환: 수정·발행을 실제로 수행했으면 True.
    """
    try:
        import json as _json
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    ck_path = cookies_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "naver_cookies.json")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    url = f"https://blog.naver.com/PostUpdateForm.naver?blogId={blog_id}&logNo={logno}"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True,
                                  args=["--disable-blink-features=AutomationControlled"])
            ctx = b.new_context(user_agent=ua, viewport={"width": 1280, "height": 900},
                                locale="ko-KR")
            try:
                ck = _json.load(open(ck_path, encoding="utf-8"))
                ctx.add_cookies(ck if isinstance(ck, list) else ck.get("cookies", []))
            except Exception:
                b.close()
                return False
            pg = ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(4500)
            # 표 셀이 있는 프레임 찾기
            frame = pg
            for fr in pg.frames:
                try:
                    if fr.locator("table td, table th").count():
                        frame = fr
                        break
                except Exception:
                    continue
            pre = frame.evaluate(r"()=>(document.body.innerText.match(/\*\*|__/g)||[]).length")
            if not pre:
                b.close()
                return False
            leaks = frame.evaluate(_LEAK_CELLS_JS)
            cells = frame.locator("table td, table th")
            for lc in leaks:
                try:
                    cells.nth(lc["i"]).click()
                    pg.wait_for_timeout(180)
                    pg.keyboard.press("Control+a")
                    pg.wait_for_timeout(80)
                    pg.keyboard.type(lc["clean"], delay=14)
                except Exception:
                    continue
            pg.wait_for_timeout(800)
            # 발행(수정완료) — 발행 버튼 직접 클릭 흐름(설정 패널 최소 조작)
            healed = False
            for sel in ("button:has-text('발행')", ".publish_btn", ".se-publish-btn"):
                try:
                    loc = frame.locator(sel).first
                    if loc.count() and loc.is_visible(timeout=1500):
                        loc.click(timeout=3000)
                        pg.wait_for_timeout(2500)
                        # 설정 패널 최종 확인
                        for cs in ("button:has-text('발행')", "button:has-text('확인')",
                                   "[class*='confirm']"):
                            try:
                                c2 = frame.locator(cs).last
                                if c2.count() and c2.is_visible(timeout=1500):
                                    c2.click(timeout=3000)
                                    break
                            except Exception:
                                continue
                        pg.wait_for_timeout(4000)
                        healed = "isAfterUpdate" in pg.url or "Redirect=View" in pg.url
                        break
                except Exception:
                    continue
            b.close()
            if healed:
                logger.info(f"[QC] 네이버 self-heal 완료 {blog_id}/{logno} (리터럴 {pre}개 제거)")
            return healed
    except Exception as e:
        logger.warning(f"[QC] 네이버 self-heal 오류(무시) {blog_id}/{logno}: {e}")
        return False


def qc_llm_relevance(subject: str, context: str, api_key: str = "") -> list[tuple[str, str]]:
    """(옵트인 QC_LLM_JUDGE=1) 캡션/제목이 상품·주제와 의미상 맞는지 LLM 1콜 판정.

    문법 게이트로 못 잡는 '훅↔상품 불일치'([073] 그라인더 사례) 감지용. 오탐 여지 있어 WARN만.
    """
    if os.environ.get("QC_LLM_JUDGE", "").strip() not in ("1", "true", "on"):
        return []
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not key or not subject or not context:
        return []
    try:
        from google import genai
        client = genai.Client(api_key=key)
        prompt = (f"상품/주제: {context}\n게시글 문구: {subject}\n\n"
                  "위 문구가 상품/주제와 의미상 맞나? 훅이 전혀 다른 소재를 말하면 불일치야.\n"
                  "첫 줄에 MATCH 또는 MISMATCH만, 둘째 줄에 12자 이내 이유.")
        r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        head = (r.text or "").strip().splitlines()
        if head and head[0].strip().upper().startswith("MISMATCH"):
            reason = head[1][:20] if len(head) > 1 else ""
            return [("WARN", f"훅↔주제 불일치 의심({reason})")]
    except Exception as e:
        logger.warning(f"[QC] LLM 심판 오류(무시): {e}")
    return []


def summarize(path: str = _QC_LOG, days: int = 1, silent_days: int = 2) -> str:
    """qc_log.jsonl 요약(최근 N일): 판정 카운트 + FAIL/WARN 목록 + ★침묵 채널 감지.

    침묵 감지: QC 로그는 '발행 성공' 시에만 쌓임 → 채널이 갑자기 로그를 안 남기면 토큰/쿠키
    만료·크론 중단으로 발행이 멈춘 신호(사후 조용한 실패). 이전엔 활동했는데 silent_days일 넘게
    로그가 없는 채널을 경고한다.
    """
    if not os.path.exists(path):
        return "(qc_log 없음)"
    all_rows = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            all_rows.append(json.loads(ln))
        except Exception:
            continue
    now = datetime.now(KST)
    cutoff = (now - timedelta(days=days)).isoformat()
    rows = [r for r in all_rows if r.get("ts", "") >= cutoff]
    from collections import Counter
    vc = Counter(r["verdict"] for r in rows)
    out = [f"[QC 요약 최근 {days}일] 총 {len(rows)}건 | OK {vc.get('OK', 0)} · WARN {vc.get('WARN', 0)} · FAIL {vc.get('FAIL', 0)}"]
    for r in rows:
        if r["verdict"] in ("FAIL", "WARN"):
            out.append(f"  {r['verdict']:4} {r['channel']:14} {str(r['id'])[:30]:30} {'; '.join(r['issues'])}")
    # 침묵 채널(발행 멈춤 의심) — 로그에 있었던 채널의 마지막 시각 기준
    last_seen: dict[str, str] = {}
    for r in all_rows:
        ch, ts = r.get("channel", ""), r.get("ts", "")
        if ts > last_seen.get(ch, ""):
            last_seen[ch] = ts
    silent_cut = (now - timedelta(days=silent_days)).isoformat()
    silent = sorted((ch, ts) for ch, ts in last_seen.items() if ts and ts < silent_cut)
    if silent:
        out.append(f"\n⚠️ 침묵 채널({silent_days}일+ 로그無 = 토큰/쿠키만료·크론중단 의심):")
        for ch, ts in silent:
            out.append(f"  🔕 {ch:16} 마지막 {ts[:16]}")
    return "\n".join(out)
