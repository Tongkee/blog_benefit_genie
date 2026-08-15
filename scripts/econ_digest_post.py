# -*- coding: utf-8 -*-
"""실험B 발행: 요즘경제 쉽게보기 — 유명 경제 블로그 소싱 → 베네핏지니화 (2026-07-29).

매일 10:00 KST 1건. 소스: 메르·홍춘욱·빠숑 (RSS 감지 → 팩트만 추출 → 완전 재작성).
표절 하드 게이트: 원문과 15자+ 연속 겹침 발견 시 재생성(최대 2회), 그래도 겹치면 발행 포기.

사용: python -m scripts.econ_digest_post   (DRAFT=true 임시저장 검증)
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (DATA_DIR, GOOGLE_API_KEY, NAVER_BLOG_ID, NAVER_COOKIES,  # noqa: E402
                    NAVER_ID, NAVER_PW)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("econ_digest_post")
KST = timezone(timedelta(hours=9))
STATE_PATH = os.path.join(DATA_DIR, "econ_digest_state.json")
CATEGORY = os.environ.get("ECON_CATEGORY", "쉽게보는 요즘경제")  # 실제 생성된 카테고리명(2026-07-29)


def run():
    draft = os.environ.get("DRAFT", "false").lower() == "true"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        state = json.load(open(STATE_PATH, encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {"seen": [], "posted": {}}
    state.setdefault("seen", [])
    state.setdefault("posted", {})
    if today in state["posted"] and not draft:
        logger.info(f"오늘({today}) 이미 발행 — 종료")
        return
    if not GOOGLE_API_KEY or not NAVER_ID:
        logger.error("GOOGLE_API_KEY / NAVER_ID 필요 — 종료")
        sys.exit(1)

    from generator.econ_digest import (fetch_candidates, fetch_body_text, pick_topic, rhythm_issues,
                                       extract_facts, write_post, overlap_guard)
    cands = fetch_candidates(set(state["seen"]))
    if not cands:
        logger.info("신규 소스 글 없음 — 오늘 쉼")
        return
    # ★소스 폴백(2026-07-31 신설). 종전에는 후보를 12건 모아놓고 **1건만 시도**한 뒤
    # 표절 게이트에 걸리면 그대로 발행을 포기했다. 세법·부동산 분석글은 개념 문장이
    # 그대로 겹치기 쉬워 특정 소스는 몇 번을 다시 써도 통과하지 못한다. 그 결과
    # 이 트랙은 신설 이후 **한 번도 발행에 성공하지 못했다**(state의 posted가 빈 채였다).
    # → 게이트는 그대로 두고(표절 방지가 이 트랙의 존재 이유다), 실패한 소스는 버리고
    #   다음 후보로 넘어간다. 게이트를 느슨하게 푸는 것보다 안전하다.
    # ★M1 번호 팩트 연대기 우선(2026-07-31 — NEXT_SESSION §1.D): 주제만 블로그에서
    # 빌리고 사실은 1차 원문(DART 오늘공시 RSS)에서 직접 가져온다. 4-튜플 적재 →
    # URL·금지목록·날짜 게이트 → 기계 번호 → LLM 튜플→문장 변환 → 숫자 대조 게이트
    # (실패 항목은 삭제+번호 재부여) → 하한(ECON_M1_MIN, 기본 15항) 게이트.
    # 하한 미달이면 기존 서사형으로 폴백한다(전환기 발행 공백 방지 — 이 트랙은
    # '조용한 발행 0건'을 이미 한 번 겪었다).
    post, topic, src_text = None, None, ""
    try:
        from generator.fact_chronicle import (bok_press_facts, dart_today_facts,
                                              llm_render, load_facts, min_items_gate,
                                              render_body, topic_keywords,
                                              verify_rendered)
        m1_topic = cands[0]
        _kws = topic_keywords(m1_topic.get("title", ""))
        items = load_facts(dart_today_facts(_kws) + bok_press_facts(_kws))
        m1_min = int(os.environ.get("ECON_M1_MIN", "15"))
        if len(items) >= m1_min:
            verified = verify_rendered(items, llm_render(items, GOOGLE_API_KEY))
            if min_items_gate(verified, m1_min):
                body = render_body(verified, m1_topic.get("title", ""))
                post = {"title": f"공시로 본 {m1_topic.get('title', '')[:24]} 연대기"[:48],
                        "body": body, "subheadings": [],
                        "tags": ["경제이슈", "공시", "DART", "팩트정리", "요즘경제"]}
                topic = m1_topic
                logger.info(f"[M1] 연대기 발행 경로: {len(verified)}항 (1차 원문 DART)")
        else:
            logger.info(f"[M1] 1차 원문 팩트 {len(items)}항 < {m1_min} — 서사형 폴백")
    except Exception as e:
        logger.warning(f"[M1] 연대기 경로 실패(서사형 폴백): {e.__class__.__name__}: {e}")

    MAX_SOURCES = 4
    pool = list(cands)
    failed: list[str] = []
    # M1 연대기가 이미 만들어졌으면 서사형 루프는 건너뛴다
    for src_no in range(0 if post else MAX_SOURCES):
        if not pool:
            break
        topic = pick_topic(pool, GOOGLE_API_KEY)
        if not topic:
            break
        pool = [c for c in pool if c.get("url") != topic.get("url")]
        logger.info(f"[소스 {src_no + 1}/{MAX_SOURCES}] 선정: [{topic['author']}] {topic['title']!r}")

        src_text = fetch_body_text(topic["blog_id"], topic["log_no"])
        if len(src_text) < 600:
            logger.warning("원문 본문 확보 실패 — 다음 후보")
            state["seen"].append(topic["url"])
            continue
        facts = extract_facts(src_text, topic["author"], GOOGLE_API_KEY)
        if not facts or len(facts.get("facts") or []) < 5:
            logger.warning("팩트 추출 부족 — 다음 후보")
            state["seen"].append(topic["url"])
            continue

        avoid: list[str] = []
        style_fb: list[str] = []
        best = None
        for attempt in range(3):
            p = write_post(facts, topic["author"], GOOGLE_API_KEY,
                           avoid=avoid or None, style_feedback=style_fb or None)
            if not p:
                continue
            hits = overlap_guard(p["body"], src_text)
            if hits:
                avoid = sorted(set(avoid + hits))[:10]
                logger.warning(f"원문 겹침 {len(hits)}건({hits[0][:15]}…) — "
                               f"재생성 {attempt + 1} (겹침 되먹임)")
                continue
            # ★서사 호흡 게이트(2026-07-31): 표절은 통과했어도 호흡이 정보성 글로
            # 돌아가면 이 코너의 존재 이유가 없다. 몰입감이 상품이다.
            # ★골격 게이트(B — NEXT_SESSION §1.B): 메르 실측 상수(1문단 1문장·87자·
            # 서술체 순도·볼드 금지·마감 3문장 코멘트)를 같은 되먹임 루프에 묶는다.
            from generator.econ_digest import paragraphize as _paraz
            from generator.skeleton_gate import (closing_comment_issues, closing_slot,
                                                 skeleton_issues)
            _pb = _paraz(p["body"])
            style_fb = rhythm_issues(p["body"])
            style_fb += [i for i in skeleton_issues(_pb, register="narrative")
                         if i not in style_fb]
            style_fb += closing_comment_issues(closing_slot(_pb), _pb)
            if style_fb:
                best = best or p          # 표절은 깨끗하니 최후 폴백으로 보관
                logger.warning(f"서사 호흡 미달 {len(style_fb)}건 — 재생성 {attempt + 1}: "
                               f"{style_fb[0][:50]}")
                continue
            post = p
            break
        if not post and best:
            # 3회 안에 호흡까지 못 맞췄으면, 표절만 깨끗한 초안으로 낸다(발행 0건보다 낫다)
            logger.warning("서사 호흡 게이트 3회 미달 — 표절 통과본으로 발행")
            post = best
        if post:
            break
        logger.warning(f"소스 게이트 3회 실패 — 이 소스 폐기하고 다음 후보로: {topic['title'][:40]!r}")
        failed.append(topic["title"][:40])
        state["seen"].append(topic["url"])   # 다시 뽑히지 않도록
        _save(state)

    if not post:
        # ★조용한 실패 금지(2026-07-31): 종전엔 return 0으로 끝나 워크플로가 초록불이었다.
        logger.error(f"소스 {len(failed)}건 연속 게이트 실패 — 발행 포기")
        print(f"::error::요즘경제 발행 0건 — 소스 {len(failed)}건이 모두 표절 게이트 실패 "
              f"({', '.join(failed[:3])}). 소스 선정 기준 재검토 필요")
        _save(state)
        sys.exit(1)
    if failed:
        logger.info(f"(소스 {len(failed)}건 건너뛰고 성공)")
    logger.info(f"생성 완료: {post['title']!r} ({len(post['body'])}자)")

    # ★문단 정리(2026-07-31): 문장은 짧은데 줄바꿈만 써서 에디터에서 한 덩어리로 붙었다.
    # 1~2문장마다 빈 줄로 끊어 한 화면의 글자 수를 벤치마크 수준으로 낮춘다.
    from generator.econ_digest import paragraphize, place_body_images
    post["body"] = paragraphize(post["body"])

    # ★골격 게이트(B — 2026-07-31): 첫 블록 이미지 금지(메르 24/24 첫 블록 텍스트).
    # 헤더카드도 맨 위가 아니라 본문 125자 뒤 첫 슬롯에 넣는다. 이미지를 먼저 다
    # 만들고 개수만큼 누적 글자수 기준으로 마커를 배치해 마커↔이미지 정합을 보장한다.
    images = []
    try:
        from poster.infographic_html import create_infographic_via_html
        header = create_infographic_via_html(title=post["title"], keyword="요즘경제",
                                             category="금융재테크", bullets=None)
        if header:
            images.append({"local_path": header, "url": "", "alt_text": post["title"], "label": ""})
    except Exception as e:
        logger.warning(f"헤더카드 실패(본문 일러스트만): {e}")
    try:
        from poster.illustration import generate_editorial_illustration
        for _ in range(2):
            path = generate_editorial_illustration(
                post["title"], category="금융재테크", api_key=GOOGLE_API_KEY)
            if path:
                images.append({"local_path": path, "url": "",
                               "alt_text": f"{post['title']} 관련 이미지", "label": ""})
    except Exception as e:
        logger.warning(f"본문 일러스트 실패(무시): {e}")
    if images:
        post["body"], markers = place_body_images(post["body"], n=len(images), start_no=1)
        if len(markers) < len(images):
            logger.info(f"본문이 짧아 이미지 {len(images) - len(markers)}장 미배치(뒤쪽부터 버림)")
            images = images[:len(markers)]
        logger.info(f"이미지 {len(images)}장 누적 글자수 배치(125자→509자당→88.6%)")

    from poster.naver_blog import post_to_naver_blog
    try:
        result = post_to_naver_blog(
            naver_id=NAVER_ID, naver_pw=NAVER_PW, blog_id=NAVER_BLOG_ID or NAVER_ID,
            title=post["title"], body=post["body"], tags=post["tags"],
            naver_cookies=NAVER_COOKIES, images=images or None, draft=draft,
            allow_pw_login=os.environ.get("ALLOW_PW_LOGIN", "false").lower() == "true",
            # ★골격 게이트(B): 소제목 컴포넌트 금지 — 메르 24건 실측 se-sectionTitle 0개.
            # 소제목이 없으면 크기 변경·볼드도 함께 사라진다(렌더러가 소제목에만 적용).
            subheadings=[], category=CATEGORY,
            # ★이 코너만 벤치마크(메르) 서식 — 나눔고딕 16px(2026-07-31 실측 대조).
            # 다른 트랙은 기존 나눔마루부리 유지(블로그 전체를 한 번에 바꾸면
            # 기존 127건과 새 글의 서식이 갈린다).
            body_font=os.environ.get("ECON_FONT", "nanumgothic"),
            body_font_size=os.environ.get("ECON_FONT_SIZE", "16"),
        )
    except Exception as e:
        logger.error(f"포스팅 중 예외: {e}")
        sys.exit(1)
    if draft:
        logger.info(f"[DRAFT] 임시저장 결과: {result}")
        return
    post_url = (result or {}).get("post_url", "")
    if not post_url or "Redirect=Write" in post_url:
        logger.error(f"발행 실패 — URL: {post_url}")
        sys.exit(1)
    state["seen"] = (state["seen"] + [topic["url"]])[-200:]
    state["posted"][today] = {"title": post["title"], "post_url": post_url,
                              "source": f"{topic['author']} {topic['url']}"}
    _save(state)
    logger.info(f"요즘경제 발행 완료: {post_url}")


def _save(state: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    run()
