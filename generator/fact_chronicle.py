# -*- coding: utf-8 -*-
"""번호 팩트 연대기(M1) 엔진 — 요즘경제 1차 원문 전환 (2026-07-31, NEXT_SESSION §1.D).

복제 문제의 근원 차단: 주제만 블로그에서 빌리고 사실은 1차 원문에서 직접 가져온다.
블로거 글에서 사실을 뽑으면 그 사람의 선택·배열을 물려받는다(잘 쓰면 복제, 못 쓰면 열화판).

M1 형식(이 형식을 고른 결정적 이유 — 검증 실패 항목을 삭제해도 글이 안 깨진다):
  팩트를 (날짜, 사실 1문장, 수치들, 출처 URL) 4-튜플로 적재
  → ★URL 없으면 배제 → 금지 목록 필터 → 날짜순 정렬 → 기계가 1~N 번호 부여
  → LLM은 튜플→문장 변환만(수치 창작 불가) → ★숫자 대조 게이트(문장의 모든 숫자가
     그 튜플 수치 집합에 있어야 통과, 실패 항목은 삭제하고 번호 재부여)
  → ★하한 게이트(기본 15항 미달이면 발행 스킵 — ECON_M1_MIN 으로 조정)

금지 목록(성과가 최고여도 금지 — 메르 최고 성과글 유형이지만 하지 않는다):
  실명 개인 · 사인간 거래 · 언론 보도 재구성 · 출처 미상 인용

1차 소스 현황(2026-07-31 집 PC 실측):
  - DART 오늘공시 RSS(dart.fss.or.kr/api/todayRSS.xml) — 키 불요, 200 확인 ✅
  - 국토부 실거래가 API — PUBLIC_DATA_KEY 등록됨(rt_price.py 재사용 가능)
  - 부처 보도자료 RSS — korea.kr·부처 직접 경로 전부 404/빈 응답, 경로 재조사 필요
"""
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("fact_chronicle")
KST = timezone(timedelta(hours=9))

MIN_ITEMS_DEFAULT = 15

# 금지 목록 — 항목 문장·주제에서 발견되면 그 팩트를 배제한다
_BANNED_RE = re.compile(
    r"대통령|장관 후보|의원|연예인|배우|가수|유튜버|인플루언서"   # 실명 개인 신상류
    r"|매매내용|계좌 내역|개인 간 거래|사인간"                    # 사인간 거래
    r"|에 따르면|단독 보도|보도했다|기사에서"                     # 언론 재구성
    r"|관계자는|익명의|소식통")                                   # 미상 인용


