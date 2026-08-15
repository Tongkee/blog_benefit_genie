# -*- coding: utf-8 -*-
"""네이버 블로그 2개(hyunji_unni 최근 60 / hyungsutech 전수) 발행글 품질 전수 감사.

읽기 전용: RSS + 모바일 목록 API로 logNo 수집 → m.blog.naver.com 본문 HTML GET(1초 간격).
결함 검출은 전부 HTML/텍스트 결정론. 결과는 naver_audit_result.json.
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# 레포의 반말 검출기 재사용 (읽기 전용 import)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from generator.quality import find_banmal_sentences  # noqa: E402

SCRATCH = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRATCH, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
RESULT_PATH = os.path.join(SCRATCH, "naver_audit_result.json")

KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; SM-G991N) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
    ),
    "Referer": "https://m.blog.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

TARGETS = [
    {"blog": "hyunji_unni", "limit": 60},
    {"blog": "hyungsutech", "limit": None},  # 전수
]

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
FAQ_RE = re.compile(r"Q\s*[:.]|자주\s*묻는")

# 제목 근접중복용 불용어(일반어·낚시어·연도)
TITLE_STOPWORDS = {
    "2024", "2025", "2026", "2024년", "2025년", "2026년",
    "방법", "정리", "총정리", "가이드", "완벽", "기준", "최신", "확인",
    "추천", "비교", "후기", "꿀팁", "핵심", "필수", "지금", "바로",
    "이것", "모르면", "손해입니다", "손해", "하는", "해야", "무엇",
    "언제", "어떻게", "그리고", "위한", "대한", "진짜", "저만", "제가",
}


def _fetch(url, tries=3, as_bytes=False):
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=20)
            if r.status_code == 200:
                return r.content if as_bytes else r.text
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(2 + i)
    print(f"  ! fetch fail {url}: {last}")
    return None


# ── 글 목록 수집 ──────────────────────────────────────────────────────────────

def rss_posts(blog_id):
    """RSS(최근 50) — {logNo: {title, date}}"""
    out = {}
    raw = _fetch(f"https://blog.rss.naver.com/{blog_id}.xml", as_bytes=True)
    if not raw:
        return out
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  ! RSS parse error {blog_id}: {e}")
        return out
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        m = re.search(r"/(\d{9,})", link)
        if not m:
            continue
        logno = m.group(1)
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        date = ""
        try:
            dt = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z")
            date = dt.astimezone(KST).strftime("%Y-%m-%d")
        except ValueError:
            pass
        out[logno] = {"title": title, "date": date}
    return out


def api_posts(blog_id, max_pages=12):
    """모바일 목록 API 페이지네이션 — {logNo: {title, date}} (비공개 글 제외)."""
    out = {}
    for page in range(1, max_pages + 1):
        url = (f"https://m.blog.naver.com/api/blogs/{blog_id}/post-list"
               f"?categoryNo=0&itemCount=30&page={page}")
        txt = _fetch(url)
        time.sleep(1)
        if not txt:
            break
        try:
            items = json.loads(txt)["result"]["items"]
        except Exception as e:  # noqa: BLE001
            print(f"  ! API parse fail {blog_id} p{page}: {e}")
            break
        if not items:
            break
        new = 0
        for it in items:
            logno = str(it.get("logNo", "")).strip()
            if not logno or it.get("notOpen"):
                continue
            if logno not in out:
                new += 1
            date = ""
            try:
                date = datetime.fromtimestamp(
                    int(it.get("addDate", 0)) / 1000, KST).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                pass
            out[logno] = {
                "title": (it.get("titleWithInspectMessage") or "").strip(),
                "date": date,
            }
        if new == 0 or len(items) < 30:
            break
    return out


def titlelist_fallback(blog_id, max_pages=10):
    """PostTitleListAsync.naver 폴백 — API 실패 시에만."""
    out = {}
    for page in range(1, max_pages + 1):
        url = (f"https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}"
               f"&viewdate=&currentPage={page}&categoryNo=0&parentCategoryNo="
               f"&countPerPage=30")
        txt = _fetch(url)
        time.sleep(1)
        if not txt:
            break
        try:
            data = json.loads(txt.replace("\\'", "'"))
            lists = data.get("postList", [])
        except Exception as e:  # noqa: BLE001
            print(f"  ! titlelist parse fail p{page}: {e}")
            break
        if not lists:
            break
        for it in lists:
            logno = str(it.get("logNo", "")).strip()
            if logno:
                from urllib.parse import unquote
                out.setdefault(logno, {
                    "title": unquote(it.get("title", "")).replace("+", " "),
                    "date": it.get("addDate", ""),
                })
        if len(lists) < 30:
            break
    return out


def collect_posts(blog_id, limit):
    api = api_posts(blog_id)
    rss = rss_posts(blog_id)
    merged = dict(api)
    for logno, meta in rss.items():
        if logno not in merged:
            merged[logno] = meta
        else:
            # RSS 제목이 있으면 보강(형식은 동일)
            if not merged[logno]["title"]:
                merged[logno]["title"] = meta["title"]
            if not merged[logno]["date"]:
                merged[logno]["date"] = meta["date"]
    if not merged:
        print(f"  ! API+RSS 모두 실패 → PostTitleListAsync 폴백 ({blog_id})")
        merged = titlelist_fallback(blog_id)
    posts = sorted(merged.items(), key=lambda kv: (kv[1]["date"], kv[0]), reverse=True)
    if limit:
        posts = posts[:limit]
    return posts  # [(logNo, {title, date}), ...] 최신순


# ── 본문 파싱·검출 ────────────────────────────────────────────────────────────

def get_post_html(blog_id, logno):
    cache = os.path.join(CACHE_DIR, f"{blog_id}_{logno}.html")
    if os.path.exists(cache) and os.path.getsize(cache) > 5000:
        with open(cache, encoding="utf-8") as f:
            return f.read()
    html = _fetch(f"https://m.blog.naver.com/{blog_id}/{logno}")
    time.sleep(1)  # 요청 간 1초 대기
    if html:
        with open(cache, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def extract_container(soup):
    for sel in ("div.se-main-container", "#viewTypeSelector", "div.post_ct"):
        node = soup.select_one(sel)
        if node:
            return node
    return None


def para_lines(container):
    """문단 단위 텍스트 라인(스팬 분절 없이 문단=1줄). (전체라인, 표밖라인) 반환."""
    all_lines, non_table = [], []
    blocks = container.find_all(["p", "li", "h1", "h2", "h3"])
    for b in blocks:
        # li 안의 p 중복 방지: p를 품은 li는 건너뛰고 p에서 수집
        if b.name == "li" and b.find("p") is not None:
            continue
        t = b.get_text().replace("\u200b", "").strip()
        if not t:
            continue
        all_lines.append(t)
        if b.find_parent("table") is None:
            non_table.append(t)
    return all_lines, non_table


def audit_post(blog_id, logno, meta):
    url = f"https://m.blog.naver.com/{blog_id}/{logno}"
    rec = {
        "blog": blog_id, "logNo": logno, "title": meta.get("title", ""),
        "date": meta.get("date", ""), "url": url, "defects": [], "info": {},
    }
    html = get_post_html(blog_id, logno)
    if not html:
        rec["defects"].append({"type": "fetch_fail", "detail": "본문 HTML 수신 실패"})
        return rec
    soup = BeautifulSoup(html, "html.parser")

    if not rec["title"]:
        og = soup.find("meta", property="og:title")
        if og:
            rec["title"] = (og.get("content") or "").strip()
    if not rec["date"]:
        m = re.search(r'blog_date[^>]*>\s*([^<]+?)\s*<', html)
        if m:
            dm = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", m.group(1))
            if dm:
                rec["date"] = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"

    container = extract_container(soup)
    if container is None:
        rec["defects"].append({"type": "no_container", "detail": "본문 컨테이너 미발견"})
        return rec

    all_lines, non_table_lines = para_lines(container)
    full_text = "\n".join(all_lines)
    rec["info"]["text_len"] = len(full_text)

    # 1. 빈 표 — 셀 텍스트 전부 공백
    tables = container.find_all("table")
    rec["info"]["table_count"] = len(tables)
    empty_tables = 0
    for t in tables:
        cells = t.find_all(["td", "th"])
        if cells and all(not c.get_text().replace("\u200b", "").strip() for c in cells):
            empty_tables += 1
    if empty_tables:
        rec["defects"].append({"type": "empty_table",
                               "detail": f"셀 전부 공백인 표 {empty_tables}개/{len(tables)}개"})

    # 2. 번호 리스트 분절 — 항목 1개짜리 <ol> 2개 이상
    ols = container.find_all("ol")
    single_ols = sum(1 for o in ols if len(o.find_all("li", recursive=False)) == 1)
    rec["info"]["ol_count"] = len(ols)
    if single_ols >= 2:
        rec["defects"].append({"type": "ol_fragmented",
                               "detail": f"1항목 <ol> {single_ols}개 (전체 ol {len(ols)}개) — 1.1.1. 분절"})

    # 3. 마커·마크다운 리터럴 노출
    lit_hits = []
    for marker in ("[사진", "[표시작", "[FAQ", "[소제목]", "{{", "**"):
        if marker in full_text:
            lit_hits.append(marker)
    md_lines = [ln for ln in all_lines if ln.startswith("##") or ln.startswith("- ")]
    if lit_hits or md_lines:
        detail = []
        if lit_hits:
            detail.append("리터럴: " + ", ".join(lit_hits))
        if md_lines:
            detail.append("MD줄 예: " + " / ".join(ln[:30] for ln in md_lines[:3]))
        rec["defects"].append({"type": "literal_marker", "detail": " | ".join(detail)})

    # 4. 지시문 에코
    echo = [pat for pat in ("★위 [사진", "(★") if pat in full_text]
    if echo:
        idx = full_text.find(echo[0])
        rec["defects"].append({"type": "instruction_echo",
                               "detail": f"{', '.join(echo)} 노출 — 예: {full_text[max(0,idx-10):idx+30]!r}"})

    # 5. 반말 문장 (레포 검출기 재사용, 표 밖 문단만)
    banmal = find_banmal_sentences("\n".join(non_table_lines), limit=8)
    if banmal:
        rec["defects"].append({"type": "banmal",
                               "detail": f"{len(banmal)}건{'+' if len(banmal) >= 8 else ''}: "
                                         + " / ".join(banmal[:3])})
    rec["info"]["banmal_count"] = len(banmal)

    # 6. FAQ 위치 이상 — 첫 등장이 앞 35% 이내
    m = FAQ_RE.search(full_text)
    if m and len(full_text) > 300:
        ratio = m.start() / len(full_text)
        rec["info"]["faq_pos_ratio"] = round(ratio, 3)
        if ratio < 0.35:
            rec["defects"].append({"type": "faq_position",
                                   "detail": f"FAQ 첫 등장 위치 {ratio:.0%} (<35%) — "
                                             f"매치 {m.group(0)!r}"})

    # 7. 소제목 원형숫자 — 인용구/굵은 텍스트가 ①~⑳로 시작
    heads = []
    for bq in container.find_all("blockquote"):
        heads.append(bq.get_text().replace("\u200b", "").strip())
    for bold in container.find_all(["b", "strong"]):
        heads.append(bold.get_text().replace("\u200b", "").strip())
    circled = sorted({h[:14] for h in heads if h and h[0] in CIRCLED})
    if circled:
        rec["defects"].append({"type": "circled_subheading",
                               "detail": f"{len(circled)}종 예: " + " / ".join(circled[:3])})

    # 8. 본문 이미지 (hyungsutech만 결함 판정 — 헤더 카드 1장뿐)
    imgs = container.find_all("img")
    rec["info"]["img_count"] = len(imgs)
    if blog_id == "hyungsutech" and len(imgs) <= 1:
        rec["defects"].append({"type": "no_body_image",
                               "detail": f"img {len(imgs)}장 — 헤더 카드 외 본문 이미지 없음"})

    return rec


# ── 9. 제목 근접중복 ──────────────────────────────────────────────────────────

def title_tokens(title):
    toks = re.findall(r"[가-힣A-Za-z0-9]+", title)
    return {t.lower() for t in toks if len(t) >= 2 and t not in TITLE_STOPWORDS}


def near_dup_titles(records):
    pairs = []
    recs = [(r["logNo"], r["title"], title_tokens(r["title"]), r["date"]) for r in records]
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            common = recs[i][2] & recs[j][2]
            if len(common) >= 2:
                pairs.append({
                    "a": {"logNo": recs[i][0], "title": recs[i][1], "date": recs[i][3]},
                    "b": {"logNo": recs[j][0], "title": recs[j][1], "date": recs[j][3]},
                    "common_tokens": sorted(common),
                })
    return pairs


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    result = {"generated_at": datetime.now(KST).isoformat(), "blogs": {}, "posts": []}
    for tgt in TARGETS:
        blog_id, limit = tgt["blog"], tgt["limit"]
        print(f"== {blog_id} list collect (limit={limit}) ==", flush=True)
        posts = collect_posts(blog_id, limit)
        print(f"   posts: {len(posts)}", flush=True)
        recs = []
        for i, (logno, meta) in enumerate(posts, 1):
            rec = audit_post(blog_id, logno, meta)
            recs.append(rec)
            print(f"  [{blog_id}] {i}/{len(posts)} logNo={logno} "
                  f"defects={len(rec['defects'])} "
                  f"types={','.join(d['type'] for d in rec['defects']) or '-'}", flush=True)
            # 중간 저장 (크래시 대비)
            if i % 10 == 0:
                with open(RESULT_PATH + ".partial", "w", encoding="utf-8") as f:
                    json.dump(result["posts"] + recs, f, ensure_ascii=False, indent=1)
        dups = near_dup_titles(recs)
        result["blogs"][blog_id] = {
            "post_count": len(recs),
            "near_dup_title_pairs": dups,
        }
        result["posts"].extend(recs)

    # 요약 집계
    summary = {}
    for r in result["posts"]:
        s = summary.setdefault(r["blog"], {})
        for d in r["defects"]:
            s[d["type"]] = s.get(d["type"], 0) + 1
    result["summary_defect_posts"] = summary
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    part = RESULT_PATH + ".partial"
    if os.path.exists(part):
        os.remove(part)
    print("DONE ->", RESULT_PATH, flush=True)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
