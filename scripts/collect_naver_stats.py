# -*- coding: utf-8 -*-
"""네이버 블로그 통계 자동 수집기 (크리에이터 어드바이저 내부 API).

로그인 세션 쿠키(data/naver_cookies.json)로 creator-advisor.naver.com 의
내부 JSON API(/api/v6/...)를 조회해 일별 조회수·방문자, 게시글별 조회수,
유입 검색어를 data/naver_insights.json 으로 저장한다.

인증 구조 (2026-07 확인):
  1) 네이버 로그인 쿠키(NID_AUT/NID_SES) 로 /api/v6/accounts/channels 호출
     → 응답 Set-Cookie 로 __ca_key 발급 (이게 없으면 다른 API 는 403 CA_KEY_INVALID)
  2) 이후 모든 요청에 HMAC-SHA256 서명 헤더 부착
     key = __ca_key 쿠키값의 첫 '.' 앞 조각
     msg = "GET|{요청 pathname}|{ts_ms}|{nonce}"
     헤더 = X-CA-Nonce / X-CA-Ts / X-CA-Sig(hex)

사용:
  python scripts/collect_naver_stats.py
  python scripts/collect_naver_stats.py --blog-id hyungsutech --cookie-file data/tech_naver_cookies.json
"""
import argparse
import hashlib
import hmac
import io
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
KST = timezone(timedelta(hours=9))

BASE = "https://creator-advisor.naver.com/api/v6"
SERVICE = "naver_blog"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
PAUSE = 1.2  # 과요청 방지 (요청 간 대기 초)


class CookieExpired(RuntimeError):
    """세션 쿠키 만료/미로그인."""


# ── 세션 ─────────────────────────────────────────────────────
def build_session(cookie_file: str, blog_id: str) -> requests.Session:
    if not os.path.isfile(cookie_file):
        raise CookieExpired(f"쿠키 파일 없음: {cookie_file}")
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://creator-advisor.naver.com/{SERVICE}/{blog_id}",
    })
    with open(cookie_file, encoding="utf-8") as f:
        cookies = json.load(f)
    for c in cookies:
        try:
            s.cookies.set(c["name"], c["value"],
                          domain=c.get("domain", ".naver.com"), path=c.get("path", "/"))
        except Exception:
            continue
    return s


def bootstrap(s: requests.Session, blog_id: str) -> dict:
    """채널 목록 조회 = 로그인 확인 + __ca_key 발급."""
    r = s.get(f"{BASE}/accounts/channels", timeout=30)
    if r.status_code in (401, 403):
        raise CookieExpired("로그인 세션 없음(401/403)")
    try:
        chans = r.json().get("data") or []
    except Exception:
        raise CookieExpired("채널 응답 파싱 실패 — 로그인 페이지로 리다이렉트 추정")
    if not chans:
        raise CookieExpired("채널 목록이 비어 있음")
    if "__ca_key" not in {c.name for c in s.cookies}:
        raise CookieExpired("__ca_key 미발급 — 세션 무효")
    for c in chans:
        if c.get("channelId") == blog_id:
            return c
    raise RuntimeError(
        f"'{blog_id}' 채널이 이 계정에 없음. 보유 채널: "
        f"{[c.get('channelId') for c in chans]}")


def _sig_headers(s: requests.Session, url: str) -> dict:
    raw = s.cookies.get("__ca_key")
    if not raw:
        return {}
    key = raw.split(".")[0]
    nonce = str(uuid.uuid4())
    ts = str(int(time.time() * 1000))
    msg = f"GET|{urlparse(url).path}|{ts}|{nonce}"
    return {
        "X-CA-Nonce": nonce, "X-CA-Ts": ts,
        "X-CA-Sig": hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest(),
    }


def api(s: requests.Session, path: str, params: dict):
    """GET /api/v6{path} → data 필드. 실패 시 (None, 사유)."""
    time.sleep(PAUSE)
    url = BASE + path
    try:
        r = s.get(url, params=params, timeout=30, headers=_sig_headers(s, url))
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"
    if r.status_code == 401:
        raise CookieExpired(f"401 Unauthorized ({path})")
    try:
        j = r.json()
    except Exception:
        return None, f"HTTP {r.status_code} non-JSON"
    if r.status_code != 200 or j.get("status") == "fail":
        return None, f"HTTP {r.status_code} {j.get('message', '')[:60]}"
    return j.get("data"), ""


