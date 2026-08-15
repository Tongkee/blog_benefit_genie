"""주간 자체 품질 감사 (2026-07-19, 사용자 지시 — 발행량 증가 대비 자체점검 체계).

2026-07-19 수동 심층 점검(13건, 오류 5건 적발)을 자동화한 것. 최근 7일 발행 글을
라이브에서 수집해 Gemini가 '독자 입장 + 팩트체커' 관점으로 채점하고, 결과를 GH 이슈
"[품질 감사] 날짜"로 보고한다. 재발행 권고 글에는 실행 커맨드까지 첨부(반자동 보완).

채점 기준(수동 점검과 동일): ①주제-내용 일치 ②수치 신뢰성(고시값·배점·세율 의심 수치)
③구조-내용 매치(소제목을 본문이 부정하는지) ④무관 내용 혼입 ⑤반복·빈약 ⑥이미지 캡션 신호.
실행: GH Actions 주 1회(quality_audit.yml). 수동: python -m scripts.quality_audit
"""
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from generator.content import _gen_text

KST = timezone(timedelta(hours=9))
LOG_PATH = os.path.join(ROOT, "data", "quality_audit_log.json")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_POSTS = 10
DAYS = 7

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("quality_audit")


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _strip_html(html: str, cap: int = 7000) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"&[a-z#0-9]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:cap]


def _naver_body(post_url: str) -> str:
    m = re.search(r"blog.naver.com/([^/]+)/(\d+)", post_url)
    if not m:
        return ""
    raw = _get(f"https://blog.naver.com/PostView.naver?blogId={m.group(1)}&logNo={m.group(2)}")
    main = raw.find("se-main-container")
    return _strip_html(raw[main:main + 60000] if main > 0 else raw)


