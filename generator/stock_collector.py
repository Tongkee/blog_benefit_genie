"""
주식 팩트 데이터 수집기 (주식분석·공모주·ETF).
LLM 할루시네이션 방지: 공신력 있는 API·크롤링으로 당일 수치만 확보.
"""
import logging
import re
from datetime import datetime

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger("stock_collector")

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ETF 관련 수집(국내/미국/국내상장 해외·절세계좌)은 generator/etf_collector.py로 이전됨.


class StockDataCollector:
    @staticmethod
    def _parse_upper_limit_table(table) -> list[dict]:
        rows: list[dict] = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) <= 4:
                continue
            stock_name = cols[3].get_text(strip=True)
            price = cols[4].get_text(strip=True)
            if not stock_name or not price or stock_name in ("종목명", "종목"):
                continue
            change = cols[6].get_text(strip=True) if len(cols) > 6 else (
                cols[2].get_text(strip=True) if len(cols) > 2 else ""
            )
            entry = {"종목명": stock_name, "현재가": price, "등락률": change}
            if len(cols) > 7:
                volume = cols[7].get_text(strip=True)
                if volume:
                    entry["거래량"] = volume
            a = cols[3].find("a")
            code = StockDataCollector._code_from_href(a.get("href")) if a else None
            if code:
                entry["_code"] = code
            rows.append(entry)
        return rows

    @staticmethod
    def _code_from_href(href: str | None) -> str | None:
        if not href:
            return None
        m = re.search(r"code=(\d{6})", href)
        return m.group(1) if m else None

    @staticmethod
    def get_today_upper_limit() -> list[dict]:
        """국내 증시 당일 상한가 종목 (네이버 금융)."""
        return StockDataCollector._fetch_limit_table(
            "https://finance.naver.com/sise/sise_upper.naver", "상한가"
        )

    @staticmethod
    def get_today_lower_limit() -> list[dict]:
        """국내 증시 당일 하한가 종목 (네이버 금융)."""
        return StockDataCollector._fetch_limit_table(
            "https://finance.naver.com/sise/sise_lower.naver", "하한가"
        )

    @staticmethod
    def _fetch_limit_table(url: str, label: str) -> list[dict]:
        rows: list[dict] = []
        logger.info(f"국내 {label} 종목 크롤링 시작")
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            tables = soup.find_all("table", {"class": "type_5"})
            if not tables:
                legacy = soup.find("table", {"class": "type_2"})
                tables = [legacy] if legacy else []
            for table in tables:
                rows.extend(StockDataCollector._parse_upper_limit_table(table))
            if not rows:
                logger.warning(f"{label} 테이블 미발견 또는 데이터 없음")
        except Exception as e:
            logger.error(f"{label} 크롤링 에러: {e}")
        return rows

    @staticmethod
    def get_kr_popular() -> list[dict]:
        """네이버 실시간 인기검색 종목 (검색량 기준, 종목코드 포함)."""
        url = "https://finance.naver.com/sise/lastsearch2.naver"
        results: list[dict] = []
        logger.info("네이버 인기검색 종목 크롤링 시작")
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", {"class": "type_5"})
            if not table:
                logger.warning("인기검색 테이블 미발견")
                return results
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 12:
                    continue
                name = cols[1].get_text(strip=True)
                if not name or name == "종목명":
                    continue
                a = cols[1].find("a")
                code = StockDataCollector._code_from_href(a.get("href")) if a else None
                entry = {
                    "종목명": name,
                    "검색비율(%)": cols[2].get_text(strip=True),
                    "현재가": cols[3].get_text(strip=True),
                    "등락률": cols[5].get_text(strip=True),
                    "거래량": cols[6].get_text(strip=True),
                    "PER": cols[10].get_text(strip=True),
                    "PBR": cols[11].get_text(strip=True),
                }
                if code:
                    entry["_code"] = code
                results.append(entry)
        except Exception as e:
            logger.error(f"인기검색 종목 크롤링 에러: {e}")
        return results[:10]

    @staticmethod
    def get_kr_stock_detail(code: str) -> dict:
        """네이버 종목 상세: PER/EPS/PBR/BPS/배당수익률·투자의견/목표주가·52주고저·동일업종PER·최근뉴스."""
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        detail: dict = {}
        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            t_opinion = soup.find("table", {"summary": "투자의견 정보"})
            if t_opinion:
                ems = t_opinion.find_all("em")
                if len(ems) >= 4:
                    grade = ems[0].next_sibling
                    grade_text = grade.strip() if isinstance(grade, str) else ""
                    score = ems[0].get_text(strip=True)
                    if score:
                        detail["투자의견(컨센서스)"] = f"{score} {grade_text}".strip()
                    if ems[1].get_text(strip=True):
                        detail["목표주가(컨센서스)"] = ems[1].get_text(strip=True)
                    if ems[2].get_text(strip=True):
                        detail["52주최고"] = ems[2].get_text(strip=True)
                    if ems[3].get_text(strip=True):
                        detail["52주최저"] = ems[3].get_text(strip=True)

            t_per = soup.find("table", {"summary": "PER/EPS 정보"})
            if t_per:
                ems = t_per.find_all("em")
                labels = ["PER", "EPS", "추정PER(컨센서스)", "추정EPS(컨센서스)", "PBR", "BPS", "배당수익률(%)"]
                for lbl, em in zip(labels, ems):
                    v = em.get_text(strip=True)
                    if v:
                        detail[lbl] = v

            t_sector = soup.find("table", {"summary": "동일업종 PER 정보"})
            if t_sector:
                ems = t_sector.find_all("em")
                if ems and ems[0].get_text(strip=True):
                    detail["동일업종PER"] = ems[0].get_text(strip=True)
                pct = t_sector.find(string=lambda s: s and "%" in s)
                if pct:
                    detail["동일업종등락률"] = pct.strip()

            news: list[dict] = []
            seen_titles: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "news_read.naver" in href and f"code={code}" in href:
                    title = a.get_text(strip=True)
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        link = href if href.startswith("http") else f"https://finance.naver.com{href}"
                        news.append({"제목": title, "링크": link})
                if len(news) >= 3:
                    break
            if news:
                detail["최근뉴스"] = news
        except Exception as e:
            logger.error(f"{code} 종목 상세 크롤링 에러: {e}")
        return detail

    @staticmethod
    def _ipo_field(td, selector: str) -> str:
        el = td.select_one(selector)
        return el.get_text(strip=True) if el else ""

    @staticmethod
    def _ipo_labeled_field(td, area_class: str) -> str:
        """area_* 블록에서 em.tit 라벨을 제외한 값만 추출."""
        area = td.select_one(f".{area_class}")
        if not area:
            return ""
        num = area.select_one(".num")
        if num:
            return num.get_text(strip=True)
        text = area.get_text(strip=True)
        for tit in area.select("em.tit"):
            text = text.replace(tit.get_text(strip=True), "", 1)
        return text.strip()

    @staticmethod
    def get_ipo_calendar() -> list[dict]:
        """공모주 청약 일정 (네이버 금융 IPO)."""
        url = "https://finance.naver.com/sise/ipo.nhn"
        ipo_list: list[dict] = []
        logger.info("공모주 캘린더 크롤링 시작")

        try:
            response = requests.get(url, headers=_HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for tr in soup.select("table.type_7 > tbody > tr"):
                tds = tr.select("td")
                if not tds:
                    continue
                td = tds[0]
                name = (
                    StockDataCollector._ipo_field(td, ".item_name a")
                    or StockDataCollector._ipo_field(td, ".item_name")
                )
                if not name:
                    continue
                market = StockDataCollector._ipo_field(td, ".item_name .type")
                gongmoga = StockDataCollector._ipo_labeled_field(td, "area_price")
                entry = {
                    "종목명": name,
                    "시장": market,
                    "공모가": gongmoga,
                    "업종": StockDataCollector._ipo_labeled_field(td, "area_type"),
                    "주간사": StockDataCollector._ipo_labeled_field(td, "area_sup"),
                    "경쟁률": StockDataCollector._ipo_labeled_field(td, "area_competition"),
                    "청약일": StockDataCollector._ipo_labeled_field(td, "area_private"),
                    "상장일": StockDataCollector._ipo_labeled_field(td, "area_list"),
                }
                # 확정 공모가(단일 숫자)면 10주 청약 증거금(공모가×50%×10주) 계산해 첨부
                nums = re.findall(r"[\d,]+", gongmoga or "")
                if len(nums) == 1:
                    try:
                        price = int(nums[0].replace(",", ""))
                        if price > 0:
                            entry["10주청약증거금(원)"] = f"{int(price * 0.5 * 10):,}"
                    except ValueError:
                        pass
                ipo_list.append(entry)
        except Exception as e:
            logger.error(f"공모주 크롤링 에러: {e}")

        if not ipo_list:
            logger.warning("공모주 일정 데이터 없음")
        return ipo_list[:15]

    @staticmethod
    def parse_ipo_date_range(s: str):
        """네이버 IPO 날짜 문자열 파싱 → (시작 date, 끝 date) | None.
        형식 실측(2026-07-07): 청약일 '26.07.13~07.14', 상장일 '26.07.13' 또는 '미정'."""
        from datetime import date

        if not s:
            return None
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{2})\s*(?:~\s*(?:(\d{2})\.)?(\d{2})\.(\d{2}))?", s.strip())
        if not m:
            return None
        yy, mm, dd = int(m.group(1)) + 2000, int(m.group(2)), int(m.group(3))
        try:
            start = date(yy, mm, dd)
            if m.group(5):
                yy2 = int(m.group(4)) + 2000 if m.group(4) else yy
                mm2, dd2 = int(m.group(5)), int(m.group(6))
                # '26.12.30~01.02'처럼 연도 경계를 넘는 범위 보정
                if not m.group(4) and (mm2, dd2) < (mm, dd):
                    yy2 += 1
                end = date(yy2, mm2, dd2)
            else:
                end = start
            return (start, end)
        except ValueError:
            return None

    @staticmethod
    def get_ipo_38_detail(name: str) -> dict:
        """38커뮤니케이션에서 공모주 심층 팩트(희망밴드·기관경쟁률·의무보유확약 등) best-effort 보강.
        수요예측 결과(확약 비율)는 네이버 IPO 목록에 없어 '균등/비례/패스' 판단 글의 핵심 팩트다.
        사이트 차단·구조 변경에 대비해 어떤 실패에도 빈 dict 반환(하드 실패 없음)."""
        out: dict = {}
        try:
            r = requests.get(
                "https://www.38.co.kr/html/fund/index.htm?o=k", headers=_HEADERS, timeout=12
            )
            r.encoding = "euc-kr"
            no = None
            clean_name = re.sub(r"\s+", "", name)
            for a in re.finditer(
                r"<a[^>]+href=\"[^\"]*\?o=v&(?:amp;)?no=(\d+)[^\"]*\"[^>]*>([^<]+)</a>", r.text
            ):
                if clean_name in re.sub(r"\s+", "", a.group(2)):
                    no = a.group(1)
                    break
            if not no:
                logger.info(f"38 상세 미발견: {name}")
                return {}
            d = requests.get(
                f"https://www.38.co.kr/html/fund/?o=v&no={no}", headers=_HEADERS, timeout=12
            )
            d.encoding = "euc-kr"
            text = re.sub(r"<[^>]+>", " ", d.text)
            text = re.sub(r"&nbsp;?|&amp;", " ", text)
            text = re.sub(r"\s+", " ", text)

            def grab(label_pat: str, key: str, val_pat: str = r"([0-9][\d,\.]*(?:\s*~\s*[\d,\.]+)?\s*(?:원|주|%|:\s*1)?)"):
                mm = re.search(label_pat + r"\s*[:：]?\s*" + val_pat, text)
                if mm:
                    v = mm.group(1).strip()
                    if v and v not in ("0", "0원", "0%"):
                        out[key] = v

            grab(r"희망공모가액?", "공모희망밴드(원)")
            grab(r"확정공모가", "확정공모가(원)")
            grab(r"기관경쟁률", "기관경쟁률(수요예측)")
            grab(r"의무보유확약", "의무보유확약(%)", r"([\d\.]+\s*%)")
            grab(r"(?:일반)?청약경쟁률", "일반청약경쟁률")
            grab(r"공모금액", "공모금액")
            if out:
                logger.info(f"38 상세 보강({name}): {list(out.keys())}")
        except Exception as e:
            logger.warning(f"38 상세 보강 실패(무시, {name}): {e}")
            return out
        return out

    # 미국 대형·인기 종목 워치리스트 (검색 유입이 잦은 종목 위주) — 이 중 당일 등락폭이 큰 종목을 선정
    _US_WATCHLIST = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX", "AVGO",
        "PLTR", "COIN", "MSTR", "SMCI", "JPM", "V", "UNH", "XOM", "WMT", "BRK-B",
    ]

    @staticmethod
    def get_us_movers() -> list[dict]:
        """워치리스트 내 미국 종목의 당일 등락률·펀더멘털·애널리스트 컨센서스(실데이터)."""
        results: list[dict] = []
        logger.info("미국 종목 워치리스트 등락률 수집 시작")
        for ticker in StockDataCollector._US_WATCHLIST:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="6mo")
                if hist.empty or len(hist) < 2:
                    continue
                closes = hist["Close"]
                current = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                chg = (current - prev) / prev * 100

                info = {}
                try:
                    info = stock.info or {}
                except Exception:
                    pass

                entry = {
                    "종목명": info.get("shortName") or ticker,
                    "티커": ticker,
                    "현재가(USD)": round(current, 2),
                    "등락률(%)": round(chg, 2),
                    "거래량": int(hist["Volume"].iloc[-1]),
                    # 주말·휴장일 발행 시 '오늘/전일 마감' 오표기 방지
                    "마지막거래일": hist.index[-1].strftime("%Y-%m-%d"),
                }
                pe = info.get("trailingPE")
                if isinstance(pe, (int, float)):
                    entry["PER"] = round(pe, 2)
                pb = info.get("priceToBook")
                if isinstance(pb, (int, float)):
                    entry["PBR"] = round(pb, 2)
                mc = info.get("marketCap")
                if isinstance(mc, (int, float)) and mc > 0:
                    entry["시가총액(USD)"] = mc
                hi = info.get("fiftyTwoWeekHigh")
                lo = info.get("fiftyTwoWeekLow")
                if isinstance(hi, (int, float)):
                    entry["52주최고(USD)"] = hi
                if isinstance(lo, (int, float)):
                    entry["52주최저(USD)"] = lo
                sector = info.get("sector")
                if sector:
                    entry["섹터"] = sector
                # 애널리스트 컨센서스(실데이터) — 목표주가·투자의견
                tgt = info.get("targetMeanPrice")
                if isinstance(tgt, (int, float)) and tgt > 0:
                    entry["목표주가평균(USD, 컨센서스)"] = round(tgt, 2)
                tgt_hi = info.get("targetHighPrice")
                tgt_lo = info.get("targetLowPrice")
                if isinstance(tgt_hi, (int, float)):
                    entry["목표주가상단(USD)"] = round(tgt_hi, 2)
                if isinstance(tgt_lo, (int, float)):
                    entry["목표주가하단(USD)"] = round(tgt_lo, 2)
                rec = info.get("recommendationKey")
                if rec and rec != "none":
                    entry["투자의견(컨센서스)"] = rec
                n_analysts = info.get("numberOfAnalystOpinions")
                if isinstance(n_analysts, (int, float)) and n_analysts > 0:
                    entry["애널리스트수"] = int(n_analysts)

                results.append(entry)
            except Exception as e:
                logger.warning(f"{ticker} 수집 실패: {e}")

        results.sort(key=lambda r: abs(r.get("등락률(%)", 0)), reverse=True)
        return results

    @staticmethod
    def get_financial_trend(yf_ticker: str, is_krw: bool = False) -> dict:
        """연간 매출·영업이익 추이 (yfinance income_stmt, 최근 4개 회계연도).
        차트(generate_financials_chart)와 같은 소스 — 본문 수치와 차트 불일치 방지.
        실패 시 빈 dict (하드 실패 없음)."""
        out: dict = {}
        try:
            df = yf.Ticker(yf_ticker).income_stmt
            if df is None or df.empty:
                return out
            unit_div, unit_label = (1e12, "조원") if is_krw else (1e9, "십억달러")
            trend: dict = {}
            for key, name in (("Total Revenue", "매출"), ("Operating Income", "영업이익")):
                if key not in df.index:
                    continue
                s = df.loc[key].dropna().sort_index()
                if len(s):
                    trend[name] = {str(ts.year): round(float(v) / unit_div, 1) for ts, v in s.items()}
            if trend.get("매출"):
                out[f"연간실적({unit_label})"] = trend
        except Exception as e:
            logger.warning(f"{yf_ticker} 재무 추이 수집 실패(무시): {e}")
        return out

    @staticmethod
    def get_search_news(queries: list[str], display: int = 4, max_total: int = 6) -> list[dict]:
        """Naver 뉴스 검색 API로 종목·ETF 최신 이슈 헤드라인 수집(제목 중복 제거).
        NAVER_CLIENT_ID/SECRET 없으면 빈 리스트 — 하드 실패 없음.
        (2026-07-05 지시: 주식분석·ETF 글은 최근 관련 이슈·뉴스를 검색해 반영)"""
        from generator.info_collector import _fetch_naver_news

        out: list[dict] = []
        seen: set[str] = set()
        for q in queries:
            for n in _fetch_naver_news(q, display=display):
                title = n.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                item = {"제목": title}
                if n.get("desc"):
                    item["요약"] = n["desc"][:80]
                if n.get("date"):
                    item["날짜"] = n["date"][:16]
                if n.get("link"):
                    item["링크"] = n["link"]
                out.append(item)
        if out:
            logger.info(f"뉴스 검색 보강: {queries} → {len(out)}건")
        return out[:max_total]

    # 종목분석 대상에서 제외할 ETF·ETN류 (분석 템플릿이 개별기업용 — PER·투자의견 등 부재)
    _ETF_NAME_RE = re.compile(
        r"(KODEX|TIGER|KBSTAR|RISE|ARIRANG|PLUS|HANARO|KOSEF|SOL|ACE|KIWOOM)\s|레버리지|인버스|ETN|선물"
    )

    @staticmethod
    def _parse_pct(val) -> float:
        """등락률 표기('+29.92%', '-15.40%', '↑29.92%', 15.4) → 부호 있는 float. 실패 시 0."""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val)
        m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%?", s.replace(",", ""))
        if not m:
            return 0.0
        pct = float(m.group(1))
        if pct > 0 and ("-" in s or "하락" in s or "↓" in s):
            pct = -pct
        return pct

    @staticmethod
    def get_market_snapshot() -> dict:
        """코스피·코스닥 지수 스냅샷(네이버 폴링 API) — 지수·등락률·전일대비.
        장중엔 실시간, 마감 후·개장 전엔 마지막 거래일 종가 기준."""
        out: dict = {}
        for code, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            try:
                r = requests.get(
                    f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}",
                    headers=_HEADERS, timeout=10,
                )
                r.raise_for_status()
                datas = (r.json() or {}).get("datas") or []
                if not datas:
                    continue
                d = datas[0]
                out[label] = {
                    "지수": d.get("closePrice"),
                    "등락률(%)": StockDataCollector._parse_pct(d.get("fluctuationsRatio")),
                    "전일대비": d.get("compareToPreviousClosePrice"),
                }
            except Exception as e:
                logger.warning(f"{label} 지수 수집 실패(무시): {e}")
        if out:
            logger.info("시장 지수: " + ", ".join(f"{k} {v['등락률(%)']:+.2f}%" for k, v in out.items()))
        return out

    # 시장 이벤트(지수급 폭락·폭등) 판정 기준 — 코스피·코스닥 중 하나라도 ±4% 이상
    MARKET_EVENT_PCT = 4.0

    @staticmethod
    def detect_market_event(snapshot: dict | None = None) -> dict | None:
        """지수급 이벤트 감지(2026-07-13 코스피 -8.95% 미커버 사고 재발 방지).
        감지 시 {"설명", "방향", "지수"} 반환, 평시엔 None."""
        snap = snapshot if snapshot is not None else StockDataCollector.get_market_snapshot()
        movers = {
            k: v.get("등락률(%)", 0.0) for k, v in snap.items()
            if abs(v.get("등락률(%)", 0.0)) >= StockDataCollector.MARKET_EVENT_PCT
        }
        if not movers:
            return None
        worst_pct = max(movers.values(), key=abs)
        direction = "급락" if worst_pct < 0 else "급등"
        desc = " · ".join(f"{k} {v:+.2f}%" for k, v in movers.items()) + f" {direction}"
        logger.info(f"★시장 이벤트 감지: {desc}")
        return {"설명": desc, "방향": direction, "지수": snap}

    # 실적 이슈 신호(제목 기준) — 실적 발표 임박·직후 종목은 프리뷰/해설 검색 수요가 큼
    _EARNINGS_RE = re.compile(r"실적|영업이익|컨센서스|어닝")

    @staticmethod
    def pick_featured_stock(recent_names: set[str] | None = None, history_len: int = 0) -> dict | None:
        """당일 가장 화제인 종목 1개 선정 — 화제성 점수 = 인기검색 순위 가중 + |당일 등락률|.

        2026-07-13 개편(사용자 피드백): 기존 3일 순환(인기검색/미국/상·하한가)은 시장 최대 이슈
        (예: SK하이닉스 -15%·코스피 급락)가 터진 날에도 순번에 걸린 소스만 봐서 무명 상한가
        종목을 골랐다. 검색량(뉴스·이슈의 결과 지표)과 등락폭을 합산해 '사람들이 실제로 찾아보는'
        종목을 뽑는다. history_len은 시그니처 호환용(순환 모드 폐지로 미사용). 미국 워치리스트는
        국내 후보가 전부 비었을 때(휴장·크롤 실패)만 폴백 — 필요 시 STOCK_PIN으로 수동 지정."""
        # 특정 종목 강제 지정(개선판 재발행·수동 운영용, 2026-07-11): STOCK_PIN="종목명" 또는 "종목명:종목코드"
        import os as _os
        pin = _os.environ.get("STOCK_PIN", "").strip()
        if pin:
            pin_name, _, pin_code = pin.partition(":")
            pin_name = pin_name.strip()
            pools: list[dict] = []
            for fn in (StockDataCollector.get_today_upper_limit,
                       StockDataCollector.get_today_lower_limit,
                       StockDataCollector.get_kr_popular):
                try:
                    pools += fn() or []
                except Exception:
                    pass
            picked = next((dict(c) for c in pools if c.get("종목명") == pin_name), None)
            if picked is None:
                picked = {"종목명": pin_name}
            picked.setdefault("선정사유", "최근 급등락으로 화제가 된 종목(수동 지정)")
            if pin_code.strip():
                picked["_code"] = pin_code.strip()
            picked["시장"] = "국내"
            code = picked.get("_code")
            if code:
                try:
                    picked.update(StockDataCollector.get_kr_stock_detail(code))
                except Exception as e:
                    logger.warning(f"{pin_name} 상세 보강 실패(무시): {e}")
            logger.info(f"[STOCK_PIN] {pin_name} 고정 선정 (code={code or '미지정'})")
            return picked

        recent_names = recent_names or set()
        cands = StockDataCollector.pick_featured_candidates(recent_names=recent_names, limit=1)
        if not cands:
            return None
        return StockDataCollector.enrich_stock_detail(cands[0])

    @staticmethod
    def pick_featured_candidates(recent_names: set[str] | None = None, limit: int = 3) -> list[dict]:
        """화제성 상위 후보 limit개 — 재료 예비조사용(2026-07-13).

        선정 전에 후보 여럿을 돌려주고, 호출부(stock_post)가 재료브리프 예비조사로
        '스토리가 확인되는 종목'을 고른다(화제성 1위인데 글감이 없는 종목 회피).
        상세 보강(enrich_stock_detail)은 최종 선정 후 호출부가 수행."""
        recent_names = recent_names or set()
        scored = StockDataCollector._scored_hot_candidates()
        if not scored:
            return []
        pool = [c for c in scored if c["종목명"] not in recent_names] or scored[:1]
        logger.info(
            "화제성 상위: "
            + ", ".join(f"{c['종목명']}({c['_total']:.1f})" for c in scored[:5])
            + f" → 후보 {min(limit, len(pool))}개"
        )
        return [StockDataCollector._finalize_candidate(c) for c in pool[:limit]]

    @staticmethod
    def _finalize_candidate(c: dict) -> dict:
        picked = dict(c)
        why = picked.pop("_why", [])
        pct = StockDataCollector._parse_pct(picked.get("등락률(%)", picked.get("등락률")))
        if abs(pct) >= 5 and not any(("상한가" in w or "하한가" in w) for w in why):
            why.append(f"당일 {pct:+.1f}% 급등락")
        picked["선정사유"] = " · ".join(why) or "당일 화제 종목"
        picked.pop("_src_score", None)
        picked.pop("_total", None)
        return picked

    @staticmethod
    def enrich_stock_detail(picked: dict) -> dict:
        """국내 종목이면 상세 페이지(펀더멘털·투자의견·목표주가·최근뉴스)로 보강.
        _code는 차트 생성(yfinance 티커 조립)용으로 남겨두고, LLM 프롬프트 빌드 시에만 제외."""
        code = picked.get("_code")
        if picked.get("시장") == "국내" and code:
            try:
                detail = StockDataCollector.get_kr_stock_detail(code)
                picked.update(detail)
            except Exception as e:
                logger.warning(f"{picked.get('종목명')} 상세 보강 실패(무시): {e}")
        return picked

    @staticmethod
    def _scored_hot_candidates() -> list[dict]:
        """전 소스(인기검색·상하한가·미국 폴백) 병합 + 화제성 점수 정렬된 후보 리스트."""
        candidates: dict[str, dict] = {}

        def _merge(row: dict, market: str, src_score: float, why: str):
            name = (row.get("종목명") or "").strip()
            if not name or StockDataCollector._ETF_NAME_RE.search(name):
                return
            cur = candidates.setdefault(
                name, {"종목명": name, "시장": market, "_src_score": 0.0, "_why": []}
            )
            for k, v in row.items():
                if k != "종목명" and v not in (None, ""):
                    cur.setdefault(k, v)
            cur["_src_score"] += src_score  # 여러 소스에 겹치면 가산(검색+급등락 = 진짜 이슈)
            cur["_why"].append(why)

        # ① 네이버 실시간 인기검색(검색량) — 순위 가중: 1위 20점 → 10위 2점
        try:
            for idx, row in enumerate(StockDataCollector.get_kr_popular()):
                _merge(row, "국내", (10 - idx) * 2.0, f"네이버 인기검색 {idx + 1}위")
        except Exception as e:
            logger.warning(f"인기검색 후보 수집 실패(무시): {e}")

        # ② 상·하한가 — 등락폭(±30%)이 공통 점수로 반영되므로 소스 자체 점수는 0
        try:
            for row in StockDataCollector.get_today_upper_limit():
                _merge(row, "국내", 0.0, "코스피·코스닥 상한가")
            for row in StockDataCollector.get_today_lower_limit():
                _merge(row, "국내", 0.0, "코스피·코스닥 하한가")
        except Exception as e:
            logger.warning(f"상·하한가 후보 수집 실패(무시): {e}")

        def _total(c: dict) -> float:
            return c["_src_score"] + abs(
                StockDataCollector._parse_pct(c.get("등락률(%)", c.get("등락률")))
            )

        # 국내 후보가 전부 비었을 때만 미국 워치리스트 폴백(휴장·크롤 실패 대비)
        if not candidates:
            logger.warning("국내 후보 없음 — 미국 워치리스트로 폴백")
            try:
                for row in StockDataCollector.get_us_movers():
                    _merge(row, "미국", 0.0, "관심 종목군 내 당일 등락률 상위")
            except Exception as e:
                logger.warning(f"미국 무버 후보 수집 실패(무시): {e}")
        if not candidates:
            return []

        scored = sorted(candidates.values(), key=_total, reverse=True)

        # 실적 시즌 가중치(2026-07-13): 상위 3개 후보만 뉴스 1회씩 조회해 실적 신호(+4점) 반영
        for c in scored[:3]:
            try:
                news = StockDataCollector.get_search_news([c["종목명"]], max_total=4)
                if any(StockDataCollector._EARNINGS_RE.search(str(n.get("제목", ""))) for n in news):
                    c["_src_score"] += 4.0
                    c["_why"].append("실적 이슈 보도")
            except Exception:
                pass
        scored.sort(key=_total, reverse=True)
        for c in scored:
            c["_total"] = _total(c)
        return scored

    @staticmethod
    def get_analyst_reports(stock_name: str, days: int = 10, max_items: int = 4) -> list[dict]:
        """네이버 금융 리서치(종목분석 리포트)에서 해당 종목의 최근 리포트 수집 —
        증권사 실명·리포트 제목·목표가·투자의견(상세 페이지 .view_info).
        2026-07-13: 급변일 '실명 목표가 조정 우선 인용' 규칙의 실데이터 소스."""
        from datetime import timedelta as _td

        out: list[dict] = []
        try:
            cutoff = datetime.now() - _td(days=days)
            detail_fetched = 0
            for page in (1, 2):
                r = requests.get(
                    "https://finance.naver.com/research/company_list.naver",
                    params={"page": page}, headers=_HEADERS, timeout=15,
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                table = soup.select_one("table.type_1")
                if not table:
                    break
                for tr in table.select("tr"):
                    tds = tr.select("td")
                    if len(tds) < 6:
                        continue
                    if tds[0].get_text(strip=True) != stock_name:
                        continue
                    date_s = tds[4].get_text(strip=True)  # '26.07.13'
                    try:
                        if datetime.strptime(date_s, "%y.%m.%d") < cutoff:
                            continue
                    except ValueError:
                        pass
                    item = {
                        "증권사": tds[2].get_text(strip=True),
                        "리포트제목": tds[1].get_text(" ", strip=True),
                        "날짜": date_s,
                    }
                    a = tds[1].select_one("a[href*='company_read']")
                    if a and detail_fetched < 3:  # 목표가·의견 상세는 최대 3건만 추가 요청
                        detail_fetched += 1
                        try:
                            r2 = requests.get(
                                "https://finance.naver.com/research/" + a["href"],
                                headers=_HEADERS, timeout=15,
                            )
                            info = BeautifulSoup(r2.text, "html.parser").select_one(".view_info")
                            if info:
                                text = info.get_text(" ", strip=True)  # '목표가 60,000 | 투자의견 Buy'
                                m = re.search(r"목표가\s*([\d,]+)", text)
                                if m:
                                    item["목표가"] = m.group(1) + "원"
                                m = re.search(r"투자의견\s*([A-Za-z가-힣.]+)", text)
                                if m:
                                    item["투자의견"] = m.group(1)
                        except Exception:
                            pass
                    out.append(item)
                    if len(out) >= max_items:
                        return out
        except Exception as e:
            logger.warning(f"리서치 리포트 수집 실패(무시, {stock_name}): {e}")
        return out

    @staticmethod
    def get_dart_disclosures(stock_code: str, days: int = 14, max_items: int = 8) -> list[dict]:
        """DART(Open DART) 최근 공시 목록 — DART_API_KEY 없으면 빈 리스트(우아한 스킵).
        corp_code 매핑은 corpCode.xml(zip, ~2MB)을 내려받아 조회(회당 1요청)."""
        import io
        import os as _os
        import zipfile
        import xml.etree.ElementTree as ET
        from datetime import timedelta as _td

        key = _os.environ.get("DART_API_KEY", "").strip()
        if not key or not stock_code:
            return []
        try:
            r = requests.get(
                "https://opendart.fss.or.kr/api/corpCode.xml",
                params={"crtfc_key": key}, timeout=30,
            )
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                xml_data = zf.read(zf.namelist()[0])
            corp_code = None
            for el in ET.fromstring(xml_data).iter("list"):
                if (el.findtext("stock_code") or "").strip() == stock_code:
                    corp_code = (el.findtext("corp_code") or "").strip()
                    break
            if not corp_code:
                logger.info(f"DART corp_code 미발견: {stock_code}")
                return []
            end = datetime.now()
            r2 = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={
                    "crtfc_key": key, "corp_code": corp_code,
                    "bgn_de": (end - _td(days=days)).strftime("%Y%m%d"),
                    "end_de": end.strftime("%Y%m%d"),
                    "page_count": max_items,
                },
                timeout=15,
            )
            data = r2.json()
            if data.get("status") != "000":  # '013' = 조회 데이터 없음(정상)
                if data.get("status") != "013":
                    logger.warning(f"DART 응답 오류({data.get('status')}): {str(data.get('message'))[:60]}")
                return []
            out = [
                {"보고서": i.get("report_nm"), "접수일": i.get("rcept_dt"), "제출인": i.get("flr_nm")}
                for i in (data.get("list") or [])[:max_items]
            ]
            logger.info(f"DART 공시 {len(out)}건 수집: {stock_code}")
            return out
        except Exception as e:
            logger.warning(f"DART 공시 수집 실패(무시): {e}")
            return []

    @staticmethod
    def collect(topic_id: str) -> dict | list | None:
        """topic_id별 팩트 데이터 수집."""
        collectors = {
            "공모주캘린더": StockDataCollector.get_ipo_calendar,
        }
        fn = collectors.get(topic_id)
        if not fn:
            return None
        data = fn()
        if isinstance(data, dict) and not data:
            return None
        if isinstance(data, list) and not data:
            return None
        return data
