# -*- coding: utf-8 -*-
"""요즘경제 벤치마크 소스 블로그 발굴 — 3개 → 50~100개 (NEXT_SESSION §2-④).

수집: 네이버 블로그 '주제별 글' 비즈니스·경제 피드(directorySeq=33, 공개 AJAX,
비로그인)를 여러 페이지 훑어 블로그 ID를 모은다. 일반 키워드 검색은 잡블로그가
지배해 버려서(실측) 주제 분류 피드를 쓴다.

검증(전부 통과해야 후보):
- RSS 생존(blog.rss.naver.com/{id}.xml 200 + item 존재)
- 최근 14일 내 발행
- RSS 제목의 경제 키워드 비율 ≥ 0.3 (경제 전업 블로그만)
- 광고성 어휘(분양·상담·문의·홍보) 제목 비율 < 0.2

출력: data/econ_sources.json — econ_digest.fetch_candidates 가 로테이션으로 사용.
사용: py -3 scripts/discover_econ_blogs.py [목표개수=60]
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import requests  # noqa: E402

KST = timezone(timedelta(hours=9))
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
     "Referer": "https://section.blog.naver.com/ThemePost.naver"}
ECON_RE = re.compile(r"경제|금리|주식|증시|코스피|나스닥|부동산|아파트|환율|달러|엔화|세금|"
                     r"절세|연금|투자|ETF|채권|실적|공시|물가|GDP|재테크|배당|청약|대출|은행")
AD_RE = re.compile(r"분양|상담|문의|홍보|이벤트 참여|체험단|협찬")
CORE = {"ranto28", "hong8706", "ppassong"}


# 검색 쿼리 — 경제 전업 블로거가 반복 등장할 만한 주제들
QUERIES = ["코스피 전망", "금리 인하 전망", "환율 전망", "부동산 시장 분석", "미국 증시 정리",
           "경제 공부", "세금 절세 방법", "연금 투자", "ETF 투자 전략", "기업 실적 분석",
           "물가 상승 원인", "재테크 공부"]


def harvest(pages_per_query: int = 5) -> dict:
    """수집 → {id: {name, count, titles}}.

    ①주제 피드(directorySeq=33)는 페이지네이션이 안 먹혀(항상 같은 10건 — 실측)
    1페이지만 보너스로 쓰고, ②본대는 SearchList(페이지네이션 정상)를 경제 쿼리
    여러 개로 훑는다. 품질은 여기서가 아니라 verify()의 RSS 게이트가 만든다.
    """
    found: dict = {}

    def _add(bid, name, title):
        if not bid or bid in CORE:
            return
        e = found.setdefault(bid, {"name": (name or "").strip(), "count": 0, "titles": []})
        e["count"] += 1
        if title:
            e["titles"].append(title[:40])

    try:
        r = requests.get("https://section.blog.naver.com/ajax/DirectoryPostList.naver",
                         params={"directorySeq": 33, "currentPage": 1, "countPerPage": 10},
                         headers=H, timeout=12)
        for it in (json.loads(r.text.lstrip(")]}',\n")).get("result") or {}).get("postList") or []:
            _add(it.get("domainIdOrBlogId"), it.get("nickName"),
                 (it.get("noTagTitle") or it.get("title") or "").strip())
    except Exception as e:
        print(f"  주제피드 실패(무해) {e.__class__.__name__}")

    for q in QUERIES:
        for page in range(1, pages_per_query + 1):
            try:
                r = requests.get("https://section.blog.naver.com/ajax/SearchList.naver",
                                 params={"countPerPage": 7, "currentPage": page,
                                         "keyword": q, "orderBy": "sim", "type": "post"},
                                 headers={**H, "Referer": "https://section.blog.naver.com/Search/Post.naver"},
                                 timeout=12)
                lst = (json.loads(r.text.lstrip(")]}',\n")).get("result") or {}).get("searchList") or []
            except Exception as e:
                print(f"  {q!r} p{page} 실패 {e.__class__.__name__}")
                continue
            for it in lst:
                _add(it.get("domainIdOrBlogId"), it.get("nickName") or it.get("blogName"),
                     (it.get("noTagTitle") or "").strip())
            time.sleep(0.35)
    return found


def verify(bid: str) -> "dict | None":
    """RSS 생존 + 최근성 + 경제성 + 비광고성 검증. 통과 시 요약 반환."""
    try:
        r = requests.get(f"https://blog.rss.naver.com/{bid}.xml", headers=H, timeout=12)
        if r.status_code != 200 or "<item>" not in r.text:
            return None
        titles = re.findall(r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                            r.text, re.S)[:20]
        dates = re.findall(r"<pubDate>(.*?)</pubDate>", r.text)[:20]
        if len(titles) < 5:
            return None
        econ = sum(1 for t in titles if ECON_RE.search(t)) / len(titles)
        ad = sum(1 for t in titles if AD_RE.search(t)) / len(titles)
        if econ < 0.3 or ad >= 0.2:
            return None
        recent = False
        for d in dates[:3]:
            m = re.search(r"(\d{1,2}) (\w{3}) (\d{4})", d)
            if m:
                try:
                    dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                           "%d %b %Y")
                    if datetime.now() - dt <= timedelta(days=14):
                        recent = True
                        break
                except ValueError:
                    continue
        if not recent:
            return None
        return {"econ_ratio": round(econ, 2), "sample": titles[0][:40]}
    except Exception:
        return None


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print("주제 피드(비즈니스·경제) 수집 중…")
    found = harvest()
    print(f"블로그 {len(found)}개 수집 — RSS 검증 시작(느림: 개당 ~1초)")
    ranked = sorted(found.items(), key=lambda kv: -kv[1]["count"])
    out = []
    for bid, meta in ranked:
        if len(out) >= target:
            break
        v = verify(bid)
        time.sleep(0.5)
        if not v:
            continue
        out.append({"id": bid, "name": meta["name"] or bid, "feed_count": meta["count"],
                    "econ_ratio": v["econ_ratio"], "sample": v["sample"]})
        print(f"  ✅ {bid:<20} {meta['name'][:14]:<14} 경제성 {v['econ_ratio']:.2f}  {v['sample']}")
    dst = os.path.join(ROOT, "data", "econ_sources.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n검증 통과 {len(out)}개 → {os.path.normpath(dst)} (코어 3개는 SOURCES에 유지)")


if __name__ == "__main__":
    main()
