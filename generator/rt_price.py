"""국토부 아파트 매매 실거래가 — 청약 '가격 적정성' 확정 팩트 공급 (2026-07-17).

API: RTMSDataSvcAptTradeDev (아파트 매매 실거래 상세, XML) — PUBLIC_DATA_KEY 공용.
LAWD_CD(법정동 시군구 5자리) 해석:
  1) 내장 시군구 코드표(서울 25구·6대 광역시·세종 — 표준 코드)
  2) 미등록(주로 경기도)은 행정표준코드 법정동코드조회 API(StanReginCd)로 조회+캐시
     — 해당 API 활용신청이 없으면 조용히 스킵(실거래 비교 없이 발행).
실패는 전부 무시 — 글 발행을 막지 않는다.
"""
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import PUBLIC_DATA_KEY, DATA_DIR

logger = logging.getLogger("rt_price")
KST = timezone(timedelta(hours=9))
_TIMEOUT = 30

_TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
_REGIN_URL = "https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList"
_CACHE_PATH = os.path.join(DATA_DIR, "lawd_cd_cache.json")

# 표준 법정동 시군구 코드 — 서울 25구·광역시·세종 (경기도는 StanReginCd 조회)
_SEED_LAWD = {
    "서울특별시": {
        "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200",
        "광진구": "11215", "동대문구": "11230", "중랑구": "11260", "성북구": "11290",
        "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
        "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500",
        "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
        "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
        "강동구": "11740",
    },
    "부산광역시": {
        "중구": "26110", "서구": "26140", "동구": "26170", "영도구": "26200",
        "부산진구": "26230", "동래구": "26260", "남구": "26290", "북구": "26320",
        "해운대구": "26350", "사하구": "26380", "금정구": "26410", "강서구": "26440",
        "연제구": "26470", "수영구": "26500", "사상구": "26530", "기장군": "26710",
    },
    "대구광역시": {
        "중구": "27110", "동구": "27140", "서구": "27170", "남구": "27200",
        "북구": "27230", "수성구": "27260", "달서구": "27290", "달성군": "27710",
        "군위군": "27720",
    },
    "인천광역시": {
        "중구": "28110", "동구": "28140", "미추홀구": "28177", "연수구": "28185",
        "남동구": "28200", "부평구": "28237", "계양구": "28245", "서구": "28260",
        "강화군": "28710", "옹진군": "28720",
    },
    "광주광역시": {"동구": "29110", "서구": "29140", "남구": "29155", "북구": "29170", "광산구": "29200"},
    "대전광역시": {"동구": "30110", "중구": "30140", "서구": "30170", "유성구": "30200", "대덕구": "30230"},
    "울산광역시": {"중구": "31110", "남구": "31140", "동구": "31170", "북구": "31200", "울주군": "31710"},
    "세종특별자치시": {"": "36110"},
}

_SIDO_RE = re.compile(
    r"^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|"
    r"세종특별자치시|경기도)\s*"
)


def parse_region(address: str) -> tuple[str, str, str]:
    """주소 → (시도, 시군구 표현, 법정동). '경기도 성남시 분당구 …' → ('경기도','성남시 분당구','…동')."""
    addr = (address or "").strip()
    m = _SIDO_RE.match(addr)
    if not m:
        return "", "", ""
    sido = m.group(1)
    rest = addr[m.end():].strip()
    toks = rest.split()
    sgg_parts = []
    for t in toks[:2]:
        if re.search(r"[시군구]$", t):
            sgg_parts.append(t)
            if t.endswith(("군", "구")):
                break
        else:
            break
    sgg = " ".join(sgg_parts)
    dong = ""
    dm = re.search(r"(\S+?[동읍면리가])(?=\s|$|\d)", rest)
    if dm:
        dong = dm.group(1)
    return sido, sgg, dong


def _load_cache() -> dict:
    try:
        return json.load(open(_CACHE_PATH, encoding="utf-8"))
    except Exception:
        return {}


