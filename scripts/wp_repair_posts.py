"""
기존 WP 발행글 HTML 보정 스크립트.

대상:
- 예전 렌더 버그로 번호 목록이 1,1,1처럼 리셋된 글
- h2 다음 본문 간격이 너무 붙어 보이는 글

동작:
- 기존 post의 raw HTML을 읽어 보정
- 같은 post ID에 PUT update (URL/slug 유지, 중복 글 생성 없음)
"""
from __future__ import annotations

import base64
import logging
import os
import sys
import re
from typing import Any

import requests
import urllib3

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, WP_APP_PW, WP_URL, WP_USER  # noqa: E402
from generator.wp_topics import TOPICS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("wp_repair_posts")

_TIMEOUT = 30
HISTORY_PATH = os.path.join(DATA_DIR, "wp_post_history.json")
VERIFY_SSL = os.environ.get("WP_VERIFY_SSL", "false").lower() in ("1", "true", "yes")
if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _base() -> str:
    return WP_URL.rstrip("/")


def _api(path: str) -> str:
    return f"{_base()}/wp-json/wp/v2/{path.lstrip('/')}"


def _headers() -> dict[str, str]:
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _check_configured() -> None:
    missing = [k for k, v in {
        "WP_URL": WP_URL,
        "WP_USER": WP_USER,
        "WP_APP_PW": WP_APP_PW,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"필수 설정 누락: {', '.join(missing)}")


def _load_history_topics() -> list[str]:
    if not os.path.exists(HISTORY_PATH):
        return []
    import json
    with open(HISTORY_PATH, encoding="utf-8") as f:
        hist = json.load(f)
    if isinstance(hist, dict):
        return [k for k in hist.keys() if k in TOPICS]
    return []


def _resolve_term(kind: str, name: str) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    r = requests.get(
        _api(kind),
        params={"search": name, "per_page": 100},
        headers=_headers(),
        timeout=_TIMEOUT,
        verify=VERIFY_SSL,
    )
    if r.ok:
        for t in r.json():
            if str(t.get("name", "")).strip().lower() == name.lower():
                return int(t["id"])
    c = requests.post(_api(kind), json={"name": name}, headers=_headers(), timeout=_TIMEOUT, verify=VERIFY_SSL)
    if c.status_code in (200, 201):
        return int(c.json()["id"])
    try:
        d = c.json()
        if d.get("code") == "term_exists":
            return int(d["data"]["term_id"])
    except Exception:
        pass
    logger.warning("%s '%s' 해석 실패: %s", kind, name, c.text[:200])
    return None


def _get_post_by_slug(slug: str) -> dict[str, Any] | None:
    r = requests.get(
        _api("posts"),
        params={"slug": slug, "per_page": 1, "context": "edit"},
        headers=_headers(),
        timeout=_TIMEOUT,
        verify=VERIFY_SSL,
    )
    if not r.ok:
        logger.warning("slug 조회 실패 %s: %s", slug, r.text[:200])
        return None
    rows = r.json()
    return rows[0] if rows else None


_OL_BLOCK_RE = re.compile(r"<ol(?P<attrs>[^>]*)>(?P<body>.*?)</ol>", re.S | re.I)
_START_RE = re.compile(r'\bstart="(\d+)"', re.I)
_LI_RE = re.compile(r"<li\b", re.I)
# <ul>은 번호 항목의 하위 불릿으로 끼는 경우가 대부분 — 시퀀스를 끊지 않는다(2026-07-10).
_RESET_MARKERS = ("<h2", "<table", "<nav", "<figure", "<hr")
_SCHEMA_SCRIPT_RE = re.compile(
    r'(?:<!-- wp:html -->\s*)?<script type="application/ld\+json">.*?</script>\s*(?:<!-- /wp:html -->)?',
    re.S,
)


def _fix_numbered_lists(html: str) -> tuple[str, int]:
    """단일 li로 쪼개진 연속 ol의 start를 1,2,3...로 정렬."""
    out: list[str] = []
    last_end = 0
    seq_next: int | None = None
    fixes = 0

    for m in _OL_BLOCK_RE.finditer(html):
        out.append(html[last_end:m.start()])
        gap = html[last_end:m.start()].lower()
        if any(marker in gap for marker in _RESET_MARKERS):
            seq_next = None

        attrs = m.group("attrs") or ""
        body = m.group("body") or ""
        li_count = len(_LI_RE.findall(body))

        tag = m.group(0)
        if li_count == 1:
            cur = 1
            sm = _START_RE.search(attrs)
            if sm:
                cur = int(sm.group(1))
            if seq_next is None:
                seq_next = cur + 1
            else:
                need = seq_next
                if cur != need:
                    if sm:
                        new_attrs = _START_RE.sub(f'start="{need}"', attrs, count=1)
                    else:
                        new_attrs = attrs + f' start="{need}"'
                    tag = f"<ol{new_attrs}>{body}</ol>"
                    fixes += 1
                seq_next = need + 1
        else:
            seq_next = None

        out.append(tag)
        last_end = m.end()

    out.append(html[last_end:])
    return "".join(out), fixes


def _inject_h2_gap(html: str) -> tuple[str, int]:
    """h2 뒤 간격 보정용 gap div 삽입(중복 삽입 방지)."""
    added = 0
    pattern = re.compile(r"</h2>(\s*)(?!<div class=\"hj-h2-gap\"></div>)", re.I)

    def repl(m: re.Match) -> str:
        nonlocal added
        added += 1
        return "</h2>\n<div class=\"hj-h2-gap\"></div>\n"

    return pattern.sub(repl, html), added


def _fix_schema(html: str, post_url: str) -> tuple[str, int]:
    """JSON-LD @id URL 보정 + wp:html 블록 래핑(본문 <p> 감싸기 방지)."""
    fixes = 0
    base = _base()
    wrong = f'"@id": "{base}"'
    right = f'"@id": "{post_url.rstrip("/")}/"'
    if wrong in html:
        html = html.replace(wrong, right)
        fixes += 1

    def _wrap(m: re.Match) -> str:
        nonlocal fixes
        block = m.group(0).strip()
        if block.startswith("<!-- wp:html -->"):
            return block
        fixes += 1
        inner = re.sub(r"^<!-- wp:html -->\s*", "", block)
        inner = re.sub(r"\s*<!-- /wp:html -->$", "", inner).strip()
        if not inner.startswith("<script"):
            inner = block  # fallback
        return f"<!-- wp:html -->\n{inner}\n<!-- /wp:html -->"

    html = _SCHEMA_SCRIPT_RE.sub(_wrap, html)
    return html, fixes


def _update_post(topic_id: str, *, dry_run: bool) -> bool:
    topic = TOPICS.get(topic_id)
    if not topic:
        logger.warning("알 수 없는 topic_id: %s", topic_id)
        return False
    slug = topic.get("slug") or topic_id.replace("_", "-")
    old = _get_post_by_slug(slug)
    if not old:
        logger.warning("기존 글 없음(skip): %s (%s)", topic_id, slug)
        return False

    raw = (((old.get("content") or {}).get("raw")) or "")
    if not raw:
        logger.warning("raw 본문 없음(skip): %s", slug)
        return False

    fixed, n_ol = _fix_numbered_lists(raw)
    fixed, n_gap = _inject_h2_gap(fixed)
    post_url = (old.get("link") or f"{_base()}/{slug}/").rstrip("/") + "/"
    fixed, n_schema = _fix_schema(fixed, post_url)
    if n_ol == 0 and n_gap == 0 and n_schema == 0:
        logger.info("변경 없음(skip): %s", slug)
        return True

    payload: dict[str, Any] = {
        "title": (old.get("title") or {}).get("raw") or "",
        "slug": slug,
        "content": fixed,
        "excerpt": (old.get("excerpt") or {}).get("raw") or "",
        "status": "publish",
    }
    cid = _resolve_term("categories", topic["category"])
    if cid:
        payload["categories"] = [cid]
    old_tags = old.get("tags") or []
    if old_tags:
        payload["tags"] = old_tags

    if dry_run:
        logger.info("[dry-run] update 예정: id=%s slug=%s (ol_fix=%d, h2_gap=%d, schema_fix=%d)", old.get("id"), slug, n_ol, n_gap, n_schema)
        return True

    u = requests.post(
        _api(f"posts/{old['id']}"),
        json=payload,
        headers=_headers(),
        timeout=_TIMEOUT,
        verify=VERIFY_SSL,
    )
    if u.status_code not in (200, 201):
        logger.error("업데이트 실패 id=%s: %s", old.get("id"), u.text[:300])
        return False
    d = u.json()
    logger.info("업데이트 완료: id=%s %s (ol_fix=%d, h2_gap=%d, schema_fix=%d)", d.get("id"), d.get("link"), n_ol, n_gap, n_schema)
    return True


def run(topics_arg: str = "", dry_run: bool = False) -> int:
    _check_configured()
    history_topics = _load_history_topics()
    if topics_arg.strip():
        target = [t.strip() for t in topics_arg.split(",") if t.strip()]
    else:
        target = history_topics
    if not target:
        logger.error("수정 대상 topic이 없습니다.")
        return 1

    logger.info("대상 topic: %s", ", ".join(target))
    ok, fail = 0, 0
    logger.info("SSL verify: %s", VERIFY_SSL)
    for tid in target:
        try:
            if _update_post(tid, dry_run=dry_run):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            logger.exception("처리 예외(%s): %s", tid, e)
            fail += 1
    logger.info("완료: 성공 %d / 실패 %d", ok, fail)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    topics = ""
    dry = False
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--dry-run":
            dry = True
        elif arg.startswith("--topics="):
            topics = arg.split("=", 1)[1]
        elif arg == "--topics" and i + 2 <= len(sys.argv[1:]):
            topics = sys.argv[i + 2]
    raise SystemExit(run(topics_arg=topics, dry_run=dry))
