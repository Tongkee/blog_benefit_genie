"""
워드프레스 REST API 발행 어댑터 (WP_PIPELINE.md §5 B단계).

render_wordpress_post() 산출 번들 → WP 글 발행(초안/공개).
- 인증: Application Password(Basic Auth). config: WP_URL / WP_USER / WP_APP_PW.
- 카테고리·태그는 이름 → term id 해석(없으면 생성).
- 네이버(Playwright)와 달리 브라우저 불필요 — 순수 REST.

전제: WP 관리자 계정의 Application Password. HTTPS 필수(평문 Basic 금지).
"""
import base64
import logging

import requests

from config import WP_URL, WP_USER, WP_APP_PW

logger = logging.getLogger("wp_publish")
_TIMEOUT = 30


def _base() -> str:
    return WP_URL.rstrip("/")


def _api(path: str) -> str:
    return f"{_base()}/wp-json/wp/v2/{path.lstrip('/')}"


def _headers() -> dict:
    # Application Password는 공백 포함 표기돼도 그대로 사용 가능(서버가 정규화).
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _configured() -> bool:
    if not (WP_URL and WP_USER and WP_APP_PW):
        logger.error("WP 설정 누락 — WP_URL/WP_USER/WP_APP_PW(.env 또는 GH Secret) 확인")
        return False
    return True