def _lawd_cd(sido: str, sgg: str) -> str:
    """시군구 5자리 법정동코드. 시드 → 캐시 → StanReginCd 순."""
    if not sido:
        return ""
    seed = _SEED_LAWD.get(sido, {})
    # '수원시 장안구'처럼 2단이면 마지막 토큰(구)이 코드 단위
    if sgg in seed:
        return seed[sgg]
    if not sgg and "" in seed:  # 세종
        return seed[""]
    cache = _load_cache()
    ck = f"{sido} {sgg}"
    if ck in cache:
        return cache[ck]
    if not PUBLIC_DATA_KEY:
        return ""
    try:
        r = requests.get(_REGIN_URL, params={
            "serviceKey": PUBLIC_DATA_KEY, "type": "json",
            "pageNo": 1, "numOfRows": 50, "locatadd_nm": ck, "flag": "Y",
        }, timeout=_TIMEOUT)
        rows = []
        if r.ok and r.text.lstrip().startswith("{"):
            data = r.json()
            for sect in data.get("StanReginCd", []):
                if isinstance(sect, dict) and "row" in sect:
                    rows = sect["row"]
        for row in rows:
            rc = str(row.get("region_cd", ""))
            if len(rc) == 10 and rc.endswith("00000") and row.get("locatadd_nm", "").strip() == ck:
                cache[ck] = rc[:5]
                os.makedirs(DATA_DIR, exist_ok=True)
                json.dump(cache, open(_CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                return rc[:5]
        logger.info(f"법정동코드 미해석: {ck} (StanReginCd 응답 {len(rows)}행)")
    except Exception as e:
        logger.info(f"법정동코드 조회 실패({ck}) — 실거래 비교 생략: {e}")
    return ""


def _fetch_month(lawd5: str, ym: str) -> list[dict]:
    try:
        r = requests.get(_TRADE_URL, params={
            "serviceKey": PUBLIC_DATA_KEY, "LAWD_CD": lawd5, "DEAL_YMD": ym,
            "numOfRows": "1000", "pageNo": "1",
        }, timeout=_TIMEOUT)
        if not r.ok:
            logger.info(f"실거래 API HTTP {r.status_code} ({ym}) — 생략")
            return []
        root = ET.fromstring(r.text)
        code = (root.findtext(".//resultCode") or "").strip()
        if code not in ("00", "000"):
            logger.info(f"실거래 API 오류({ym}): {code} {root.findtext('.//resultMsg')}")
            return []
        out = []
        for it in root.iter("item"):
            d = {c.tag: (c.text or "").strip() for c in it}
            amt = (d.get("dealAmount") or d.get("거래금액") or "").replace(",", "")
            ar = d.get("excluUseAr") or d.get("전용면적") or ""
            try:
                out.append({
                    "apt": d.get("aptNm") or d.get("아파트") or "",
                    "dong": d.get("umdNm") or d.get("법정동") or "",
                    "area": float(ar),
                    "amount": int(amt),  # 만원
                    "build": int(d.get("buildYear") or d.get("건축년도") or 0),
                    "floor": d.get("floor") or d.get("층") or "",
                    "ym": ym,
                })
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        logger.info(f"실거래 조회 실패({ym}): {e}")
        return []


def _fmt_eok(man: int) -> str:
    eok, rem = divmod(man, 10000)
    if eok and rem:
        return f"{eok}억 {rem:,}만"
    return f"{eok}억" if eok else f"{rem:,}만"


def build_trade_facts(address: str, types: list[dict], months: int = 6) -> dict | None:
    """공고 주소 기준 같은 시군구 최근 N개월 실거래 요약 — facts 주입용. 실패 시 None."""
    if not PUBLIC_DATA_KEY:
        return None
    sido, sgg, dong = parse_region(address)
    lawd = _lawd_cd(sido, sgg)
    if not lawd:
        return None
    trades: list[dict] = []
    now = datetime.now(KST)
    for i in range(months):
        y, m = now.year, now.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        trades += _fetch_month(lawd, f"{y}{m:02d}")
    if not trades:
        logger.info(f"실거래 데이터 없음({sido} {sgg}, {months}개월)")
        return None

    # 공고 주택형 전용면적 밴드(±7㎡)별 요약
    areas = []
    for t in types:
        try:
            areas.append(float(str(t.get("HOUSE_TY", "")).split(".")[0] or 0)
                         or float(t.get("SUPLY_AR", 0)))
        except (ValueError, TypeError):
            continue
    areas = sorted({round(a) for a in areas if a})
    new_cut = now.year - 7  # 준신축 기준(7년 이내)

    def _stats(rows: list[dict]) -> dict | None:
        if not rows:
            return None
        amts = [r["amount"] for r in rows]
        recent = sorted(rows, key=lambda r: r["ym"], reverse=True)[:3]
        return {
            "거래건수": len(rows),
            "평균": _fmt_eok(sum(amts) // len(amts)),
            "최고": _fmt_eok(max(amts)),
            "최저": _fmt_eok(min(amts)),
            "최근 사례": [
                f"{r['apt']} {r['area']:.0f}㎡ {r['floor']}층 {_fmt_eok(r['amount'])} ({r['ym'][:4]}.{r['ym'][4:]})"
                for r in recent
            ],
        }

    out = {
        "기준": f"{sido} {sgg} 최근 {months}개월 아파트 매매 실거래 (국토교통부, 만원 단위 원자료)",
        "전체 거래건수": len(trades),
    }
    for a in areas:
        band = [t for t in trades if abs(t["area"] - a) <= 7]
        s = _stats(band)
        if s:
            out[f"전용 {a}㎡대 전체"] = s
        s_new = _stats([t for t in band if t["build"] >= new_cut])
        if s_new:
            out[f"전용 {a}㎡대 준신축({new_cut}년 이후 준공)"] = s_new
    if dong:
        s_dong = _stats([t for t in trades if t["dong"] and t["dong"] in dong])
        if s_dong:
            out[f"같은 동({dong})"] = s_dong
    logger.info(f"실거래 요약 완료: {sido} {sgg} {len(trades)}건, 면적대 {areas}")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import pprint
    pprint.pprint(build_trade_facts("서울특별시 노원구 월계동 487-17번지 일대",
                                    [{"HOUSE_TY": "059.9667A"}, {"HOUSE_TY": "084.9807A"}]))
