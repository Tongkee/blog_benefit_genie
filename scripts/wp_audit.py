# -*- coding: utf-8 -*-
"""WP·Blogger 발행글 전수 품질 감사 (읽기 전용 — 수정·삭제 없음).

대상:
  ① tech.hyunjiunni.com  (형수테크 WP)      — REST
  ② soyu.hyunjiunni.com  (소유의 발품노트)   — Blogger JSON 피드
  ③ hyunjiunni.com       (현지언니 WP)      — REST 최근 30글

검출기: 빈 표 / 마커 리터럴 / 이미지 결손(0장·깨진 src) / 반말 혼입(quality.find_banmal_sentences)
       / h2·h3 부재 통짜 본문 / 중복·유사 제목 쌍 / 소유: data-slot 결손·제목-본문 불일치(어제 리터치)
       / 형수테크: 본문 이미지 0장 목록
"""
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generator"))
from quality import find_banmal_sentences  # noqa: E402

# Windows cp949 콘솔에서 '—'·이모지 print 시 UnicodeEncodeError → UTF-8 강제(이식성).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 회사 PC 등 사내 프록시(MITM)에서 Python이 프록시 CA를 못 믿어 SSL 검증 실패(curl은 통과).
# 읽기전용 감사(자기 소유 공개 블로그)라 AUDIT_INSECURE_SSL=1이면 검증 우회(기본은 검증 유지).
if os.environ.get("AUDIT_INSECURE_SSL") == "1":
    import ssl as _ssl
    _ssl._create_default_https_context = _ssl._create_unverified_context

# 감사 결과 저장 위치 — PC 이식성 위해 레포 로컬(.audit_out, gitignore 권장). env로 override 가능.
SCRATCH = os.environ.get("AUDIT_OUT_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".audit_out")
os.makedirs(SCRATCH, exist_ok=True)
OUT_PATH = os.path.join(SCRATCH, "wp_audit_result.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) qa-audit/1.0"}
DELAY = 0.5
YESTERDAY = "2026-07-27"
TODAY = "2026-07-28"

# ── HTTP ─────────────────────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 40) -> str:
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


_head_cache: dict[str, int] = {}

def head_status(url: str) -> int:
    """이미지 src 상태코드. 404/410 = 깨짐. -1 = 네트워크 오류."""
    if url in _head_cache:
        return _head_cache[url]
    time.sleep(DELAY)
    st = -1
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as r:
            st = r.status
    except urllib.error.HTTPError as e:
        st = e.code
        if st == 405:  # HEAD 미지원 서버 → GET 폴백
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    st = r.status
            except urllib.error.HTTPError as e2:
                st = e2.code
            except Exception:
                st = -1
    except Exception:
        st = -1
    _head_cache[url] = st
    return st


# ── HTML 파싱 헬퍼 ────────────────────────────────────────────────────────────

TABLE_RE = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)
CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_RE = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
H23_RE = re.compile(r"<h[23]\b", re.IGNORECASE)
DATA_SLOT_A_RE = re.compile(r"<a\b[^>]*data-slot[^>]*>(.*?)</a>", re.DOTALL | re.IGNORECASE)
SHOP_IMG_HOST_RE = re.compile(r"(shopping-phinf\.pstatic\.net|shop-phinf|phinf\.pstatic\.net)", re.IGNORECASE)

# 렌더 안 된 마커·마크다운 리터럴 (텍스트 기준)
MARKER_RES: list[tuple[str, re.Pattern]] = [
    ("[사진N] 마커", re.compile(r"\[사진\s*\d*\]?")),
    ("[표시작/표끝] 마커", re.compile(r"\[표(시작|끝)\]?")),
    ("[상품링크N] 마커", re.compile(r"\[상품링크\s*\d*\]?")),
    ("[FAQ] 마커", re.compile(r"\[FAQ(시작|끝)\]?")),
    ("[구분선] 마커", re.compile(r"\[구분선\]")),
    ("[가운데] 마커", re.compile(r"\[가운데\]")),
    ("{{ 템플릿 리터럴", re.compile(r"\{\{")),
    ("** 마크다운 볼드", re.compile(r"\*\*[^\n*]{1,60}\*\*|\*\*")),
    ("## 마크다운 헤딩", re.compile(r"^#{2,4}\s", re.MULTILINE)),
]

STOP_TOKENS = {
    "2024", "2025", "2026", "방법", "총정리", "정리", "가이드", "추천", "비교",
    "후기", "순위", "최신", "기준", "완벽", "꿀팁", "확인", "신청", "조건",
    "정보", "하는", "위한", "제대로", "안내", "및", "그리고", "까지", "부터",
    "top", "best", "vs", "리뷰", "장단점", "차이", "이유", "핵심",
}


def strip_tags(s: str) -> str:
    return htmllib.unescape(TAG_RE.sub(" ", s)).strip()


