# -*- coding: utf-8 -*-
"""청약 공고 데이터 인포카드 3종 — 벤치마크 카드형 블로그 스타일 (2026-07-19 사용자 벤치마킹).

경쟁 상위 글들의 공통 무기 '섹션마다 데이터 인포카드'를 자동화한다.
LLM을 거치지 않고 cheongyak_collector.build_facts()의 확정 팩트만 렌더하므로
수치 오류가 구조적으로 불가능하다(고시값 정적 DB와 같은 원칙).

카드: ①핵심 요약(2×2 타일) ②청약 일정 타임라인 ③타입별 분양가 비교.
렌더는 infographic_html._pw_screenshot_element(.cardwrap 캡처) 재사용.
"""
import asyncio
import logging
import re
import tempfile
from html import escape

from poster.infographic_html import _pw_screenshot_element

logger = logging.getLogger("cheongyak_cards")

# 벤치마크 카드 팔레트 — 크림 배경 + 네이비 + 옐로 하이라이트 + 레드 포인트
_C = {
    "bg": "#FBF4E4", "tile": "#FFFDF7", "line": "#E8D9B8",
    "navy": "#273A5A", "yellow": "#FFD84D", "red": "#E05A47",
    "text": "#3A3A34", "muted": "#8A8577",
}
_TYPE_COLORS = ["#4A7BD0", "#4CAF87", "#E0899B", "#C08BD0", "#D9A441", "#6BB2C9"]