# ── 기간 헬퍼 ────────────────────────────────────────────────
def last_complete_week(today: date) -> date:
    """마지막 '완결된' 주의 월요일 (월~일 창이 오늘 이전에 끝난 주)."""
    monday = today - timedelta(days=today.weekday())  # 이번 주 월요일
    return monday - timedelta(days=7)


def last_complete_month(today: date) -> date:
    """마지막 '완결된' 달의 1일."""
    first = today.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def log_no(content_id: str) -> str:
    return (content_id or "").rstrip("/").rsplit("/", 1)[-1]


# ── 응답 슬림 헬퍼 (2026-07-31 전수 수집 확장) ───────────────
# age 코드 → 라벨 (creator-advisor 번들 실측: "01":"0-12세" … "11":"60세-")
_AGE_LABELS = {"01": "0-12", "02": "13-18", "03": "19-24", "04": "25-29",
               "05": "30-34", "06": "35-39", "07": "40-44", "08": "45-49",
               "09": "50-54", "10": "55-59", "11": "60+"}


def _slim_demo(rows) -> list:
    """demo/follower-distribution 응답 → [{age, age_label, total, f, m}]."""
    out = []
    for r in rows or []:
        g = {x.get("gender"): x.get("metricValue") for x in r.get("genderList") or []}
        out.append({"age": r.get("age"), "age_label": _AGE_LABELS.get(r.get("age"), ""),
                    "total": r.get("metricValue"), "f": g.get("f"), "m": g.get("m")})
    return out


def _slim_ranks(rows, blog_id: str) -> list:
    """cv/like/reply-ranks 공통 파서 → [{rank, title, value, logNo, url}]."""
    out = []
    for r in rows or []:
        cid = r.get("contentId") or r.get("metaUrl") or ""
        out.append({"rank": r.get("rank"), "title": r.get("title", ""),
                    "value": r.get("metricValue"), "logNo": log_no(cid),
                    "url": f"https://blog.naver.com/{blog_id}/{log_no(cid)}" if cid else ""})
    return out