def _resolve_term(kind: str, name: str) -> int | None:
    """kind='categories'|'tags', 이름 → term id(없으면 생성)."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        r = requests.get(_api(kind), params={"search": name, "per_page": 100},
                         headers=_headers(), timeout=_TIMEOUT)
        if r.ok:
            for t in r.json():
                if str(t.get("name", "")).strip().lower() == name.lower():
                    return t["id"]
        r = requests.post(_api(kind), json={"name": name}, headers=_headers(), timeout=_TIMEOUT)
        if r.status_code in (200, 201):
            return r.json()["id"]
        # 이미 존재하면 에러 payload에 기존 id가 담겨온다
        data = r.json()
        if data.get("code") == "term_exists":
            return int(data["data"]["term_id"])
        logger.warning(f"{kind} '{name}' 해석 실패 {r.status_code}: {r.text[:150]}")
    except Exception as e:
        logger.warning(f"{kind} '{name}' 해석 예외: {e}")
    return None


def _find_post_id_by_slug(slug: str) -> int | None:
    """slug로 기존 글 조회(모든 상태) — 재발행 시 중복 생성 대신 갱신하기 위함."""
    if not slug:
        return None
    try:
        r = requests.get(_api("posts"),
                         params={"slug": slug, "status": "publish,draft,future,pending,private",
                                 "per_page": 1, "context": "edit"},
                         headers=_headers(), timeout=_TIMEOUT)
        if r.ok and r.json():
            return int(r.json()[0]["id"])
    except Exception as e:
        logger.warning(f"slug '{slug}' 조회 예외: {e}")
    return None


def publish_wordpress(rendered: dict, title: str, *, status: str = "draft",
                      category: str = "", include_schema: bool = True) -> dict | None:
    """렌더 번들 → WP 발행.

    rendered: render_wordpress_post() 반환(content_html/excerpt/slug/tags/schema_jsonld).
    title   : 글 제목(전체 — render의 seo_title은 60자 절삭이라 별도로 받는다).
    status  : 'draft'(기본, 스팟체크) | 'publish' | 'future' 등.
    반환    : {id, link, status} 또는 None.
    """
    if not _configured():
        return None

    content = rendered.get("content_html") or rendered.get("html") or ""
    if include_schema and rendered.get("schema_jsonld"):
        # wp:html 블록으로 감싸야 WP가 <p>로 감싸지 않음
        content = content + "\n<!-- wp:html -->\n" + rendered["schema_jsonld"] + "\n<!-- /wp:html -->"

    payload: dict = {
        "title": (title or rendered.get("seo_title") or "").strip(),
        "content": content,
        "status": status,
        "excerpt": rendered.get("excerpt", ""),
    }
    if rendered.get("slug"):
        payload["slug"] = rendered["slug"]

    if category:
        cid = _resolve_term("categories", category)
        if cid:
            payload["categories"] = [cid]

    tag_ids = [tid for tid in (_resolve_term("tags", n) for n in (rendered.get("tags") or [])) if tid]
    if tag_ids:
        payload["tags"] = tag_ids

    # 동일 slug 글이 있으면 갱신(주제 로테이션 재발행 시 -2 붙은 중복 글 방지)
    endpoint = _api("posts")
    existing_id = _find_post_id_by_slug(rendered.get("slug", ""))
    if existing_id:
        endpoint = _api(f"posts/{existing_id}")
        logger.info(f"동일 slug 기존 글 갱신: id={existing_id}")

    try:
        r = requests.post(endpoint, json=payload, headers=_headers(), timeout=_TIMEOUT)
    except Exception as e:
        logger.error(f"발행 요청 실패: {e}")
        return None

    if r.status_code in (200, 201):
        d = r.json()
        logger.info(f"발행 완료 [{d.get('status')}] id={d.get('id')} {d.get('link')}")
        return {"id": d.get("id"), "link": d.get("link"), "status": d.get("status")}

    logger.error(f"발행 실패 {r.status_code}: {r.text[:300]}")
    return None


def upload_media_info(file_path: str, filename: str, alt_text: str = "") -> dict | None:
    """이미지 파일 → WP 미디어 업로드 → {id, source_url} (본문 <img> 삽입용, 2026-07-17)."""
    if not _configured():
        return None
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        headers = _headers()
        headers["Content-Type"] = "image/png"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        r = requests.post(_api("media"), data=data, headers=headers, timeout=60)
        if r.status_code in (200, 201):
            d = r.json()
            mid = int(d["id"])
            if alt_text:
                requests.post(_api(f"media/{mid}"), json={"alt_text": alt_text},
                              headers=_headers(), timeout=_TIMEOUT)
            logger.info(f"미디어 업로드 완료 id={mid} ({filename})")
            return {"id": mid, "source_url": d.get("source_url", "")}
        logger.error(f"미디어 업로드 실패 {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"미디어 업로드 예외: {e}")
    return None


def upload_media(file_path: str, filename: str, alt_text: str = "") -> int | None:
    """이미지 파일 → WP 미디어 업로드 → media id."""
    info = upload_media_info(file_path, filename, alt_text)
    return info["id"] if info else None


def set_featured_image(post_id: int, media_id: int) -> bool:
    """글 대표 이미지 지정."""
    try:
        r = requests.post(_api(f"posts/{post_id}"), json={"featured_media": media_id},
                          headers=_headers(), timeout=_TIMEOUT)
        if r.ok:
            logger.info(f"대표 이미지 지정: post={post_id} media={media_id}")
            return True
        logger.error(f"대표 이미지 지정 실패 {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"대표 이미지 지정 예외: {e}")
    return False


def get_post_meta_by_slug(slug: str) -> dict | None:
    """slug → {id, featured_media, title} (없으면 None)."""
    if not slug:
        return None
    try:
        r = requests.get(_api("posts"),
                         params={"slug": slug, "status": "publish,draft,future,pending,private",
                                 "per_page": 1, "context": "edit"},
                         headers=_headers(), timeout=_TIMEOUT)
        if r.ok and r.json():
            d = r.json()[0]
            return {"id": int(d["id"]), "featured_media": int(d.get("featured_media") or 0),
                    "title": d.get("title", {}).get("rendered", "")}
    except Exception as e:
        logger.warning(f"slug '{slug}' 메타 조회 예외: {e}")
    return None


def check_connection() -> bool:
    """인증·연결 점검(현재 사용자 조회). 실발행 전 스모크 테스트."""
    if not _configured():
        return False
    try:
        r = requests.get(f"{_base()}/wp-json/wp/v2/users/me", headers=_headers(), timeout=_TIMEOUT)
        if r.ok:
            logger.info(f"WP 연결 OK — 사용자 '{r.json().get('name')}' (id={r.json().get('id')})")
            return True
        logger.error(f"WP 연결 실패 {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"WP 연결 예외: {e}")
    return False