_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}}
body{{width:1080px;background:#fff;}}
.cardwrap{{width:1080px;padding:26px;background:{_C['bg']};border:3px solid {_C['line']};
  border-radius:26px;}}
.topbar{{background:{_C['navy']};border-radius:16px;padding:22px 30px;margin-bottom:22px;
  display:flex;align-items:center;justify-content:space-between;}}
.topbar .t{{color:#fff;font-size:38px;font-weight:900;letter-spacing:-1px;line-height:1.25;}}
.topbar .badge{{flex:none;margin-left:18px;background:{_C['yellow']};color:{_C['navy']};
  font-size:24px;font-weight:900;padding:8px 20px;border-radius:999px;}}
.foot{{margin-top:18px;display:flex;justify-content:space-between;align-items:center;}}
.foot .brand{{font-size:22px;font-weight:800;color:{_C['navy']};}}
.foot .src{{font-size:19px;color:{_C['muted']};}}
"""


def _shot(html: str) -> str | None:
    try:
        png = asyncio.run(_pw_screenshot_element(html))
    except Exception as e:
        logger.warning(f"청약 카드 스크린샷 실패: {e}")
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(png)
    tmp.close()
    return tmp.name


def _wrap(inner: str, title: str, badge: str) -> str:
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body><div class="cardwrap">
  <div class="topbar"><div class="t">{escape(title)}</div>
  {f'<div class="badge">{escape(badge)}</div>' if badge else ''}</div>
  {inner}
  <div class="foot"><div class="brand">현지언니의 발품 정보</div>
  <div class="src">출처 · 입주자모집공고문(청약홈)</div></div>
</div></body></html>"""


def _parse_manwon(s: str) -> int:
    """'6억 5,500만 원' → 65500(만원). 실패 시 0."""
    if not s:
        return 0
    m = re.search(r"(?:(\d+)억)?\s*(?:([\d,]+)만)?", str(s).replace(" ", ""))
    if not m or (not m.group(1) and not m.group(2)):
        return 0
    eok = int(m.group(1) or 0)
    man = int((m.group(2) or "0").replace(",", ""))
    return eok * 10000 + man


def _fmt_eok(manwon: int) -> str:
    if manwon <= 0:
        return "-"
    eok, man = divmod(manwon, 10000)
    if eok and man:
        return f"{eok}억 {man:,}만"
    return f"{eok}억" if eok else f"{man:,}만"


def _first_date(s: str) -> str:
    """'2026-07-27 (해당지역) / …' → '7월 27일'."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if not m:
        return str(s).strip() or "-"
    return f"{int(m.group(2))}월 {int(m.group(3))}일"


def _date_range(s: str) -> str:
    ds = re.findall(r"\d{4}-(\d{2})-(\d{2})", str(s))
    if not ds:
        return str(s).strip(" ~") or "-"
    if len(ds) >= 2 and ds[0] != ds[1]:
        return f"{int(ds[0][0])}월 {int(ds[0][1])}일 ~ {int(ds[1][0])}월 {int(ds[1][1])}일"
    return f"{int(ds[0][0])}월 {int(ds[0][1])}일"


def _yyyymm(s: str) -> str:
    m = re.search(r"(\d{4})\D?(\d{2})", str(s))
    return f"{m.group(1)}년 {int(m.group(2))}월" if m else (str(s).strip() or "-")


# ── 카드 1: 핵심 요약 (2×2 타일) ─────────────────────────────────────────────

def create_overview_card(facts: dict) -> str | None:
    name = facts.get("단지명", "")
    kind = facts.get("공고유형", "")
    types = facts.get("주택형별 공급", [])
    total = 0
    prices = []
    for t in types:
        try:
            total += int(str(t.get("일반공급") or 0)) + int(str(t.get("특별공급") or 0))
        except ValueError:
            pass
        p = _parse_manwon(t.get("최고분양가", ""))
        if p:
            prices.append(p)
    sched = facts.get("일정", {})
    rcpt = sched.get("1순위 접수") or sched.get("접수", "")
    move_in = sched.get("입주 예정", "")
    price_txt = (f"{_fmt_eok(min(prices))}~{_fmt_eok(max(prices))}" if len(prices) > 1
                 else (_fmt_eok(prices[0]) if prices else "공고문 확인"))
    tiles = [
        ("공급 세대", f"{total or facts.get('총공급세대수', '-')}세대",
         kind.replace("APT ", "") or ""),
        ("분양가", price_txt, "타입별 최고가 기준"),
        ("청약 접수", _first_date(rcpt), "순위별 접수는 짧아요"),
        ("입주 예정", _yyyymm(move_in), facts.get("시공사", "")[:14]),
    ]
    tile_html = ""
    for lbl, big, sub in tiles:
        tile_html += (
            f'<div class="tile"><div class="lbl">{escape(lbl)}</div>'
            f'<div class="big">{escape(str(big))}</div>'
            f'<div class="sub">{escape(str(sub))}</div></div>'
        )
    inner = f"""<style>
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
.tile{{background:{_C['tile']};border:2px solid {_C['line']};border-radius:16px;
  padding:24px 26px;text-align:center;}}
.tile .lbl{{display:inline-block;background:{_C['yellow']};color:{_C['navy']};font-size:22px;
  font-weight:900;padding:4px 16px;border-radius:999px;margin-bottom:12px;}}
.tile .big{{font-size:44px;font-weight:900;color:{_C['navy']};letter-spacing:-1px;
  line-height:1.15;margin-bottom:8px;}}
.tile .sub{{font-size:21px;color:{_C['muted']};font-weight:500;min-height:26px;}}
</style><div class="grid">{tile_html}</div>"""
    # 긴 단지명은 괄호 부연 제거 — 제목 두 줄 어색한 줄바꿈 방지
    short = re.sub(r"\([^)]*\)", "", name).strip()
    title = f"{short} 청약 핵심" if len(short) <= 16 else f"{short[:16]}… 청약 핵심"
    path = _shot(_wrap(inner, title, "한눈에"))
    if path:
        logger.info(f"청약 요약 카드 생성 → {path}")
    return path


# ── 카드 2: 청약 일정 타임라인 ───────────────────────────────────────────────

def create_schedule_card(facts: dict) -> str | None:
    sched = facts.get("일정", {})
    order = ["모집공고일", "특별공급 접수", "1순위 접수", "2순위 접수", "접수",
             "당첨자 발표", "계약", "입주 예정"]
    hot = {"1순위 접수", "접수", "당첨자 발표"}
    rows = ""
    n = 0
    for k in order:
        v = str(sched.get(k, "")).strip()
        # 'None ~ None'(특공 없는 공고 등 빈 값) 행 노출 방지 — 실제 날짜가 없으면 스킵
        if not v or not re.search(r"\d{4}-\d{2}-\d{2}|\d{6}", v):
            continue
        val = _yyyymm(v) if k == "입주 예정" else _date_range(v)
        if val in ("-", ""):
            continue
        n += 1
        cls = "row hot" if k in hot else "row"
        rows += (f'<div class="{cls}"><div class="dot"></div>'
                 f'<div class="k">{escape(k)}</div><div class="v">{escape(val)}</div></div>')
    if n < 3:
        return None
    inner = f"""<style>
.row{{display:flex;align-items:center;gap:20px;background:{_C['tile']};
  border:2px solid {_C['line']};border-radius:14px;padding:18px 26px;margin-bottom:12px;}}
.row.hot{{background:#FFF3C4;border-color:{_C['yellow']};}}
.dot{{flex:none;width:18px;height:18px;border-radius:50%;background:{_C['red']};}}
.row:not(.hot) .dot{{background:{_C['navy']};opacity:.45;}}
.k{{flex:none;width:250px;font-size:28px;font-weight:800;color:{_C['navy']};}}
.v{{font-size:30px;font-weight:900;color:{_C['text']};letter-spacing:-0.5px;}}
.row.hot .v{{color:{_C['red']};}}
</style>{rows}"""
    path = _shot(_wrap(inner, "청약 일정, 이 날짜만 기억하세요", "일정"))
    if path:
        logger.info(f"청약 일정 카드 생성 → {path} ({n}행)")
    return path


# ── 카드 3: 타입별 분양가 비교 ───────────────────────────────────────────────

def create_price_card(facts: dict) -> str | None:
    types = facts.get("주택형별 공급", [])
    if not types:
        return None
    rows = ""
    prices = []
    for i, t in enumerate(types[:6]):
        ty = str(t.get("주택형", "")).strip()
        # '084.9956B' → '84B' 뱃지 표기
        m = re.match(r"0*(\d+)(?:\.\d+)?([A-Za-z]?)", ty)
        badge = f"{m.group(1)}{m.group(2).upper()}" if m else ty[:4]
        area = str(t.get("공급면적", "")).strip()
        try:
            gen = int(str(t.get("일반공급") or 0))
            spc = int(str(t.get("특별공급") or 0))
            cnt = f"{gen + spc}세대"
        except ValueError:
            cnt = "-"
        p = _parse_manwon(t.get("최고분양가", ""))
        if p:
            prices.append(p)
        price = f"{_fmt_eok(p)} 원" if p else "공고문 확인"
        color = _TYPE_COLORS[i % len(_TYPE_COLORS)]
        rows += (
            f'<div class="row"><div class="badge" style="background:{color}">{escape(badge)}</div>'
            f'<div class="meta"><div class="area">{escape(area)}</div>'
            f'<div class="cnt">{escape(cnt)}</div></div>'
            f'<div class="price">{escape(price)}</div></div>'
        )
    strip = ""
    if prices:
        dep = round(min(prices) * 0.1)
        strip = (f'<div class="strip">계약금 10% 가정 시 최소 '
                 f'<b>{escape(_fmt_eok(dep))} 원</b> 현금 필요 '
                 f'<span>(실제 비율은 공고문 확인)</span></div>')
    inner = f"""<style>
.row{{display:flex;align-items:center;gap:24px;background:{_C['tile']};
  border:2px solid {_C['line']};border-radius:14px;padding:16px 26px;margin-bottom:12px;}}
.badge{{flex:none;min-width:110px;text-align:center;color:#fff;font-size:34px;font-weight:900;
  padding:10px 16px;border-radius:12px;letter-spacing:-0.5px;}}
.meta{{flex:1;}}
.area{{font-size:25px;font-weight:700;color:{_C['text']};}}
.cnt{{font-size:21px;color:{_C['muted']};}}
.price{{font-size:36px;font-weight:900;color:{_C['navy']};letter-spacing:-1px;}}
.strip{{margin-top:6px;background:#FFF3C4;border:2px solid {_C['yellow']};border-radius:12px;
  padding:16px 24px;font-size:25px;font-weight:700;color:{_C['navy']};}}
.strip b{{color:{_C['red']};font-size:29px;}}
.strip span{{font-size:20px;color:{_C['muted']};font-weight:500;}}
</style>{rows}{strip}"""
    path = _shot(_wrap(inner, "타입별 최고 분양가", "분양가"))
    if path:
        logger.info(f"청약 분양가 카드 생성 → {path} ({len(types[:6])}타입)")
    return path


# ── 카드 3-1: 타입별 구성 요약 (2026-07-29 사용자 지시 — 평면도와 한 세트) ────

def create_type_card(facts: dict) -> str | None:
    """타입별 주택형·공급면적·세대 구성 타일 그리드. 분양가 카드(가격 중심 행)와 달리
    '어떤 타입이 몇 세대나 나오나'를 한눈에 — 평면도 이미지 옆에 붙는 요약."""
    types = facts.get("주택형별 공급", [])
    if not types:
        return None
    tiles = ""
    shown = types[:6]
    for i, t in enumerate(shown):
        ty = str(t.get("주택형", "")).strip()
        m = re.match(r"0*(\d+)(?:\.(\d+))?([A-Za-z]?)", ty)
        badge = f"{m.group(1)}{m.group(3).upper()}" if m else ty[:4]
        exclusive = f"전용 {m.group(1)}.{m.group(2)}㎡" if (m and m.group(2)) else (f"전용 {ty}" if ty else "")
        area = str(t.get("공급면적", "")).strip()
        try:
            gen = int(str(t.get("일반공급") or 0))
        except ValueError:
            gen = 0
        try:
            spc = int(str(t.get("특별공급") or 0))
        except ValueError:
            spc = 0
        cnt = f"일반 {gen}" + (f" · 특공 {spc}" if spc else "") + "세대"
        color = _TYPE_COLORS[i % len(_TYPE_COLORS)]
        tiles += (
            f'<div class="tile"><div class="badge" style="background:{color}">{escape(badge)}</div>'
            f'<div class="ex">{escape(exclusive)}</div>'
            f'<div class="ar">공급 {escape(area)}</div>'
            f'<div class="cnt">{escape(cnt)}</div></div>'
        )
    more = (f'<div class="strip">이 외 {len(types) - 6}개 타입은 모집공고문에서 확인하세요.</div>'
            if len(types) > 6 else "")
    inner = f"""<style>
.grid{{display:grid;grid-template-columns:repeat({2 if len(shown) <= 4 else 3},1fr);gap:14px;}}
.tile{{background:{_C['tile']};border:2px solid {_C['line']};border-radius:16px;
  padding:20px 18px;text-align:center;}}
.badge{{display:inline-block;color:#fff;font-size:34px;font-weight:900;padding:8px 22px;
  border-radius:12px;letter-spacing:-0.5px;margin-bottom:12px;}}
.ex{{font-size:24px;font-weight:800;color:{_C['navy']};margin-bottom:4px;}}
.ar{{font-size:21px;color:{_C['text']};margin-bottom:8px;}}
.cnt{{display:inline-block;background:#FFF3C4;border-radius:999px;padding:4px 14px;
  font-size:20px;font-weight:700;color:{_C['navy']};}}
.strip{{margin-top:14px;background:{_C['tile']};border:2px dashed {_C['line']};border-radius:12px;
  padding:13px 20px;font-size:20px;color:{_C['muted']};}}
</style><div class="grid">{tiles}</div>{more}"""
    path = _shot(_wrap(inner, "타입별 구성, 한눈에 보기", "타입 요약"))
    if path:
        logger.info(f"청약 타입 요약 카드 생성 → {path} ({len(shown)}타입)")
    return path


# ── 카드 4: 규제·자격 체크 ───────────────────────────────────────────────────

def create_eligibility_card(facts: dict) -> str | None:
    reg = facts.get("규제", {})
    rows = ""
    n = 0
    label_map = [
        ("투기과열지구", "투기과열지구"),
        ("조정대상지역", "조정대상지역"),
        ("분양가상한제", "분양가상한제"),
        ("정비사업", "정비사업 규제"),
        ("공공주택지구", "공공주택지구"),
        ("생애최초 공급", "생애최초 공급"),
    ]
    for key, label in label_map:
        v = str(reg.get(key, "")).strip().upper()
        if v not in ("Y", "N"):
            continue
        n += 1
        ok = v == "N" if key != "생애최초 공급" else v == "Y"
        icon = "✓" if ok else "!"
        cls = "ok" if ok else "warn"
        desc = ("해당 없음" if v == "N" else "적용") if key != "생애최초 공급" \
            else ("있음" if v == "Y" else "없음")
        rows += (f'<div class="row"><div class="ic {cls}">{icon}</div>'
                 f'<div class="k">{escape(label)}</div><div class="v">{escape(desc)}</div></div>')
    if n < 3:
        return None
    region = str(facts.get("공급지역", "")).strip()
    strip = (f'<div class="strip">규제와 별개로 <b>청약통장 요건·{escape(region) or "해당"}지역 '
             f'거주 우선</b>은 공고문 기준이에요 — 접수 전 꼭 확인!</div>')
    inner = f"""<style>
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.row{{display:flex;align-items:center;gap:16px;background:{_C['tile']};
  border:2px solid {_C['line']};border-radius:14px;padding:18px 22px;}}
.ic{{flex:none;width:44px;height:44px;border-radius:50%;color:#fff;font-size:26px;
  font-weight:900;display:flex;align-items:center;justify-content:center;}}
.ic.ok{{background:#4CAF87;}}
.ic.warn{{background:{_C['red']};}}
.k{{flex:1;font-size:25px;font-weight:800;color:{_C['navy']};}}
.v{{font-size:24px;font-weight:900;color:{_C['text']};}}
.strip{{margin-top:14px;background:#FFF3C4;border:2px solid {_C['yellow']};border-radius:12px;
  padding:16px 22px;font-size:23px;font-weight:600;color:{_C['navy']};line-height:1.45;}}
.strip b{{color:{_C['red']};}}
</style><div class="grid2">{rows}</div>{strip}"""
    path = _shot(_wrap(inner, "규제 적용 여부, 여기만 보면 됩니다", "자격 체크"))
    if path:
        logger.info(f"청약 자격 카드 생성 → {path} ({n}항목)")
    return path


# ── 카드 5: 필요 현금 시뮬레이션 ─────────────────────────────────────────────

def create_payment_card(facts: dict) -> str | None:
    cash = facts.get("필요현금 참고(최고분양가 기준)", {})
    top = cash.get("최고분양가", "")
    d10 = cash.get("계약금 10% 가정", "")
    d20 = cash.get("계약금 20% 가정", "")
    if not (top and d10):
        return None
    rows = ""
    for label, val, hot in (("최고 분양가", top, False),
                            ("계약금 10% 가정", d10, True),
                            ("계약금 20% 가정", d20, False)):
        if not val:
            continue
        cls = "row hot" if hot else "row"
        rows += (f'<div class="{cls}"><div class="k">{escape(label)}</div>'
                 f'<div class="v">{escape(str(val))}</div></div>')
    inner = f"""<style>
.row{{display:flex;align-items:center;justify-content:space-between;background:{_C['tile']};
  border:2px solid {_C['line']};border-radius:14px;padding:20px 28px;margin-bottom:12px;}}
.row.hot{{background:#FFF3C4;border-color:{_C['yellow']};}}
.k{{font-size:27px;font-weight:800;color:{_C['navy']};}}
.v{{font-size:34px;font-weight:900;color:{_C['text']};letter-spacing:-1px;}}
.row.hot .v{{color:{_C['red']};}}
.strip{{margin-top:6px;background:{_C['tile']};border:2px dashed {_C['line']};border-radius:12px;
  padding:15px 22px;font-size:21px;color:{_C['muted']};line-height:1.45;}}
</style>{rows}<div class="strip">실제 계약금 비율·중도금 대출 조건은 입주자모집공고문이
기준이에요. 여기 금액은 최고 분양가 기준 가정치입니다.</div>"""
    path = _shot(_wrap(inner, "현금, 얼마나 준비해야 할까", "자금 계획"))
    if path:
        logger.info(f"청약 자금 카드 생성 → {path}")
    return path


# ── 카드 6: 청약 전 체크리스트 ───────────────────────────────────────────────

def create_checklist_card(facts: dict) -> str | None:
    sched = facts.get("일정", {})
    rcpt = _first_date(sched.get("1순위 접수") or sched.get("접수", ""))
    cash = facts.get("필요현금 참고(최고분양가 기준)", {})
    d10 = cash.get("계약금 10% 가정", "")
    items = [
        "입주자모집공고문 원문 정독 (청약홈)",
        "청약통장 가입기간·예치금 충족 확인",
        f"계약금 현금 준비 ({d10} 안팎, 10% 가정)" if d10 else "계약금 현금 준비 계획",
        "중도금 대출 조건·이자 부담 확인",
        f"접수일 캘린더 등록 — {rcpt}" if rcpt != "-" else "접수일 캘린더 등록",
    ]
    rows = ""
    for it in items:
        rows += (f'<div class="row"><div class="box">✓</div>'
                 f'<div class="t">{escape(it)}</div></div>')
    inner = f"""<style>
.row{{display:flex;align-items:center;gap:20px;background:{_C['tile']};
  border:2px solid {_C['line']};border-radius:14px;padding:18px 26px;margin-bottom:12px;}}
.box{{flex:none;width:44px;height:44px;border-radius:10px;background:{_C['navy']};color:{_C['yellow']};
  font-size:28px;font-weight:900;display:flex;align-items:center;justify-content:center;}}
.t{{font-size:26px;font-weight:700;color:{_C['text']};letter-spacing:-0.5px;}}
</style>{rows}"""
    path = _shot(_wrap(inner, "접수 전, 이 5가지만 점검하세요", "체크리스트"))
    if path:
        logger.info(f"청약 체크리스트 카드 생성 → {path}")
    return path


def create_cheongyak_cards(facts: dict) -> list[dict]:
    """3종 카드 일괄 생성 — [{local_path, label, anchor_hint}] (실패 카드는 제외)."""
    out = []
    name = facts.get("단지명", "")
    for fn, label, hint in (
        (create_overview_card, "청약 핵심 요약", "overview"),
        (create_schedule_card, "청약 일정", "schedule"),
        (create_payment_card, "필요 현금", "payment"),
        (create_type_card, "타입별 구성 요약", "types"),
        (create_price_card, "타입별 분양가", "price"),
        (create_eligibility_card, "규제·자격 체크", "eligibility"),
        (create_checklist_card, "청약 전 체크리스트", "checklist"),
    ):
        try:
            p = fn(facts)
        except Exception as e:
            logger.warning(f"청약 카드 실패({hint}): {e}")
            p = None
        if p:
            out.append({"local_path": p, "label": f"{name} {label}", "anchor_hint": hint})
    return out
