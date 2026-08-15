# -*- coding: utf-8 -*-
"""아침증시 브리핑 '🧮 오늘의 계산' 슬롯 (2026-07-31 — NEXT_SESSION §1.C).

공개 수치 2개 → 사칙연산 1건 → 체감 단위 환산. 매일 다른 계산 1건을 넣어
고정 코너로 만든다(벤치마크 실측: 서킷브레이커 글 댓글 474건의 결정타가
'219조 ÷ 49조 = 1.9년' 계산이었다).

원칙(인수인계서 지시 그대로):
- ★계산은 전부 코드가 한다. LLM에 산수를 시키면 실패한다(실측 확정) —
  이 모듈은 LLM을 부르지 않고 문장까지 결정론 템플릿으로 조립한다(오류 여지 0).
- ★화이트리스트 게이트: FORMULAS에 등록된 산식만 실행된다. 미등록 산식 요청이나
  입력 수치 결손이면 None(슬롯 생략) — 잘못된 계산을 내보내느니 코너를 뺀다.
- ★모든 계산은 입력값·산식·출처·출력을 로그로 남긴다.

수치 출처: generator.market_brief.collect_market_data (Yahoo Finance chart API,
raw price/prev 필드). 외부 상수는 물리 단위 환산값만 쓴다(시세·통계 상수 금지).
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("calc_slot")
KST = timezone(timedelta(hours=9))

# 물리 단위 환산 상수(고정 사실 — 시세 아님)
_BARREL_L = 158.987   # 원유 1배럴 = 158.987L
_OZT_G = 31.1035      # 1트로이온스 = 31.1035g
_DON_G = 3.75         # 금 1돈 = 3.75g


def _get(data: list, name_kw: str) -> "dict | None":
    d = next((d for d in data if name_kw in d.get("name", "")), None)
    return d if d and isinstance(d.get("price"), (int, float)) else None


def _fmt_krw(v: float) -> str:
    if v >= 1e8:
        return f"{v / 1e8:,.1f}억원"
    if v >= 1e4:
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


# ── 산식 구현부 — 각 함수는 (섹션 본문 줄 목록) 또는 None 반환 ──────────
def _f_gold_don(data):
    """금 1돈 원화 환산: 금($/온스) × 환율 ÷ (온스/돈)."""
    gold, fx = _get(data, "국제 금"), _get(data, "환율")
    if not gold or not fx:
        return None
    don = _OZT_G / _DON_G                      # 1온스 = 8.29돈
    krw_oz = gold["price"] * fx["price"]
    krw_don = krw_oz / don
    logger.info(f"[calc:gold_don] in: gold={gold['price']} fx={fx['price']} "
                f"(Yahoo Finance) → 1돈 {krw_don:,.0f}원")
    return [
        f"✅ 국제 금 {gold['price_str']} × 환율 {fx['price_str']}",
        f"금 1온스를 원화로 바꾸면 약 {_fmt_krw(krw_oz)}입니다.",
        f"1온스는 {don:.1f}돈이니, 금 1돈이면 약 {_fmt_krw(krw_don)}입니다.",
        "아기 돌반지 1돈을 오늘 시세로 환산한 값입니다.",
    ]


def _f_oil_liter(data):
    """기름 1리터 원가 감각: WTI($/배럴) × 환율 ÷ 배럴당 리터."""
    oil, fx = _get(data, "유가"), _get(data, "환율")
    if not oil or not fx:
        return None
    krw_bbl = oil["price"] * fx["price"]
    krw_l = krw_bbl / _BARREL_L
    logger.info(f"[calc:oil_liter] in: wti={oil['price']} fx={fx['price']} "
                f"(Yahoo Finance) → 리터 {krw_l:,.0f}원")
    return [
        f"✅ WTI {oil['price_str']} × 환율 {fx['price_str']}",
        f"원유 1배럴({_BARREL_L:.0f}L)을 원화로 바꾸면 약 {_fmt_krw(krw_bbl)}입니다.",
        f"1리터로 나누면 원유 원가는 리터당 약 {krw_l:,.0f}원입니다.",
        "주유소 기름값에서 세금·정제·유통 비용을 빼기 전의 순수 원유값입니다.",
    ]


def _f_btc_krw(data):
    """비트코인 1개 원화 환산."""
    btc, fx = _get(data, "비트코인"), _get(data, "환율")
    if not btc or not fx:
        return None
    krw = btc["price"] * fx["price"]
    logger.info(f"[calc:btc_krw] in: btc={btc['price']} fx={fx['price']} "
                f"(Yahoo Finance) → {krw:,.0f}원")
    return [
        f"✅ 비트코인 {btc['price_str']} × 환율 {fx['price_str']}",
        f"비트코인 1개를 원화로 바꾸면 약 {_fmt_krw(krw)}입니다.",
        f"0.01개(1%)만 있어도 약 {_fmt_krw(krw / 100)}인 셈입니다.",
    ]


def _f_tech_spread(data):
    """기술주 쏠림: 나스닥 등락률 − S&P500 등락률(%p)."""
    nas, spx = _get(data, "나스닥"), _get(data, "S&P500")
    if not nas or not spx:
        return None
    gap = nas["pct"] - spx["pct"]
    direction = "더 크게 움직였습니다" if abs(nas["pct"]) >= abs(spx["pct"]) else "덜 움직였습니다"
    logger.info(f"[calc:tech_spread] in: nasdaq={nas['pct']}% spx={spx['pct']}% "
                f"(Yahoo Finance) → gap {gap:+.2f}%p")
    return [
        f"✅ 나스닥 {nas['pct_str']} vs S&P500 {spx['pct_str']}",
        f"두 지수의 등락률 차이는 {gap:+.2f}%p입니다.",
        f"기술주가 시장 전체보다 {abs(gap):.2f}%p {direction}.",
    ]


def _f_fx_10k(data):
    """환율 변동 체감: 1만 달러 환전 시 어제와의 차액."""
    fx = _get(data, "환율")
    if not fx or not isinstance(fx.get("prev"), (int, float)):
        return None
    diff = (fx["price"] - fx["prev"]) * 10_000
    word = "더 들어갑니다" if diff > 0 else "덜 들어갑니다"
    logger.info(f"[calc:fx_10k] in: fx={fx['price']} prev={fx['prev']} "
                f"(Yahoo Finance) → 1만달러 차액 {diff:+,.0f}원")
    return [
        f"✅ 원/달러 {fx['price_str']} (전일 {fx['prev']:,.1f}원)",
        f"오늘 1만 달러를 환전하면 어제보다 약 {_fmt_krw(abs(diff))} {word}.",
        "유학비·수입 결제 같은 목돈 송금에서 하루 환율 차이가 만드는 금액입니다.",
    ]


# ── 화이트리스트 — 여기 등록된 산식만 실행 가능(미등록=발행 금지 게이트) ──
FORMULAS = {
    "gold_don": _f_gold_don,
    "oil_liter": _f_oil_liter,
    "btc_krw": _f_btc_krw,
    "tech_spread": _f_tech_spread,
    "fx_10k": _f_fx_10k,
}


def build_calc_section(data: list, formula: "str | None" = None) -> "str | None":
    """오늘의 계산 섹션 본문 반환(섹션 헤더 포함). 만들 수 없으면 None(슬롯 생략).

    formula 미지정 시 날짜(연중 일수) 기준으로 로테이션 — 매일 다른 계산 1건.
    지정 시 화이트리스트 검사: 미등록 산식이면 None(게이트).
    """
    if formula is not None:
        fn = FORMULAS.get(formula)
        if fn is None:
            logger.error(f"[calc] 미등록 산식 {formula!r} — 화이트리스트 게이트, 슬롯 생략")
            return None
        order = [formula]
    else:
        keys = list(FORMULAS)
        start = datetime.now(KST).timetuple().tm_yday % len(keys)
        order = keys[start:] + keys[:start]   # 오늘 산식부터, 입력 결손 시 다음 산식 폴백
    for key in order:
        try:
            lines = FORMULAS[key](data)
        except Exception as e:
            logger.warning(f"[calc:{key}] 계산 실패(다음 산식): {e}")
            continue
        if lines:
            logger.info(f"[calc] 오늘의 산식: {key}")
            return "\n\n".join(["[구분선]\n🧮 오늘의 계산"] + lines)
    logger.warning("[calc] 실행 가능한 산식 없음 — 슬롯 생략")
    return None