# ── 수집 ─────────────────────────────────────────────────────
def collect(blog_id: str, cookie_file: str, days: int = 30) -> dict:
    s = build_session(cookie_file, blog_id)
    chan = bootstrap(s, blog_id)
    common = {"service": SERVICE, "channelId": blog_id}
    notes = []

    today = datetime.now(KST).date()
    start = today - timedelta(days=days - 1)

    # ① 일별 조회수 / 순방문자 / 방문횟수
    daily_map = {}
    for metric, field in (("view-count", "views"), ("uv-count", "visitors"),
                          ("visit-count", "visits")):
        data, err = api(s, f"/integrated-analysis/{metric}",
                        {**common, "interval": "day",
                         "startDate": start.isoformat(), "endDate": today.isoformat()})
        if data is None:
            notes.append(f"daily.{field}({metric}) 실패: {err}")
            continue
        for row in data:
            d = row.get("date")
            if d:
                daily_map.setdefault(d, {"date": d})[field] = row.get("metricValue")

    # ①-확장. 일별 체류시간·공감·댓글 (2026-07-31 전수 수집 지시 — _probe_stats_api 실측 경로)
    for metric, field in (("average-duration", "avg_duration_sec"),
                          ("like-count", "likes"), ("reply-count", "replies")):
        data, err = api(s, f"/integrated-analysis/{metric}",
                        {**common, "interval": "day",
                         "startDate": start.isoformat(), "endDate": today.isoformat()})
        if data is None:
            notes.append(f"daily.{field}({metric}) 실패: {err}")
            continue
        for row in data:
            d = row.get("date")
            if d:
                v = row.get("metricValue")
                if field == "avg_duration_sec" and isinstance(v, float):
                    v = round(v, 1)
                daily_map.setdefault(d, {"date": d})[field] = v

    # ①-확장. 일별 이웃 증감 (followerAdds/Removes/bothFollowerAdds=서로이웃)
    data, err = api(s, "/integrated-analysis/follower-count",
                    {**common, "interval": "day",
                     "startDate": start.isoformat(), "endDate": today.isoformat()})
    if data is None:
        notes.append(f"daily.follower(follower-count) 실패: {err}")
    else:
        for row in data:
            d = row.get("date")
            if d:
                row_d = daily_map.setdefault(d, {"date": d})
                row_d["follower_adds"] = row.get("followerAdds")
                row_d["follower_removes"] = row.get("followerRemoves")
                row_d["both_follower_adds"] = row.get("bothFollowerAdds")

    daily = [daily_map[k] for k in sorted(daily_map)]
    if not daily:
        notes.append("daily 전체 수집 실패")

    # ② 게시글별 조회수 — 최근 완결 주 우선, 실패 시 어제 하루
    top_posts, posts_period = [], ""
    yesterday = today - timedelta(days=1)
    for interval, dt, label in (
        ("week", last_complete_week(today), "최근 완결 주(월~일)"),
        ("day", yesterday, "어제 하루"),
    ):
        data, err = api(s, "/integrated-analysis/cv-ranks",
                        {**common, "interval": interval, "date": dt.isoformat(), "limit": 30})
        if data:
            posts_period = f"{label} 기준 {dt.isoformat()}"
            for row in data:
                cid = row.get("contentId") or row.get("metaUrl") or ""
                created = row.get("createdAt")
                top_posts.append({
                    "title": row.get("title", ""),
                    "logNo": log_no(cid),
                    "views": row.get("metricValue"),
                    "rank": row.get("rank"),
                    "url": f"https://blog.naver.com/{blog_id}/{log_no(cid)}" if cid else "",
                    "created_at": (datetime.fromtimestamp(created / 1000, KST).isoformat(timespec="minutes")
                                   if created else ""),
                })
            break
        notes.append(f"top_posts({interval}) 실패: {err}")

    # ③ 유입 검색어 — 주간 우선, 실패 시 어제 하루
    search_queries, sq_period = [], ""
    for interval, dt, label in (
        ("week", last_complete_week(today), "최근 완결 주(월~일)"),
        ("day", yesterday, "어제 하루"),
    ):
        data, err = api(s, "/inflow-analysis/referrer-query-rank",
                        {**common, "metric": "cv", "interval": interval,
                         "date": dt.isoformat(), "limit": 30})
        if data:
            blk = data[0] if isinstance(data, list) and data else {}
            total = blk.get("totalMetric") or 0
            sq_period = f"{label} 기준 {dt.isoformat()}"
            for it in blk.get("topN") or []:
                ratio = it.get("ratio") or 0
                search_queries.append({
                    "query": it.get("searchQuery", ""),
                    "count": round(ratio * total),   # API 자체 비율 × 기간 총 조회수
                    "ratio": round(ratio, 6),
                    "referrer": (it.get("referrer") or "").split("?")[0],
                })
            if search_queries:
                break
        else:
            notes.append(f"search_queries({interval}) 실패: {err}")

    # ④ 요약 (어제/그제 조회·방문·검색유입)
    summary = {}
    data, err = api(s, "/home/yesterday-summary",
                    {"date": today.isoformat(), "service": SERVICE, "channelId": blog_id})
    if data:
        dts = data.get("date") or []
        cv = data.get("cv") or {}

        def last(seq):
            return seq[-1] if isinstance(seq, list) and seq else None

        summary = {
            "date": last(dts),
            "views": last(cv.get("cv") or []),
            "visits": last(cv.get("visit") or []),
            "visitors": last(cv.get("uv") or []),
            "search_inflow": last((data.get("searchInflow") or {}).get("searchInflow") or []),
            "main_inflow": last((data.get("mainInflow") or {}).get("mainInflow") or []),
        }
    else:
        notes.append(f"summary 실패: {err}")

    # ⑤ 주간 사용자 분석 — 지난 완결 주(월~일) 기준 (2026-07-31 전수 수집 지시).
    # 재방문율·평균 방문횟수는 주간/월간 창만 받는다(day interval 은 400 — 실측).
    ws = last_complete_week(today)
    we = ws + timedelta(days=6)
    weekly = {"week_start": ws.isoformat(), "week_end": we.isoformat()}
    data, err = api(s, "/integrated-analysis/retention-rate",
                    {**common, "interval": "week",
                     "startDate": ws.isoformat(), "endDate": we.isoformat()})
    if data:
        weekly["retention_rate"] = round(data[0].get("metricValue") or 0, 6)
        weekly["returning_visitors"] = data[0].get("retention")
    else:
        notes.append(f"weekly.retention-rate 실패: {err}")
    data, err = api(s, "/integrated-analysis/average-visit",
                    {**common, "interval": "week",
                     "startDate": ws.isoformat(), "endDate": we.isoformat()})
    if data:
        weekly["average_visit"] = round(data[0].get("metricValue") or 0, 4)
    else:
        notes.append(f"weekly.average-visit 실패: {err}")

    wparams = {**common, "interval": "week", "date": ws.isoformat()}
    data, err = api(s, "/integrated-analysis/demo-distribution", {**wparams, "metric": "cv"})
    if data:
        weekly["demo"] = _slim_demo(data)
    else:
        notes.append(f"weekly.demo 실패: {err}")
    data, err = api(s, "/integrated-analysis/device-distribution", {**wparams, "metric": "cv"})
    if data:
        weekly["device"] = [{"device": r.get("device"), "views": r.get("metricValue")}
                            for r in data]
    else:
        notes.append(f"weekly.device 실패: {err}")
    data, err = api(s, "/integrated-analysis/country-distribution", {**wparams, "metric": "cv"})
    if data:
        weekly["country"] = [{"country": r.get("countryCode"), "views": r.get("metricValue"),
                              "ratio": round(r.get("ratio") or 0, 6)} for r in data[:10]]
    else:
        notes.append(f"weekly.country 실패: {err}")
    # actionType 유효값은 add/delete (cancel·remove·unfollow 는 400 — 2026-07-31 실측)
    for action, key in (("add", "follower_add_demo"), ("delete", "follower_delete_demo")):
        data, err = api(s, "/integrated-analysis/follower-distribution",
                        {**wparams, "actionType": action})
        if data:
            weekly[key] = _slim_demo(data)
        else:
            notes.append(f"weekly.{key} 실패: {err}")
    for rank_path, key in (("like-ranks", "like_ranks"), ("reply-ranks", "reply_ranks")):
        data, err = api(s, f"/integrated-analysis/{rank_path}", {**wparams, "limit": 30})
        if data:
            weekly[key] = _slim_ranks(data, blog_id)
        else:
            notes.append(f"weekly.{key} 실패: {err}")
    data, err = api(s, "/integrated-analysis/d1-ranks", {**wparams, "limit": 30})
    if data:
        weekly["topic_ranks"] = data          # [{rank, d1(주제), metricValue}]
    else:
        notes.append(f"weekly.topic_ranks 실패: {err}")
    data, err = api(s, "/home/popular-category-keyword",
                    {**common, "date": ws.isoformat()})
    if data:
        weekly["popular_category_keyword"] = data   # 내 카테고리 인기 검색어
    else:
        notes.append(f"weekly.popular_category_keyword 실패: {err}")
    data, err = api(s, "/home/popular-demo-keyword", {**common, "date": ws.isoformat()})
    if data:
        weekly["popular_demo_keyword"] = data       # 내 독자층 인기 검색어(없으면 미수록)
    data, err = api(s, "/inflow-analysis/query-compare",
                    {**common, "metric": "cv", "interval": "week",
                     "date": ws.isoformat(), "limit": 30})
    if data:
        weekly["query_compare"] = data              # 유입검색어 경쟁 비교(my/totalMean/topMean)
    else:
        notes.append(f"weekly.query_compare 실패: {err}")

    # ⑥ 어제 시간대별 조회 (hour-distribution 은 interval 없이 date 하루 단위만 — 실측)
    hourly = {}
    data, err = api(s, "/integrated-analysis/hour-distribution",
                    {**common, "metric": "cv", "date": yesterday.isoformat()})
    if data:
        hourly = {"date": yesterday.isoformat(), "rows": data}  # metrics=[조회?, 방문?, 비율?] 원형 보존
    else:
        notes.append(f"hourly 실패: {err}")

    # ⑦ 오늘 실시간 + 급상승 게시물
    realtime = {}
    data, err = api(s, "/home/realtime-summary",
                    {**common, "date": today.isoformat()})
    if data:
        realtime["summary"] = data
    else:
        notes.append(f"realtime.summary 실패: {err}")
    data, err = api(s, "/home/realtime-summary-histogram",
                    {**common, "date": today.isoformat(), "metricType": "cv"})
    if data:
        realtime["histogram"] = data
    soaring = []
    data, err = api(s, "/home/soaring-contents",
                    {**common, "interval": "day", "date": yesterday.isoformat()})
    if data:
        for r in data[:20]:
            cid = r.get("contentId") or ""
            soaring.append({"title": r.get("title", ""), "logNo": log_no(cid),
                            "value": r.get("metricValue"),
                            "url": f"https://blog.naver.com/{blog_id}/{log_no(cid)}" if cid else ""})
    else:
        notes.append(f"soaring 실패: {err}")

    # 오늘(집계 진행 중) 수치
    today_row = next((d for d in daily if d.get("date") == today.isoformat()), {})
    views_30d = sum(d.get("views") or 0 for d in daily)
    visitors_30d = sum(d.get("visitors") or 0 for d in daily)

    # 대시보드(_insights) 호환 posts 배열
    posts = [{
        "id": p["logNo"], "ts": p.get("created_at", ""), "type": "post", "code": "",
        "title": p["title"], "url": p["url"], "views": p["views"],
        "visitors": None, "likes": None, "replies": None,
    } for p in top_posts]

    return {
        "updated": datetime.now(KST).isoformat(timespec="minutes"),
        "blog_id": blog_id,
        "account": chan.get("channelName") or blog_id,
        "platform": "naverblog",
        "today": {"date": today.isoformat(),
                  "views": today_row.get("views"), "visitors": today_row.get("visitors")},
        "summary": summary,
        "views_30d": views_30d,
        "visitors_30d": visitors_30d,
        "posts_period": posts_period,
        "search_period": sq_period,
        "daily": daily,
        "top_posts": top_posts,
        "search_queries": search_queries,
        "posts": posts,
        # 2026-07-31 전수 수집 확장 — 소비처(대시보드)는 미지 필드를 무시하므로 하위호환
        "weekly": weekly,
        "hourly_yesterday": hourly,
        "realtime_today": realtime,
        "soaring_yesterday": soaring,
        "notes": notes,
    }


