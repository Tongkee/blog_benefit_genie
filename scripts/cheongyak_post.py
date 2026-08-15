"""청약 공고 건별 분석글 발행 — 청약홈 신규 공고 감지 → 심층분석 → WP 주거·청약 (2026-07-17).

정규 로테이션(wp_post)과 별개 트랙: 새 공고가 있을 때만 추가 발행(하루 1건 가드 미적용),
run당 최대 1건(비용·품질 통제). 잔여 신규 공고는 다음 크론이 순차 소화.

사용:
  python -m scripts.cheongyak_post                 # 신규 공고 1건 발행
  CHEONGYAK_NOTICE=2026000123 ...                  # 특정 공고(HOUSE_MANAGE_NO) 강제
  WP_STATUS=draft DRY_RUN=true ...                 # 검증 모드
필요 키: PUBLIC_DATA_KEY(청약홈 API), GOOGLE_API_KEY, WP_*(발행)
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR, GOOGLE_API_KEY, WP_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("cheongyak_post")

KST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(DATA_DIR, "cheongyak_history.json")
HUB_ID = "housing-plan"

# 청약 건별 분석 구조 (2026-07-17 사용자 지시: 일정·현금·타입·유형·가격적정성·판단)
_EXTRA_INSTRUCTIONS = """\
- 이 글은 특정 단지 '입주자모집공고' 건별 분석이다. 아래 흐름을 반드시 갖춰라(소제목 문구는 자연스럽게, 순서 유지):
  ① 어떤 단지인가 — 위치·규모·시공사·공급유형을 한눈에
  ② 청약 일정 — 특별공급/1·2순위/당첨자 발표/계약을 표로
  ③ 현금은 얼마나 필요한가 — 타입별 분양가와 계약금 계산. 계약금 비율·중도금 대출 조건은
     '모집공고문 발췌' 원문에 있는 내용만 근거로 쓰고, 발췌에 없으면 '공고문 확인 필요'로 처리
  ④ 어떤 타입이 유리한가 — 세대수·면적·가격을 비교해 경쟁률 관점 코멘트
  ⑤ 신청 유형별 체크 — 특별공급 종류·1순위 요건·규제(투기과열/조정대상/분양가상한) 적용 여부
  ⑥ 가격은 적당한가 — 팩트에 '주변 아파트 실거래 시세(국토교통부)'가 있으면 그것을 1순위
     근거로 삼아 분양가와 직접 비교하라(예: 84㎡ 최고분양가가 같은 구 준신축 평균 대비 몇 %
     수준인지 계산, 최근 실거래 사례 1~2건 인용). 검색 정보는 보조로만, '~로 알려져 있다' 톤,
     확인 안 되면 단정 금지
  ⑥-1 알아둘 리스크 — ★필수 섹션(2026-07-19 경쟁글 분석: 좋은 얘기만 하는 글은 신뢰를 잃는다).
     공급유형이 조합원 취소분·무순위·잔여세대면 그런 물량이 나오는 구조적 배경(계약 해지·자격
     상실·미계약)을 일반론으로 짚고 개별 사유는 공고문에 없다고 투명하게. 지역주택조합 사업이면
     지주택 일반 리스크(사업 지연·추가 분담금 이력 가능성)를 일반론으로. 계약금 몰취 구조,
     중도금 이자 부담, 거래 침체기엔 전매제한이 짧아도 실제 매도가 어려울 수 있다는 점 중 해당
     항목을 다뤄라. 단, 이 단지의 소송·마이너스피·미분양 같은 개별 사실은 팩트에 없으면 단정 금지.
  ⑦ 마지막 소제목은 '현지언니의 판단' — [해볼 만해요 / 조건부 추천이에요 / 보류가 나아요] 셋 중
     하나를(★존댓말 종결 필수, 반말 단정 금지 — 2026-07-29 감사) 첫 문장에서
     명확히 고르고, 근거 3가지 + '이런 분께 맞다/이런 분은 보류' 를 불릿으로.
     ★'이런 분께 맞아요:' 같은 상위 라벨 줄에는 글머리(·)를 붙이지 말고 라벨만 한 줄로 쓰고,
     그 아래 해당 항목들만 · 불릿으로(상위·하위가 같은 글머리면 안 됨)
     ★판정 하한(2026-07-19): 분양가가 주변 준신축 '평균' 대비 +15% 이상인 타입이 과반이면
     '해볼 만하다' 판정 금지. "전매제한이 짧아 빠르게 매도할 수 있다"류 매도 용이성 표현 금지.
