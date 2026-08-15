"""
발행된 WP 글에 대표 이미지 일괄 생성·지정 (백필 + 재실행 안전).

- wp_post_history.json의 발행 topic들을 순회
- featured_media가 이미 있으면 스킵(FORCE=1 시 재생성)
- 일러스트+타이틀 카드 생성(generator/wp_featured.py) → 업로드 → 지정

사용:
  python -m scripts.wp_set_featured            # 누락분만
  FORCE=1 python -m scripts.wp_set_featured    # 전체 재생성
  WP_TOPIC=isa python -m scripts.wp_set_featured  # 단건
"""
import html
import json
import logging
import os
import sys

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import GOOGLE_API_KEY, DATA_DIR
from generator.wp_topics import TOPICS
from generator.wp_featured import build_featured_image
from poster.wp_publish import get_post_meta_by_slug, upload_media, set_featured_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_set_featured")


def process_topic(topic_id: str, force: bool = False) -> str:
    topic = TOPICS.get(topic_id)
    if not topic:
        return "unknown-topic"
    slug = topic.get("slug") or topic_id.replace("_", "-")
    meta = get_post_meta_by_slug(slug)
    if not meta:
        return "no-post"
    if meta["featured_media"] and not force:
        return "skip(있음)"
    title = html.unescape(meta["title"]) or topic["keyword"]
    path = build_featured_image(title, topic["keyword"], topic["category"],
                                topic.get("hub_id", ""), api_key=GOOGLE_API_KEY)
    if not path:
        return "build-fail"
    try:
        mid = upload_media(path, f"featured-{slug}.png", alt_text=title)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if not mid:
        return "upload-fail"
    return "OK" if set_featured_image(meta["id"], mid) else "set-fail"


def main():
    force = os.environ.get("FORCE", "").strip() in ("1", "true")
    only = os.environ.get("WP_TOPIC", "").strip().lower()
    if only:
        targets = [only]
    else:
        hist_path = os.path.join(DATA_DIR, "wp_post_history.json")
        with open(hist_path, encoding="utf-8") as f:
            targets = sorted(json.load(f))
    results = {}
    for tid in targets:
        logger.info(f"── {tid} ──")
        results[tid] = process_topic(tid, force=force)
    logger.info("── 결과 ──")
    for tid, res in results.items():
        logger.info(f"  {tid}: {res}")
    fails = [t for t, r in results.items() if r.endswith("fail")]
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
