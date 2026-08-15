"""
주식/ETF 가격 차트 이미지 생성 (matplotlib, 실제 시세 데이터만 사용).
"""
import logging
import os
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import requests
import yfinance as yf

logger = logging.getLogger("stock_chart")

_FONT_CANDIDATES = ["NanumGothic", "Malgun Gothic", "AppleGothic"]


def _set_korean_font():
    available = {f.name for f in fm.fontManager.ttflist}
    for name in _FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.family"] = name
            return


_set_korean_font()
plt.rcParams["axes.unicode_minus"] = False


def _save(fig) -> str:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="chart_")
    os.close(fd)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_comparison_chart(
    tickers: list[str], labels: dict[str, str] | None = None,
    period: str = "3mo", title: str = "",
) -> str | None:
    """여러 티커의 정규화(시작일=100) 가격 흐름을 한 차트에 비교."""
    labels = labels or {}
    try:
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        plotted = 0
        for ticker in tickers:
            try:
                hist = yf.Ticker(ticker).history(period=period)
                if hist.empty or len(hist) < 5:
                    continue
                closes = hist["Close"]
                normalized = closes / closes.iloc[0] * 100
                ax.plot(normalized.index, normalized.values, label=labels.get(ticker, ticker), linewidth=1.8)
                plotted += 1
            except Exception as e:
                logger.warning(f"{ticker} 차트 데이터 실패: {e}")
        if plotted == 0:
            plt.close(fig)
            return None
        ax.set_title(title or "최근 가격 흐름 비교 (시작일=100 기준)", fontsize=13)
        ax.set_ylabel("상대 수익률 (시작일=100)")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"비교 차트 생성 실패: {e}")
        return None


def generate_dividend_history_chart(ticker: str, label: str = "", years: int = 10) -> str | None:
    """연도별 주당 배당금 막대차트 (완결 연도만 — 진행 중인 올해는 부분 합계라 제외).
    배당 ETF의 '배당이 꾸준히 늘었나'를 한눈에 보여주는 용도."""
    try:
        from datetime import datetime as _dt

        div = yf.Ticker(ticker).dividends
        if div is None or len(div) < 8:
            return None
        yearly = div.groupby(div.index.year).sum()
        yearly = yearly[yearly.index < _dt.now().year].tail(years)
        if len(yearly) < 3:
            return None

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        bars = ax.bar([str(y) for y in yearly.index], yearly.values, color="#2e7d32", alpha=0.85)
        for b, v in zip(bars, yearly.values):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
        total_growth = (yearly.iloc[-1] / yearly.iloc[0] - 1) * 100
        ax.set_title(
            f"{label or ticker} 연도별 주당 배당금 (USD) — {yearly.index[0]}년 대비 {total_growth:+.0f}%",
            fontsize=12,
        )
        ax.set_ylabel("주당 배당금 (USD)")
        ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"{ticker} 배당 이력 차트 생성 실패: {e}")
        return None


def generate_total_return_chart(ticker: str, label: str = "", years: int = 10) -> str | None:
    """배당 재투자 포함(총수익, 수정주가) vs 주가만 — 시작=100 두 곡선 비교.
    배당 ETF 성과를 주가 그래프만으로 보면 총수익이 누락된다는 걸 시각화."""
    try:
        t = yf.Ticker(ticker)
        tr = t.history(period="max", auto_adjust=True)["Close"]
        pr = t.history(period="max", auto_adjust=False)["Close"]
        common = tr.index.intersection(pr.index)
        tr, pr = tr.loc[common], pr.loc[common]
        n = min(years * 252, len(tr) - 1)
        if n < 300:
            return None
        tr, pr = tr.iloc[-n:], pr.iloc[-n:]
        trn = tr / tr.iloc[0] * 100
        prn = pr / pr.iloc[0] * 100
        actual_years = round(n / 252)

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        ax.plot(trn.index, trn.values, label=f"배당 재투자 포함 ({trn.iloc[-1] - 100:+.0f}%)",
                linewidth=1.8, color="#2e7d32")
        ax.plot(prn.index, prn.values, label=f"주가만 ({prn.iloc[-1] - 100:+.0f}%)",
                linewidth=1.5, color="#1f77b4", linestyle="--")
        ax.set_title(f"{label or ticker} 총수익 vs 주가 (최근 {actual_years}년, 시작=100)", fontsize=12)
        ax.set_ylabel("누적 수익 (시작=100)")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"{ticker} 총수익 비교 차트 생성 실패: {e}")
        return None


def generate_financials_chart(ticker: str, label: str = "", is_krw: bool = False) -> str | None:
    """연간 매출·영업이익 추이 그룹 막대차트 (yfinance income_stmt, 최근 4개 회계연도).
    단위: 미국 십억달러(B USD), 국내 조원."""
    try:
        df = yf.Ticker(ticker).income_stmt
        if df is None or df.empty:
            return None
        series = {}
        for key, name in (("Total Revenue", "매출"), ("Operating Income", "영업이익")):
            if key in df.index:
                s = df.loc[key].dropna()
                if len(s):
                    series[name] = s.sort_index()
        if "매출" not in series:
            return None

        unit_div, unit_label = (1e12, "조원") if is_krw else (1e9, "십억 달러")
        years = [str(ts.year) for ts in series["매출"].index]
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        width = 0.38
        x = range(len(years))
        rev = [v / unit_div for v in series["매출"].values]
        ax.bar([i - width / 2 for i in x], rev, width, label="매출", color="#1f77b4", alpha=0.85)
        if "영업이익" in series and len(series["영업이익"]) == len(years):
            op = [v / unit_div for v in series["영업이익"].values]
            ax.bar([i + width / 2 for i in x], op, width, label="영업이익", color="#2e7d32", alpha=0.85)
        ax.set_xticks(list(x))
        ax.set_xticklabels(years)
        ax.set_title(f"{label or ticker} 연간 실적 추이 ({unit_label})", fontsize=12)
        ax.set_ylabel(unit_label)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"{ticker} 재무 추이 차트 생성 실패: {e}")
        return None


def generate_price_chart(ticker: str, label: str = "", period: str = "6mo") -> str | None:
    """단일 종목/ETF 가격 추이 + 20일 이동평균선."""
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty or len(hist) < 10:
            return None
        closes = hist["Close"]
        sma20 = closes.rolling(20).mean()

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        ax.plot(closes.index, closes.values, label=label or ticker, linewidth=1.8, color="#1f77b4")
        ax.plot(sma20.index, sma20.values, label="20일 이동평균", linewidth=1.2, color="#ff7f0e", linestyle="--")
        ax.set_title(f"{label or ticker} 최근 가격 추이", fontsize=13)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        return _save(fig)
    except Exception as e:
        logger.error(f"{ticker} 가격 차트 생성 실패: {e}")
        return None


def get_naver_official_chart(code: str) -> str | None:
    """네이버금융이 제공하는 국내 종목 실시간 차트(정적 PNG)를 그대로 다운로드.
    (finance.naver.com 종목 상세페이지가 렌더하는 원본 이미지 — 신뢰도용 실측 캡처 대체)"""
    url = f"https://ssl.pstatic.net/imgfinance/chart/item/area/day/{code}.png"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200 or len(resp.content) < 2000:
            return None
        fd, path = tempfile.mkstemp(suffix=".png", prefix="naver_chart_")
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        logger.error(f"{code} 네이버금융 공식 차트 다운로드 실패: {e}")
        return None