- 시세 비교 우선순위(2026-07-19): '같은 동(같은 생활권) 실거래'가 팩트에 있으면 그것이 1순위
  잣대. 시·구 전체 평균이나 '준신축 최고가 대비 낮다' 프레임으로 유리하게 포장 금지(최고가는 참고만).
- 판단은 투자 권유 단정이 아니라 조건 중심으로. 글 끝에 '청약 자격·자금 사정은 사람마다 달라
  최종 판단 전 입주자모집공고문 원문을 꼭 확인하라'는 면책 1줄.
- 검색(그라운딩) 정보와 공고 팩트를 섞지 마라 — 수치는 팩트 데이터·공고문 발췌가 우선."""


def _load_history() -> dict:
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_history(h: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)


def _related_housing_posts(limit: int = 3) -> list[dict]:
    """기발행 주거·청약 허브 글을 관련글로 (내부링크·체류시간)."""
    try:
        from generator.wp_topics import TOPICS
        wp_hist_path = os.path.join(DATA_DIR, "wp_post_history.json")
        hist = json.load(open(wp_hist_path, encoding="utf-8")) if os.path.exists(wp_hist_path) else {}
        out = []
        for tid, meta in TOPICS.items():
            if meta.get("hub_id") == HUB_ID and tid in hist:
                out.append({"title": meta.get("keyword", tid),
                            "slug": meta.get("slug") or tid.replace("_", "-")})
        return out[:limit]
    except Exception:
        return []


def _fig_html(name: str, c: dict, upload) -> str:
    info = upload(c["path"], alt_suffix=c["label"], page=c.get("page", 0))
    if not info:
        return ""
    if c.get("src") == "homepage":   # 분양 홈페이지 도면(2026-07-29) — 공고문 페이지 아님
        cap = f"{name} {c['label']} — 분양 홈페이지"
    else:
        cap = f"{name} {c['label']} — 입주자모집공고문 p.{c.get('page', '')} (출처: 청약홈)"
    return (
        f'<figure class="wp-block-image size-large hj-notice-capture">'
        f'<img src="{info["source_url"]}" alt="{name} {c["label"]}" loading="lazy"/>'
        f"<figcaption>{cap}</figcaption></figure>\n"
    )


def _insert_captures_inline(content_html: str, name: str, captures: list[dict], upload):
    """공고문 캡처를 '관련 내용을 설명하는 섹션 안'에 삽입 (2026-07-17 사용자 피드백 —
    맨 끝 원문자료 섹션 대신). 금액표→현금/분양가 섹션 끝, 평면도→타입 섹션 끝.
    매칭할 섹션이 없으면 그 캡처만 말미 '원문 자료' 폴백. 반환: (html, 삽입여부)."""
    import re as _re
    figs = {"price": [], "plan": [], "site": []}
    for c in captures:
        h = _fig_html(name, c, upload)
        if h:
            lbl = c["label"]
            # 단지 도면류(배치도/조감도/위치도, 2026-07-28 collector 확장) — 단지 소개 섹션으로.
            key = ("plan" if "평면" in lbl
                   else "site" if any(k in lbl for k in ("배치도", "조감도", "위치도"))
                   else "price")
            figs[key].append(h)
    if not (figs["price"] or figs["plan"] or figs["site"]):
        return content_html, False

    h2s = list(_re.finditer(r'<h2 id="sec-\d+">([^<]+)</h2>', content_html))

    def _sec_idx(*kws):
        for i, m in enumerate(h2s):
            if any(k in m.group(1) for k in kws):
                return i
        return None

    def _sec_end(i):
        return h2s[i + 1].start() if i + 1 < len(h2s) else len(content_html)

    inserts, leftovers = [], []
    pi = _sec_idx("현금", "필요", "분양가", "금액")
    if pi is not None and figs["price"]:
        inserts.append((_sec_end(pi), "\n" + "".join(figs["price"])))
    else:
        leftovers += figs["price"]
    ti = _sec_idx("타입", "유리")
    if ti is not None and figs["plan"]:
        inserts.append((_sec_end(ti), "\n" + "".join(figs["plan"])))
    else:
        leftovers += figs["plan"]
    si = _sec_idx("단지")   # ① '어떤 단지인가' 섹션 끝 — 도면류(배치도/조감도/위치도)
    if si is not None and figs["site"]:
        inserts.append((_sec_end(si), "\n" + "".join(figs["site"])))
    else:
        leftovers += figs["site"]
    for pos, html_ in sorted(inserts, reverse=True):
        content_html = content_html[:pos] + html_ + content_html[pos:]
    if leftovers:
        content_html += ('\n<h2 id="sec-notice">모집공고문 원문 자료</h2>\n'
                         + "".join(leftovers))
    return content_html, True


def run():
    from generator.cheongyak_collector import (
        fetch_new_apt_notices, fetch_new_remainder_notices, fetch_house_types,
        fetch_notice_pdf, pdf_excerpt, pdf_capture_key_pages,
        build_facts, build_key_stats, notice_key,
    )
    from generator.wp_topics import hub_display

    status = os.environ.get("WP_STATUS", "publish").strip().lower()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    forced = os.environ.get("CHEONGYAK_NOTICE", "").strip()

    history = _load_history()
    notices = fetch_new_apt_notices() + fetch_new_remainder_notices()
    if forced:
        notices = [n for n in notices if forced in (n.get("HOUSE_MANAGE_NO", ""), notice_key(n))]
    else:
        notices = [n for n in notices if notice_key(n) not in history]
    if not notices:
        logger.info("발행할 신규 청약 공고 없음 — 종료")
        return

    # 공고일 최신순 1건만 (잔여는 다음 크론)
    notices.sort(key=lambda n: n.get("RCRIT_PBLANC_DE", ""), reverse=True)
    detail = notices[0]
    key = notice_key(detail)
    name = detail.get("HOUSE_NM", "").strip()
    logger.info(f"대상 공고: [{key}] {name} ({detail.get('SUBSCRPT_AREA_CODE_NM')}, "
                f"{detail.get('RCRIT_PBLANC_DE')}) 잔여 신규 {len(notices) - 1}건")

    types = fetch_house_types(detail.get("HOUSE_MANAGE_NO", ""),
                              remainder=bool(detail.get("_remainder")))
    pdf = fetch_notice_pdf(detail)
    excerpt = pdf_excerpt(pdf) if pdf else ""
    captures = pdf_capture_key_pages(pdf) if pdf else []
    # 분양 홈페이지 도면(2026-07-29): 공고문에 도면 없는 단지 보충 — 네이버 트랙과 동일 배선
    try:
        from generator.cheongyak_collector import fetch_homepage_assets
        pdf_plan = sum(1 for c in captures if "평면" in c["label"])
        pdf_site = sum(1 for c in captures if any(k in c["label"] for k in ("배치도", "조감도", "위치도")))
        captures += fetch_homepage_assets(detail, max_plan=max(0, 4 - pdf_plan),
                                          max_site=max(0, 2 - pdf_site))
    except Exception as e:
        logger.info(f"홈페이지 도면 수집 예외(무시): {e.__class__.__name__}")

    # 주변 실거래 시세(국토부) — 가격 적정성의 확정 팩트 근거 (2026-07-17, 실패해도 발행)
    rt_facts = None
    try:
        from generator.rt_price import build_trade_facts
        rt_facts = build_trade_facts(detail.get("HSSPLY_ADRES", ""), types)
    except Exception as e:
        logger.warning(f"실거래 시세 수집 실패(무시): {e}")

    facts = build_facts(detail, types, excerpt)
    if rt_facts:
        facts["주변 아파트 실거래 시세(국토교통부, 최근 6개월)"] = rt_facts
    topic = {
        "keyword": f"{name} 청약",
        "category": hub_display(HUB_ID),
        "hub_id": HUB_ID,
        "facts": facts,
        "key_stats": build_key_stats(detail, types),
        "sources": [(f"{name} 입주자모집공고 (청약홈)", detail.get("PBLANC_URL", "") or "https://www.applyhome.co.kr"),
                    ("청약홈 청약일정", "https://www.applyhome.co.kr")],
        "use_search": True,  # 주변 시세·여건 맥락 보강 (톤 가드는 extra_instructions)
        "extra_instructions": _EXTRA_INSTRUCTIONS,
    }

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음")
        sys.exit(1)

    from generator.deep_content import generate_deep_post
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("청약 분석글 생성 실패")
        sys.exit(1)

    if dry_run:
        logger.info(f"[DRY_RUN] 생성만 완료: {post['title']!r} "
                    f"(본문 {len(post.get('body', ''))}자, 캡처 {len(captures)}장) — 발행 생략")
        return

    from generator.wp_render import render_wordpress_post
    from poster.wp_publish import (publish_wordpress, check_connection,
                                   upload_media_info, set_featured_image)
    if not check_connection():
        logger.error("WP 연결 실패")
        sys.exit(1)

    slug = f"cheongyak-{detail.get('HOUSE_MANAGE_NO', key)}"
    post_url = f"{WP_URL.rstrip('/')}/{slug}/"
    r = render_wordpress_post(
        post, category=topic["category"], base_url=post_url, slug_override=slug,
        related_posts=_related_housing_posts(), site_url=WP_URL, category_slug=HUB_ID,
    )

    # 공고문 캡처(금액표·평면도) — 관련 섹션 '안'에 삽입 (2026-07-17 사용자 피드백)
    def _upload(path, alt_suffix="", page=0):
        return upload_media_info(path, f"{slug}-notice-p{page}.png",
                                 alt_text=f"{name} {alt_suffix}")

    new_html, inserted = _insert_captures_inline(r["content_html"], name, captures, _upload)
    if inserted:
        r["content_html"] = new_html
        logger.info("공고문 캡처 섹션 내 삽입 완료")
    else:
        # 캡처가 없으면 본문 일러스트로 시각 요소 보강 (금액표 있으면 원문이 우선)
        try:
            from generator.wp_body_images import add_body_illustrations
            r["content_html"] = add_body_illustrations(
                r["content_html"], topic["keyword"], topic["category"], GOOGLE_API_KEY, slug=slug)
        except Exception as e:
            logger.warning(f"본문 일러스트 실패(무시): {e}")

    res = publish_wordpress(r, title=post["title"], status=status, category=topic["category"])
    if not res:
        logger.error("발행 실패")
        sys.exit(1)
    logger.info(f"발행 완료 [{res['status']}] id={res['id']} {res['link']}")

    # 대표 이미지 (best-effort)
    try:
        from generator.wp_featured import build_featured_image
        img = build_featured_image(post["title"], topic["keyword"], topic["category"],
                                   HUB_ID, api_key=GOOGLE_API_KEY)
        if img:
            info = upload_media_info(img, f"featured-{slug}.png", alt_text=post["title"])
            try:
                os.unlink(img)
            except OSError:
                pass
            if info:
                set_featured_image(res["id"], info["id"])
    except Exception as e:
        logger.warning(f"대표 이미지 실패(무시): {e}")

    if status == "publish":
        history[key] = {
            "date": datetime.now(KST).strftime("%Y-%m-%d"),
            "house_nm": name,
            "region": detail.get("SUBSCRPT_AREA_CODE_NM", ""),
            "slug": slug,
            "post_url": res.get("link", ""),
            "remainder": bool(detail.get("_remainder")),
        }
        _save_history(history)


if __name__ == "__main__":
    run()
