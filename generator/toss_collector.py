"""토스증권 Open API 수집기 — 실계좌 투자 기록 시리즈용 (2026-07-17 뼈대 구축).

상태: 토스 Open API 사전신청 대기 중(키 미발급). 공식 openapi.json(v1.2.4,
docs/toss_openapi.json)과 스펙 내 예시 응답을 기준으로 선구축 — 키 발급 시
TOSS_CLIENT_ID/TOSS_CLIENT_SECRET만 .env·시크릿에 넣으면 실데이터로 전환된다.

인증(2겹): OAuth2 Client Credentials → Bearer 토큰 + 계좌 API는 X-Tossinvest-Account
헤더(accountSeq — /accounts에서 1회 조회 후 캐싱: ACCOUNT 그룹 rate limit 초당 1회).
MOCK 모드: 키 없음 또는 TOSS_MOCK=true → data/toss_mock_examples.json(스펙 공식 예시).
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DATA_DIR  # noqa: E402  (dotenv 로드 부수효과 포함)

logger = logging.getLogger("toss_collector")

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.tossinvest.com"
_TIMEOUT = 20
_CACHE_PATH = os.path.join(DATA_DIR, "toss_account_cache.json")
_MOCK_PATH = os.path.join(DATA_DIR, "toss_mock_examples.json")

_token_cache = {"token": "", "exp": 0.0}


def _creds() -> tuple[str, str]:
    return os.getenv("TOSS_CLIENT_ID", "").strip(), os.getenv("TOSS_CLIENT_SECRET", "").strip()


def is_mock() -> bool:
    cid, sec = _creds()
    return os.getenv("TOSS_MOCK", "").lower() == "true" or not (cid and sec)


def _mock(path: str):
    d = json.load(open(_MOCK_PATH, encoding="utf-8"))
    return d[path]["result"]


def _token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["exp"] - 60:
        return _token_cache["token"]
    cid, sec = _creds()
    r = requests.post(f"{BASE}/oauth2/token", data={
        "grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    _token_cache["token"] = d["access_token"]
    _token_cache["exp"] = time.time() + float(d.get("expires_in", 3600))
    return _token_cache["token"]


def _get(path: str, params: dict | None = None, account: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    if account:
        headers["X-Tossinvest-Account"] = str(_account_seq())
    r = requests.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=_TIMEOUT)
    if r.status_code == 429:
        time.sleep(1.2)  # rate limit — 1회 재시도(배치라 여유)
        r = requests.get(f"{BASE}{path}", params=params or {}, headers=headers, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("result", {})


def _account_seq() -> int:
    try:
        c = json.load(open(_CACHE_PATH, encoding="utf-8"))
        if c.get("accountSeq") is not None:
            return c["accountSeq"]
    except Exception:
        pass
    accounts = _get("/api/v1/accounts") if not is_mock() else _mock("/api/v1/accounts")
    rows = accounts if isinstance(accounts, list) else accounts.get("accounts", [])
    seq = rows[0]["accountSeq"]
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump({"accountSeq": seq, "cached_at": datetime.now(KST).isoformat()},
              open(_CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    logger.info(f"토스 accountSeq 캐싱: {seq}")
    return seq


def fetch_holdings() -> dict:
    """보유 현황 — 총매입/평가/손익(수수료·세금 차감 후 포함)/일간손익 + 종목 리스트."""
    if is_mock():
        logger.info("토스 MOCK 모드 — 스펙 예시 응답 사용(키 발급 전)")
        return _mock("/api/v1/holdings")
    return _get("/api/v1/holdings", account=True)


def fetch_recent_orders(days: int = 8) -> list[dict]:
    """최근 N일 체결 주문. Order History는 status(OPEN/CLOSED) 필수 → 완료(CLOSED)분 조회.
    주문 조회 실패 시 [] 반환(보유자산만으로도 인증글 생성되도록 graceful, 2026-07-22)."""
    if is_mock():
        orders = _mock("/api/v1/orders").get("orders", [])
    else:
        try:
            res = _get("/api/v1/orders", params={"status": "CLOSED"}, account=True)
            orders = res if isinstance(res, list) else res.get("orders", [])
        except Exception as e:
            logger.warning(f"주문 내역 조회 실패 — 보유자산만 사용: {str(e)[:120]}")
            return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).isoformat()
    out = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        if (o.get("orderedAt") or o.get("orderDate") or o.get("executedAt") or "") < cutoff:
            continue
        st = str(o.get("status", "")).upper()
        if st in ("FILLED", "PARTIAL_FILLED", "FULLY_FILLED", "EXECUTED", "CLOSED") or o.get("executedQuantity"):
            out.append(o)
    return out


def fetch_exchange_rate() -> str:
    try:
        if is_mock():
            return ""
        res = _get("/api/v1/exchange-rate",
                   params={"baseCurrency": "USD", "quoteCurrency": "KRW"})
        return str(res.get("rate") or res.get("exchangeRate") or "")
    except Exception:
        return ""


# ── 리포트 팩트 빌드 ─────────────────────────────────────────────────────────

def _num(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _fmt_krw(v) -> str:
    n = _num(v)
    return f"{n:,.0f}원"


def _pct(v) -> str:
    return f"{_num(v) * 100:.2f}%"


def _qty(v) -> str:
    """보유/체결 수량 — 소수점 과다(6자리) 방지. 최대 3자리, 끝 0 제거."""
    n = _num(v)
    s = f"{n:,.3f}".rstrip("0").rstrip(".")
    return s or "0"


def _money(usd, fx: float) -> str:
    """USD 금액을 '$X (약 Y원)'으로. KRW는 API가 0이라 환율로 환산."""
    u = _num(usd)
    if not u:
        return "-"
    if fx:
        return f"${u:,.2f} (약 {u * fx:,.0f}원)"
    return f"${u:,.2f}"


_MANUAL_PATH = os.path.join(DATA_DIR, "toss_manual_snapshot.json")


def has_manual_snapshot() -> bool:
    return os.path.exists(_MANUAL_PATH)


def build_manual_facts(period_label: str) -> dict:
    """API 승인 전 반자동 모드 — 사용자가 캡처로 준 실계좌 스냅샷(수기 파싱본)을 팩트로.
    계좌번호 등 식별정보는 스냅샷에 아예 넣지 않는 것이 원칙(2026-07-17)."""
    s = json.load(open(_MANUAL_PATH, encoding="utf-8"))
    facts = {
        "기준": f"{period_label} (토스증권 실계좌, {s.get('as_of', '')} 캡처 기준)",
        "계좌 요약": s.get("summary", {}),
        "보유 종목": s.get("holdings", []),
        "이번 주 매매·자금 흐름": s.get("trades_this_week", []),
        "최근 배당": s.get("dividends_recent", []),
        "대기 중인 조건주문": s.get("pending_orders", []),
        "운용 메모(주인장 관점)": s.get("notes", []),
    }
    return {k: v for k, v in facts.items() if v}


def build_invest_facts(period_label: str) -> dict:
    """holdings+orders → deep_content facts. 계좌번호 등 식별정보는 수집 자체를 안 한다.
    키 미발급이어도 수동 스냅샷이 있으면 그것(실데이터)을 우선 사용."""
    if is_mock() and has_manual_snapshot():
        logger.info("토스 수동 스냅샷(실계좌 캡처) 모드 — API 승인 전 반자동")
        return build_manual_facts(period_label)
    h = fetch_holdings()
    orders = fetch_recent_orders()
    fx = fetch_exchange_rate()

    items = h.get("items", [])
    fx_f = _num(fx)
    rows = []
    for it in items:
        pl = it.get("profitLoss", {})
        mv = it.get("marketValue", {})
        rows.append({
            "종목": it.get("name") or it.get("symbol", ""),
            "수량": _qty(it.get("quantity")),
            "평단가($)": f"{_num(it.get('averagePurchasePrice')):,.2f}",
            "현재가($)": f"{_num(it.get('lastPrice')):,.2f}",
            "평가액": _money(mv.get("amount"), fx_f),
            "수익률": _pct(pl.get("rateAfterCost") or pl.get("rate")),
        })

    trades = []
    buy_amt_usd = 0.0
    for o in orders:
        ex = o.get("execution", {})
        if o.get("side") == "BUY":
            buy_amt_usd += _num(ex.get("filledAmount") or o.get("orderAmount"))
        trades.append({
            "일시": (o.get("orderedAt") or "")[:10],
            "구분": "매수" if o.get("side") == "BUY" else "매도",
            "종목": o.get("symbol", ""),
            "체결수량": _qty(ex.get("filledQuantity")),
            "체결금액": _money(ex.get("filledAmount"), fx_f),
        })

    # 적립식(주식 모으기) 요약 — 주문 대부분이 소액 매수면 DCA로 간주(2026-07-22 사용자 확인)
    buys = [o for o in orders if o.get("side") == "BUY"]
    dca = {}
    if buys and len(buys) >= max(1, len(orders) - 1):
        amts = sorted({int(round(_num(o.get("orderAmount")))) for o in buys if _num(o.get("orderAmount"))})
        dca = {
            "방식": "주식 모으기(적립식·DCA) — 매일 종목별로 정해둔 소액을 자동 매수",
            "이번 기간 매수": f"{len(buys)}건",
            "종목별 1회 적립액": [f"${a}" for a in amts] if amts else [],
            "이번 기간 총 투입액": _money(buy_amt_usd, fx_f),
        }

    pl = h.get("profitLoss", {})
    dpl = h.get("dailyProfitLoss", {})
    facts = {
        "기준": f"{period_label} (토스증권 Open API 실계좌 데이터, 작성 시점 기준)",
        "투자 방식": dca or "적립식(주식 모으기) 위주 — 매일 소액 자동 매수",
        "계좌 요약": {
            "총 매입금액": _money(h.get("totalPurchaseAmount", {}).get("usd"), fx_f),
            "평가금액": _money(h.get("marketValue", {}).get("amount", {}).get("usd"), fx_f),
            "누적 손익(비용차감후)": {"금액": _money(pl.get("amountAfterCost", {}).get("usd"), fx_f),
                             "수익률": _pct(pl.get("rateAfterCost") or pl.get("rate"))},
            "이번 기간 손익": {"금액": _money(dpl.get("amount", {}).get("usd"), fx_f),
                         "수익률": _pct(dpl.get("rate"))},
        },
        "보유 종목": rows,
        "이번 기간 체결 내역": trades or "매매 없음(관망)",
    }
    if fx_f:
        facts["참고 환율(USD/KRW)"] = f"1달러 = {fx_f:,.1f}원"
    if is_mock():
        facts["⚠데이터 출처"] = "MOCK(스펙 예시) — 키 발급 전 검증용. 실발행 금지"
    return facts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint
    pprint.pprint(build_invest_facts("주간 기록 테스트"))