def html_to_text(html: str) -> str:
    """표·스크립트 제외 본문 텍스트 (줄 단위 — find_banmal_sentences 입력용)."""
    s = re.sub(r"<script\b.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<style\b.*?</style>", " ", s, flags=re.DOTALL | re.IGNORECASE)
    s = TABLE_RE.sub("\n", s)  # 표 셀 텍스트는 반말·마커 검사 대상 제외
    s = re.sub(r"<(?:br|/p|/li|/h[1-6]|/div|/tr|/blockquote|/figcaption|/figure|/section)[^>]*>",
               "\n", s, flags=re.IGNORECASE)
    s = TAG_RE.sub("", s)
    s = htmllib.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    lines = [ln.strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def title_tokens(title: str) -> set[str]:
    toks = re.findall(r"[가-힣a-zA-Z0-9]{2,}", title.lower())
    return {t for t in toks if t not in STOP_TOKENS and not t.isdigit()}


# ── 글 단위 검출 ─────────────────────────────────────────────────────────────

def audit_post(channel: str, title: str, url: str, html: str,
               published: str, updated: str | None,
               check_img_head: bool = True) -> dict:
    defects: list[dict] = []
    text = html_to_text(html)

    # 1. 빈 표 / 셀 대부분 빈 표
    for ti, tbl in enumerate(TABLE_RE.findall(html), 1):
        cells = [strip_tags(c) for c in CELL_RE.findall(tbl)]
        if not cells:
            defects.append({"type": "empty_table", "detail": f"표#{ti}: 셀 0개(빈 표)"})
            continue
        empty = sum(1 for c in cells if not c)
        if empty / len(cells) >= 0.5 and len(cells) >= 2:
            defects.append({"type": "empty_table",
                            "detail": f"표#{ti}: 전체 {len(cells)}셀 중 {empty}셀 빈칸({empty/len(cells):.0%})"})

    # 2. 마커·마크다운 리터럴
    for name, rx in MARKER_RES:
        hits = rx.findall(text)
        if hits:
            sample = hits[0] if isinstance(hits[0], str) else str(hits[0])
            defects.append({"type": "literal_marker",
                            "detail": f"{name} {len(hits)}건 (예: {sample[:40]!r})"})

    # 3. 이미지 결손
    imgs = IMG_RE.findall(html)
    srcs = []
    for tag in imgs:
        m = SRC_RE.search(tag)
        if m and not m.group(1).startswith("data:"):
            srcs.append(m.group(1))
    if len(imgs) == 0:
        defects.append({"type": "no_image", "detail": "본문 img 0장"})
    elif check_img_head:
        broken = []
        for src in srcs[:3]:
            u = "https:" + src if src.startswith("//") else src
            st = head_status(u)
            if st in (404, 410):
                broken.append(f"{u[:90]} → {st}")
        if broken:
            defects.append({"type": "broken_image", "detail": "; ".join(broken)})

    # 4. 반말 혼입
    banmal = find_banmal_sentences(text, limit=8)
    if banmal:
        defects.append({"type": "banmal", "detail": f"{len(banmal)}문장+", "sentences": banmal})

    # 5. 소제목 계층 (h2/h3 전무 = 통짜 본문)
    if not H23_RE.search(html):
        defects.append({"type": "no_heading", "detail": "h2/h3 소제목 없음(통짜 본문)"})

    # 7. 소유 전용 검출
    slot_flags = {}
    if channel == "soyu":
        shop_imgs = [s for s in srcs if SHOP_IMG_HOST_RE.search(s)]
        slot_anchors = DATA_SLOT_A_RE.findall(html)
        slot_count = len(re.findall(r"data-slot", html))
        imgs_in_slot = sum(len(IMG_RE.findall(a)) for a in slot_anchors)
        slot_flags = {"shop_imgs": len(shop_imgs), "data_slot": slot_count,
                      "imgs_in_slot_anchor": imgs_in_slot}
        if shop_imgs and slot_count == 0:
            defects.append({"type": "no_dataslot",
                            "detail": f"상품 이미지 {len(shop_imgs)}장인데 data-slot 링크 0개"})
        elif shop_imgs and imgs_in_slot < len(shop_imgs):
            defects.append({"type": "unlinked_product_img",
                            "detail": f"상품 이미지 {len(shop_imgs)}장 중 data-slot 앵커 밖 {len(shop_imgs) - imgs_in_slot}장"})

        # 어제 리터치(updated=어제·오늘, published 다른 날) 제목-본문 첫문단 불일치
        pub_d, upd_d = (published or "")[:10], (updated or "")[:10]
        if upd_d in (YESTERDAY, TODAY) and pub_d != upd_d:
            first_para = "\n".join(text.splitlines()[:8])[:600]
            toks = title_tokens(title)
            overlap = {t for t in toks if t in first_para.lower()}
            entry = {"type": "retouched_title",
                     "detail": f"published {pub_d} / updated {upd_d} — 제목토큰 {len(toks)}개 중 첫문단 겹침 {len(overlap)}개",
                     "overlap_tokens": sorted(overlap)}
            if not overlap:
                entry["type"] = "title_body_mismatch"
                entry["detail"] = (f"어제 리터치(updated {upd_d})인데 제목 핵심토큰 {sorted(toks)} 이 "
                                   f"본문 첫 문단에 전혀 없음 — 제목만 바뀐 의심")
            defects.append(entry)

    return {
        "title": title,
        "url": url,
        "published": published,
        "updated": updated,
        "img_count": len(imgs),
        "text_len": len(text),
        **({"soyu_slot": slot_flags} if slot_flags else {}),
        "defects": defects,
    }


def find_dup_titles(posts: list[dict]) -> list[dict]:
    """블로그 내 핵심 토큰 2+ 겹치는 제목 쌍."""
    pairs = []
    toks = [(p, title_tokens(p["title"])) for p in posts]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            common = toks[i][1] & toks[j][1]
            if len(common) >= 2:
                pairs.append({
                    "a": {"title": toks[i][0]["title"], "url": toks[i][0]["url"], "date": toks[i][0]["published"]},
                    "b": {"title": toks[j][0]["title"], "url": toks[j][0]["url"], "date": toks[j][0]["published"]},
                    "common_tokens": sorted(common),
                })
    return pairs


# ── 채널별 수집 ──────────────────────────────────────────────────────────────

def collect_wp(base: str, per_page: int) -> list[dict]:
    url = f"{base}/wp-json/wp/v2/posts?per_page={per_page}&_fields=id,title,link,date,content"
    data = json.loads(fetch(url))
    out = []
    for p in data:
        out.append({
            "id": p.get("id"),
            "title": htmllib.unescape((p.get("title") or {}).get("rendered", "")).strip(),
            "url": p.get("link"),
            "published": p.get("date"),
            "updated": None,
            "html": (p.get("content") or {}).get("rendered", ""),
        })
    return out


def collect_blogger(base: str, max_results: int) -> list[dict]:
    url = f"{base}/feeds/posts/default?alt=json&max-results={max_results}"
    data = json.loads(fetch(url))
    out = []
    for e in (data.get("feed", {}).get("entry") or []):
        link = ""
        for l in e.get("link", []):
            if l.get("rel") == "alternate":
                link = l.get("href", "")
                break
        out.append({
            "id": (e.get("id") or {}).get("$t", ""),
            "title": (e.get("title") or {}).get("$t", "").strip(),
            "url": link,
            "published": (e.get("published") or {}).get("$t", ""),
            "updated": (e.get("updated") or {}).get("$t", ""),
            "html": (e.get("content") or {}).get("$t", ""),
        })
    return out


CHANNELS = [
    ("tech", "형수테크 WP", lambda: collect_wp("https://tech.hyunjiunni.com", 100)),
    ("soyu", "소유의 발품노트 (Blogger)", lambda: collect_blogger("https://soyu.hyunjiunni.com", 40)),
    ("hyunji", "현지언니 WP", lambda: collect_wp("https://hyunjiunni.com", 30)),
]


def main() -> None:
    result = {"generated_at": datetime.now().isoformat(timespec="seconds"),
              "read_only": True, "channels": {}}
    for key, label, collector in CHANNELS:
        ch: dict = {"label": label}
        try:
            raw = collector()
        except Exception as e:
            ch["error"] = f"{type(e).__name__}: {e}"
            result["channels"][key] = ch
            print(f"[{key}] 수집 실패: {e}", flush=True)
            continue
        print(f"[{key}] {len(raw)}글 수집 — 검사 시작", flush=True)
        posts = []
        for r in raw:
            try:
                posts.append(audit_post(key, r["title"], r["url"], r["html"],
                                        r["published"], r["updated"]))
            except Exception as e:
                posts.append({"title": r["title"], "url": r["url"],
                              "defects": [{"type": "audit_error", "detail": f"{type(e).__name__}: {e}"}]})
            print(f"  - {r['title'][:44]} : {len(posts[-1]['defects'])}건", flush=True)
        ch["post_count"] = len(posts)
        ch["posts"] = posts
        ch["duplicate_title_pairs"] = find_dup_titles(posts)
        counts: dict[str, int] = {}
        for p in posts:
            for d in p["defects"]:
                counts[d["type"]] = counts.get(d["type"], 0) + 1
        if ch["duplicate_title_pairs"]:
            counts["duplicate_title_pair"] = len(ch["duplicate_title_pairs"])
        ch["defect_counts"] = counts
        result["channels"][key] = ch

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {OUT_PATH}", flush=True)
    for key, ch in result["channels"].items():
        print(f"[{key}] {ch.get('post_count', 0)}글 | defects: {ch.get('defect_counts', {})}", flush=True)


if __name__ == "__main__":
    main()