def _collect() -> list[dict]:
    """최근 DAYS일 발행 글 수집 — 파이프라인별 최신 위주로 최대 MAX_POSTS건."""
    cutoff = (datetime.now(KST) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    posts: list[dict] = []

    import glob
    hist_files = (glob.glob(os.path.join(ROOT, "data", "info_*_history.json"))
                  + [os.path.join(ROOT, "data", f) for f in
                     ("gov_history.json", "tech_history.json", "cheongyak_naver_history.json")])
    for f in hist_files:
        d = _load(f, [])
        items = d if isinstance(d, list) else list(d.values())
        recent = [x for x in items if isinstance(x, dict) and str(x.get("date", "")) >= cutoff
                  and (x.get("post_url") or "").startswith("http")
                  and x.get("status", "posted") == "posted"]
        for x in recent[-2:]:
            posts.append({"pipeline": os.path.basename(f).replace("_history.json", ""),
                          "title": x.get("keyword") or x.get("headline", ""),
                          "url": x["post_url"], "kind": "naver"})

    try:
        wp = json.loads(_get("https://hyunjiunni.com/wp-json/wp/v2/posts?per_page=4&orderby=date"))
        for p in wp:
            if str(p.get("date", ""))[:10] >= cutoff:
                posts.append({"pipeline": "wp", "title": re.sub(r"<[^>]+>", "", p["title"]["rendered"]),
                              "url": p["link"], "kind": "web"})
    except Exception as e:
        logger.warning(f"WP 수집 실패: {e}")

    try:
        soyu = json.loads(_get(
            "https://raw.githubusercontent.com/parky091999-sudo/soyu_blog/master/data/post_history.json"))
        for x in (soyu if isinstance(soyu, list) else []):
            if str(x.get("date", "")) >= cutoff and (x.get("url") or "").startswith("http") \
                    and x.get("status") == "posted":
                posts.append({"pipeline": "soyu", "title": x.get("title", ""),
                              "url": x["url"], "kind": "web"})
    except Exception as e:
        logger.warning(f"soyu 수집 실패: {e}")

    return posts[:MAX_POSTS]


_JUDGE_SYS = (
    f"오늘 날짜는 {datetime.now(KST).strftime('%Y년 %m월 %d일')}이다. "
    "따라서 글의 '2026년 기준' 표기는 정상적인 현재 시점 표기다 — "
    "'미래 시점이라 확정되지 않았다'는 유형의 지적은 절대 금지(네 학습 시점보다 시간이 지났다). "
    "수치 자체가 2026년 실제 고시·법령과 다르다고 판단될 때만 지적하라.\n"
    "너는 블로그 품질 감사관이자 팩트체커다. 글 본문을 읽고 JSON만 출력한다.\n"
    "채점 기준: ①제목·주제와 본문 내용 일치 ②수치 신뢰성 — 특히 법정 고시값·배점표·세율구간"
    "(예: 청약 가점 배점, 기준 중위소득, 종소세 구간)이 어긋나 보이면 반드시 지적하고 '왜 의심되는지' 근거를 써라 "
    "③구조-내용 매치(소제목을 본문이 스스로 부정하는 어색함) ④주제와 무관한 문장 혼입 "
    "⑤같은 표현 3회+ 반복, 정보 빈약(메타정보만 나열) ⑥폐지된 용어(공인인증서 등).\n"
    "확신 없는 수치 지적은 severity를 낮추고 '검증 필요'로 표기. 과잉 지적 금지 — 실제 독자에게 해가 되는 것만."
)


def _judge(post: dict, body: str, api_key: str) -> dict:
    prompt = (
        f"[파이프라인] {post['pipeline']}\n[제목] {post['title']}\n[URL] {post['url']}\n"
        f"[본문 텍스트]\n{body}\n\n"
        "JSON 한 개만: {\"score\": 1~10, \"issues\": [{\"type\": \"수치|주제일치|구조|혼입|빈약|용어\", "
        "\"severity\": \"high|mid|low\", \"detail\": \"…\"}], \"republish\": true|false, "
        "\"gate_suggestion\": \"재발 방지용 생성 규칙 제안 1줄(없으면 빈 문자열)\", \"summary\": \"한 줄 총평\"}"
    )
    raw = _gen_text(api_key, prompt, _JUDGE_SYS, 2048, 0.3)
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _make_issue(results: list[dict]) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    bad = [r for r in results if r["judge"].get("republish")]
    lines = [f"> 자동 생성: 최근 {DAYS}일 발행 글 {len(results)}건 자체 품질 감사", ""]
    lines.append("| 점수 | 파이프라인 | 글 | 총평 |")
    lines.append("|---|---|---|---|")
    for r in sorted(results, key=lambda x: x["judge"].get("score", 10)):
        j = r["judge"]
        lines.append(f"| {j.get('score', '?')} | {r['post']['pipeline']} | "
                     f"[{r['post']['title'][:28]}]({r['post']['url']}) | {j.get('summary', '')[:60]} |")
    if any(r["judge"].get("issues") for r in results):
        lines += ["", "## 발견 사항"]
        for r in results:
            for i in r["judge"].get("issues", []):
                lines.append(f"- **[{i.get('severity')}|{i.get('type')}]** "
                             f"{r['post']['title'][:24]}: {i.get('detail', '')[:200]}")
    if bad:
        lines += ["", "## 재발행 권고 (실행 커맨드)"]
        for r in bad:
            kw = r["post"]["title"]
            lines.append(f"- {kw}: 원글 삭제 후 `gh workflow run info_post.yml -f keyword='{kw}' "
                         f"-f force_post=true -f facts='<검증 수치>'` (파이프라인에 맞는 워크플로 사용)")
    gates = [r["judge"].get("gate_suggestion", "") for r in results if r["judge"].get("gate_suggestion")]
    if gates:
        lines += ["", "## 게이트 개선 제안"]
        lines += [f"- {g}" for g in dict.fromkeys(gates)]
    try:
        from generator.official_facts import overdue_reviews
        due = overdue_reviews()
        if due:
            lines += ["", "## ⏰ 고시값 DB 재검토 기한 경과 — 공식 소스 대조 후 갱신 필요"]
            lines += [f"- {d}" for d in due]
    except Exception:
        pass
    lines += ["", "처리 루틴: 이 이슈를 확인 후 \"품질 감사 이슈 검토해줘\"."]
    return f"[품질 감사] {today}\n" + "\n".join(lines)


def _post_issue(title_body: str):
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "parky091999-sudo/hyunji_unni_blog")
    title, body = title_body.split("\n", 1)
    if not token:
        print(title, "\n", body)
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body, "labels": ["quality-audit"]}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        logger.info(f"이슈 생성: {r.status}")


def run():
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        logger.error("GOOGLE_API_KEY 없음")
        return
    posts = _collect()
    logger.info(f"감사 대상 {len(posts)}건")
    if not posts:
        return
    results = []
    for p in posts:
        try:
            body = _naver_body(p["url"]) if p["kind"] == "naver" else _strip_html(_get(p["url"]))
            if len(body) < 300:
                logger.warning(f"본문 수집 실패/빈약 — 스킵: {p['url']}")
                continue
            j = _judge(p, body, api_key)
            if j:
                results.append({"post": p, "judge": j})
                logger.info(f"[{j.get('score')}] {p['pipeline']} {p['title'][:24]} — {j.get('summary', '')[:40]}")
        except Exception as e:
            logger.warning(f"감사 실패({p['url']}): {str(e)[:80]}")
    if not results:
        return
    log = _load(LOG_PATH, [])
    log.append({"date": datetime.now(KST).strftime("%Y-%m-%d"),
                "n": len(results),
                "avg": round(sum(r["judge"].get("score", 0) for r in results) / len(results), 1),
                "republish": sum(1 for r in results if r["judge"].get("republish"))})
    json.dump(log[-52:], open(LOG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _post_issue(_make_issue(results))


if __name__ == "__main__":
    run()
