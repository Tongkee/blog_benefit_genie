# -*- coding: utf-8 -*-
"""아침 증시 브리핑 데이터 수집 — 무지개로그 포맷 실험 트랙 (2026-07-29 사용자 지시).

밤사이 글로벌 지표를 Yahoo Finance 차트 API(키 불요)로 수집한다. 수치는 전부 여기서
확정하고 LLM은 해석 문장만 쓴다(수치 창작 원천 차단 — 인포카드와 같은 원칙).

섹션 순서는 벤치마크(무지개로그) 고정 골격: 미국 3대 지수 → 반도체 → 유가 → 금리/환율 →
달러인덱스 → VIX → 금 → 비트코인 → 중국 → 국내 예상. (docs/BENCHMARK_무지개로그.md §③)
"""
import logging
import time

import requests

logger = logging.getLogger("market_brief")

# (심볼, 표기명, 이모지, 소수자릿수, 단위)
INDICATORS = [
    ("^IXIC",     "나스닥",          "✅", 2, ""),
    ("^GSPC",     "S&P500",         "✅", 2, ""),
    ("^DJI",      "다우존스",         "✅", 2, ""),
    ("^SOX",      "필라델피아 반도체",  "🔧", 2, ""),
    ("CL=F",      "WTI 국제유가",     "🛢", 2, "달러"),
    ("^TNX",      "미 국채 10년물",    "🏦", 2, "%"),
    ("KRW=X",     "원/달러 환율",     "💵", 1, "원"),
    ("DX-Y.NYB",  "달러인덱스",       "💲", 2, ""),
    ("^VIX",      "공포지수 VIX",     "😨", 2, ""),
    ("GC=F",      "국제 금",         "🥇", 1, "달러"),
    ("BTC-USD",   "비트코인",         "₿", 0, "달러"),
    ("000001.SS", "중국 상하이종합",   "🇨🇳", 2, ""),
    ("^KS11",     "코스피(전일)",     "🇰🇷", 2, ""),
]

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}


def _fetch_quote(symbol: str) -> dict | None:
    """전일 종가 대비 최신가·등락률. Yahoo v8 chart(무키)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = requests.get(url, params={"range": "5d", "interval": "1d"}, headers=_UA, timeout=15)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        meta = res["meta"]
        price = meta.get("regularMarketPrice")
        closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c]
        prev = meta.get("chartPreviousClose")
        # 마지막 봉이 오늘(진행 중)이면 직전 봉 종가가 더 정확한 '전일'
        if len(closes) >= 2 and price and abs(closes[-1] - price) / max(price, 1e-9) < 0.001:
            prev = closes[-2]
        if not price or not prev:
            return None
        return {"price": float(price), "prev": float(prev),
                "pct": (float(price) / float(prev) - 1) * 100}
    except Exception as e:
        logger.info(f"{symbol} 시세 실패(스킵): {e.__class__.__name__}")
        return None


def collect_market_data() -> list[dict]:
    """[{name, emoji, price_str, pct, pct_str, up}] — 실패 지표는 제외(섹션 자체 생략)."""
    out = []
    for sym, name, emoji, nd, unit in INDICATORS:
        q = _fetch_quote(sym)
        time.sleep(0.4)
        if not q:
            continue
        price = round(q["price"], nd) if nd else int(round(q["price"]))
        price_str = f"{price:,.{nd}f}" if nd else f"{price:,}"
        if unit == "%":
            price_str = f"{q['price']:.2f}%"
        elif unit:
            price_str += unit if unit == "원" else f" {unit}"
        pct = q["pct"]
        out.append({
            "symbol": sym, "name": name, "emoji": emoji,
            "price_str": price_str, "pct": round(pct, 2),
            "pct_str": f"({'+' if pct >= 0 else ''}{pct:.2f}%)",
            "up": pct >= 0,
            # 원시 수치(2026-07-31 §1.C 계산 슬롯용) — 표기용 price_str과 별개로
            # 코드 계산에 쓸 원본 값을 보존한다
            "price": q["price"], "prev": q["prev"],
        })
    logger.info(f"시장 지표 수집 {len(out)}/{len(INDICATORS)}개")
    return out


def market_one_liner(data: list[dict]) -> str:
    """서론용 '한 줄 정리' 소재 — 예: '지수는 혼조, 유가는 급락, 반도체는 조정'."""
    def _pick(name):
        return next((d for d in data if name in d["name"]), None)
    frags = []
    idx = [d for d in data if d["name"] in ("나스닥", "S&P500", "다우존스")]
    if len(idx) >= 2:
        ups = sum(1 for d in idx if d["up"])
        frags.append("지수는 " + ("일제히 상승" if ups == len(idx) else "일제히 하락" if ups == 0 else "혼조"))
    for key, label in (("유가", "유가"), ("반도체", "반도체"), ("환율", "환율"), ("비트코인", "비트코인")):
        d = _pick(key)
        if d and abs(d["pct"]) >= 1.0:
            direction = "급등" if d["pct"] >= 2 else "상승" if d["up"] else "급락" if d["pct"] <= -2 else "하락"
            frags.append(f"{label}는 {direction}")
    return ", ".join(frags[:4])