def _figures_of(text: str) -> set:
    """콤마 제거 숫자 토큰 집합 — 숫자 대조 게이트 기준."""
    return set(re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")))


def load_facts(raw_facts: list) -> list:
    """4-튜플 적재 + 배제 게이트. 입력: [{date, fact, figures, source_url}] (figures 는
    수치 문자열 목록 — 비어 있으면 fact 문장에서 추출). 반환: 정렬·번호 부여된 목록.

    배제 순서: ①URL 없음 ②금지 목록 ③날짜 형식 불량. 남은 항목을 날짜순 정렬 후
    기계가 1~N 번호를 붙인다(LLM이 번호를 만들지 않는다).
    """
    kept = []
    for f in raw_facts or []:
        url = (f.get("source_url") or "").strip()
        if not url.startswith("http"):
            logger.info(f"[M1] URL 없음 — 배제: {str(f.get('fact'))[:40]!r}")
            continue
        fact = (f.get("fact") or "").strip()
        if not fact:
            continue
        if _BANNED_RE.search(fact):
            logger.info(f"[M1] 금지 목록 매칭 — 배제: {fact[:40]!r}")
            continue
        date = (f.get("date") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", date):
            logger.info(f"[M1] 날짜 형식 불량({date!r}) — 배제: {fact[:40]!r}")
            continue
        figures = [str(x) for x in (f.get("figures") or [])] or sorted(_figures_of(fact))
        kept.append({"date": date, "fact": fact, "figures": figures, "source_url": url})
    kept.sort(key=lambda f: f["date"])
    for i, f in enumerate(kept, 1):
        f["no"] = i
    return kept


def verify_rendered(items: list, rendered: dict) -> list:
    """★숫자 대조 게이트. rendered: {번호(int): 변환 문장}. 각 문장의 모든 숫자가
    해당 튜플의 수치 집합(+날짜 토큰)에 있어야 통과. 실패 항목은 삭제하고
    번호를 다시 매긴다 — M1의 존재 이유(삭제해도 글이 안 깨진다).
    반환: [{no, date, sentence, source_url}]"""
    out = []
    for f in items:
        sent = (rendered or {}).get(f["no"], "").strip()
        if not sent:
            logger.info(f"[M1] {f['no']}번 변환 문장 없음 — 튜플 원문 사용")
            sent = f["fact"]
        allowed = _figures_of(" ".join(f["figures"])) | _figures_of(f["fact"]) \
            | _figures_of(f["date"]) | {str(int(t)) for t in _figures_of(f["date"]) if t.isdigit()}
        bad = _figures_of(sent) - allowed
        if bad:
            logger.warning(f"[M1] 숫자 대조 실패({sorted(bad)}) — {f['no']}번 삭제: {sent[:40]!r}")
            continue
        out.append({"date": f["date"], "sentence": sent, "source_url": f["source_url"]})
    for i, f in enumerate(out, 1):
        f["no"] = i
    return out


def render_body(verified: list, topic_title: str) -> str:
    """검증 통과 항목 → 번호 연대기 본문(메모체 레지스터 — 번호 1~N 연속).
    1문단 1문장(골격 게이트 B 정합). 출처는 항목 바로 아래 붙인다(URL 명시 원칙)."""
    paras = []
    for f in verified:
        d = f["date"]
        disp = d if len(d) == 7 else d      # YYYY-MM 또는 YYYY-MM-DD 그대로
        paras.append(f"{f['no']}. ({disp}) {f['sentence']}")
        paras.append(f"출처: {f['source_url']}")
    paras.append("참고: 공식 공시·공공데이터 원문 연대기")
    return "\n\n".join(paras)


def min_items_gate(verified: list, min_items: int = MIN_ITEMS_DEFAULT) -> bool:
    """★하한 게이트 — 미달이면 발행 스킵(빈약한 연대기를 내보내느니 뺀다)."""
    ok = len(verified) >= min_items
    if not ok:
        logger.warning(f"[M1] 하한 게이트 미달: {len(verified)}/{min_items}항 — 발행 스킵")
    return ok


# 주제 키워드 추출용 불용어 — 블로그 제목 상투어(2026-07-31 라이브 실측:
# '오늘','우리','국장은','feat' 같은 토큰이 DART 매칭을 0건으로 만들었다)
_KW_STOP = {"오늘", "우리", "국장", "이유", "원인", "하나", "숨은", "진짜", "방법",
            "정리", "총정리", "feat", "것", "지금", "최근", "현재", "시장", "생각",
            "이야기", "관련", "정도", "상황", "문제", "이번", "다시", "결국"}
_JOSA_RE = re.compile(r"(은|는|이|가|을|를|의|에|로|들|도|만)$")


def topic_keywords(title: str, limit: int = 8) -> list:
    """블로그 글 제목 → 1차 소스 매칭용 키워드. 조사 제거 + 상투어 배제.
    영문 티커(PCE·TRS 등)와 고유명사 위주로 남긴다."""
    out = []
    for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", title or ""):
        base = _JOSA_RE.sub("", t)
        if len(base) < 2 or base in _KW_STOP or base.lower() in _KW_STOP:
            continue
        if base not in out:
            out.append(base)
    return out[:limit]


def llm_render(items: list, api_key: str) -> dict:
    """튜플→문장 변환만 LLM에 맡긴다. 번호·수치·순서·출처는 전부 기계가 관리하고,
    결과는 verify_rendered 의 숫자 대조 게이트를 다시 통과해야 한다.
    실패 시 빈 dict — verify_rendered 가 튜플 원문으로 폴백한다."""
    from generator.content import _gen_text
    import json as _json
    src = [{"no": f["no"], "date": f["date"], "fact": f["fact"],
            "figures": f["figures"]} for f in items]
    prompt = (
        "아래 사실 튜플 각각을 자연스러운 한국어 사실 문장 1개로 바꿔라.\n"
        "규칙: ①수치·날짜는 튜플에 있는 것만 그대로(창작·환산·반올림 금지) "
        "②'~했다/~됐다' 서술 종결 ③한 문장 40~80자 ④판단·전망 표현 금지.\n"
        "반드시 JSON 객체 하나만 출력: {\"1\": \"문장\", \"2\": \"문장\", ...}\n\n"
        + _json.dumps(src, ensure_ascii=False, indent=1)
    )
    try:
        txt = _gen_text(api_key, prompt,
                        "튜플을 짧은 사실 문장으로 바꾸는 변환기. 수치와 날짜를 창작하지 않는다.",
                        4000, 0.3)
        s = txt[txt.find("{"): txt.rfind("}") + 1]
        raw = _json.loads(s)
        return {int(k): str(v) for k, v in raw.items() if str(k).lstrip().isdigit()}
    except Exception as e:
        logger.warning(f"[M1] 변환 LLM 실패 — 튜플 원문 사용: {e.__class__.__name__}")
        return {}


# ── 1차 소스 수집기 ──────────────────────────────────────────
def _rss_facts(url: str, fact_suffix: str, label: str,
               keywords: list, limit: int) -> list:
    """RSS(제목·링크·날짜)를 키워드 매칭해 4-튜플로. 수치는 제목에 있는 것만
    figures 로 넣는다(본문 파싱은 하지 않는다 — 제목 밖 수치 창작 차단)."""
    import requests
    import xml.etree.ElementTree as ET
    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        logger.warning(f"[M1] {label} RSS 실패: {e.__class__.__name__}")
        return []
    kws = [k for k in (keywords or []) if len(k) >= 2]
    out = []
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if kws and not any(k in title for k in kws):
            continue
        pub = (item.findtext("pubDate") or item.findtext(
            "{http://purl.org/dc/elements/1.1/}date") or "").strip()
        m = re.search(r"(\d{4})[-./](\d{2})[-./](\d{2})", pub)
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else today
        out.append({"date": date, "fact": f"{title}{fact_suffix}",
                    "figures": sorted(_figures_of(title)), "source_url": link})
        if len(out) >= limit:
            break
    logger.info(f"[M1] {label} 매칭 {len(out)}건 (키워드 {kws[:5]})")
    return out


def dart_today_facts(keywords: list, limit: int = 30) -> list:
    """DART 오늘공시 RSS(키 불요, 2026-07-31 실측 200)."""
    return _rss_facts("https://dart.fss.or.kr/api/todayRSS.xml",
                      " 공시가 제출됐다", "DART 오늘공시", keywords, limit)


def bok_press_facts(keywords: list, limit: int = 30) -> list:
    """한국은행 보도자료 RSS(키 불요, 2026-07-31 밤 실측 — 부처급 RSS 중 유일 생존).
    게시판: B0000501(보도자료 통계)·B0000502(보도자료 기타). ⚠️B0000338은 화폐박물관
    소장품 게시판이니 쓰지 말 것. 기재부·금융위·국토부·복지부·고용부·국세청·공정위
    RSS는 전부 404/HTML(경로 폐지 추정)."""
    out = []
    for bid, name in (("B0000501", "한은 보도자료(통계)"), ("B0000502", "한은 보도자료(기타)")):
        out += _rss_facts(f"https://www.bok.or.kr/portal/bbs/{bid}/news.rss",
                          f" — {name.split('(')[0].strip()} 발표가 나왔다", name,
                          keywords, limit)
    return out[:limit]