def save(out: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    _append_inflow_daily(out)


def _append_inflow_daily(out: dict) -> None:
    """일별 유입 채널(검색/메인) 누적 — data/naver_inflow_daily.json (2026-08-01 신설).

    배경: 트래픽 재비교(traffic_recompare)에서 '메인 노출이 언제 시작됐나'를 판정할
    일별 채널 시계열이 없어 추정에 그쳤다. yesterday-summary의 검색/메인 유입을
    수집 때마다 날짜 키로 쌓아 시계열을 만든다(같은 날짜는 덮어씀 — 멱등)."""
    sm = out.get("summary") or {}
    d = sm.get("date")
    if not d:
        return
    path = os.path.join(DATA_DIR, "naver_inflow_daily.json")
    try:
        acc = json.load(open(path, encoding="utf-8"))
    except Exception:
        acc = {}
    blog = out.get("blog_id", "?")
    acc.setdefault(blog, {})[d] = {
        "views": sm.get("views"), "visitors": sm.get("visitors"),
        "search": sm.get("search_inflow"), "main": sm.get("main_inflow"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=1)


def report(out: dict, path: str) -> None:
    t = out.get("today") or {}
    sm = out.get("summary") or {}
    print(f"💾 저장: {path}", flush=True)
    print(f"   채널 {out['account']}({out['blog_id']}) · 갱신 {out['updated']}", flush=True)
    print(f"   오늘({t.get('date')}) 조회 {t.get('views')} · 방문자 {t.get('visitors')}"
          f"   |  어제({sm.get('date')}) 조회 {sm.get('views')} · 방문자 {sm.get('visitors')}"
          f" · 검색유입 {sm.get('search_inflow')}", flush=True)
    print(f"   최근 30일 누적 조회 {out['views_30d']} · 방문자 {out['visitors_30d']}"
          f" (일별 {len(out['daily'])}건)", flush=True)
    print(f"   인기글 {len(out['top_posts'])}건 [{out.get('posts_period') or '-'}]", flush=True)
    for p in out["top_posts"][:5]:
        print(f"     {p['views']:>5}v  {(p['title'] or '')[:38]}", flush=True)
    print(f"   유입검색어 {len(out['search_queries'])}건 [{out.get('search_period') or '-'}]", flush=True)
    for q in out["search_queries"][:5]:
        print(f"     {q['count']:>4}회  {q['query'][:30]}", flush=True)
    wk = out.get("weekly") or {}
    if wk:
        rr = wk.get("retention_rate")
        dev = " · ".join(f"{d.get('device')} {d.get('views')}" for d in (wk.get("device") or []))
        print(f"   주간({wk.get('week_start')}~{wk.get('week_end')})"
              f" 재방문율 {f'{rr * 100:.2f}%' if rr is not None else '-'}"
              f" · 평균방문 {wk.get('average_visit', '-')}"
              f" · 기기별 {dev or '-'}", flush=True)
        demo = [r for r in (wk.get("demo") or []) if r.get("total")]
        if demo:
            top3 = sorted(demo, key=lambda r: -(r.get("total") or 0))[:3]
            print("   성별연령 상위: " + " · ".join(
                f"age{r['age']} 계{r['total']}(여{r.get('f')}/남{r.get('m')})" for r in top3),
                flush=True)
    hr = out.get("hourly_yesterday") or {}
    rows = hr.get("rows") or []
    if rows:
        peak = max(rows, key=lambda r: (r.get("metrics") or [0])[0])
        print(f"   어제 시간대 피크: {peak.get('hour')}시 (metrics {peak.get('metrics')})", flush=True)
    if out.get("soaring_yesterday"):
        s0 = out["soaring_yesterday"][0]
        print(f"   급상승 1위: {(s0.get('title') or '')[:38]} ({s0.get('value')})", flush=True)
    for n in out.get("notes") or []:
        print(f"   ⚠ {n}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="네이버 블로그 통계 수집 (크리에이터 어드바이저 API)")
    ap.add_argument("--blog-id", default="hyunji_unni")
    ap.add_argument("--cookie-file", default=os.path.join(DATA_DIR, "naver_cookies.json"))
    ap.add_argument("--out", default=None, help="기본: data/naver_insights.json")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--skip-tech", action="store_true",
                    help="기본 실행 시 형수의테크공장(hyungsutech) 추가 수집을 생략")
    a = ap.parse_args()

    cookie_file = a.cookie_file if os.path.isabs(a.cookie_file) else os.path.join(ROOT, a.cookie_file)
    out_path = a.out or os.path.join(DATA_DIR, "naver_insights.json")
    if not os.path.isabs(out_path):
        out_path = os.path.join(ROOT, out_path)

    try:
        data = collect(a.blog_id, cookie_file, a.days)
    except CookieExpired as e:
        print(f"❌ 네이버 세션 쿠키 만료/무효: {e}", flush=True)
        print("   → 재발급: python scripts/get_cookies.py 재실행 필요"
              f" (쿠키 파일: {cookie_file})", flush=True)
        sys.exit(2)
    save(data, out_path)
    report(data, out_path)

    # 형수의테크공장 — 별도 쿠키 파일이 있으면 추가 수집 시도(실패해도 메인 결과는 유지)
    tech_cookie = os.path.join(DATA_DIR, "tech_naver_cookies.json")
    if (not a.skip_tech and a.blog_id == "hyunji_unni"
            and a.out is None and os.path.isfile(tech_cookie)):
        print("\n── 형수의테크공장(hyungsutech) 추가 수집", flush=True)
        tech_out = os.path.join(DATA_DIR, "naver_insights_tech.json")
        try:
            td = collect("hyungsutech", tech_cookie, a.days)
            save(td, tech_out)
            report(td, tech_out)
        except CookieExpired as e:
            print(f"   ⚠ 테크 계정 쿠키 만료: {e}", flush=True)
            print("     → python scripts/get_cookies_tech.py 재실행 필요", flush=True)
        except Exception as e:
            print(f"   ⚠ 테크 계정 수집 실패: {type(e).__name__}: {str(e)[:100]}", flush=True)


if __name__ == "__main__":
    main()
