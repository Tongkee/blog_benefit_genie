# -*- coding: utf-8 -*-
"""실험B: 유명 경제 블로그 소싱 → 현지언니화 재작성 (2026-07-29 사용자 지시).

소스(2026-07-29 실측 선정): 메르(ranto28)·홍춘욱(hong8706)·빠숑(ppassong).
원칙(표절·유사문서 원천 차단):
- 소스에서 **팩트·수치·타임라인만** 추출(Gemini 구조화). 문장·문단·글 구조 재사용 금지.
- 블로거의 전망·해석은 반드시 "한 경제 블로거/전문가의 견해"로 분리 표기.
- 생성 후 15자+ 연속 문자열이 원문과 겹치면 재생성(하드 게이트).
- 이미지·차트 재사용 금지(수치만 뽑아 자체 카드로).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape

import requests

logger = logging.getLogger("econ_digest")

SOURCES = [
    ("ranto28", "메르"),
    ("hong8706", "홍춘욱"),
    ("ppassong", "빠숑"),
]
_UA = {"User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile Safari/604.1")}


def _active_sources(max_daily: int = 12) -> list[tuple[str, str]]:
    """코어 3개 + 검증 확장 소스(data/econ_sources.json, discover_econ_blogs.py 산출)를
    일자 로테이션으로 최대 max_daily개 반환 (2026-07-31 §2-④ 소스 확장).

    확장 효과: ①후보 12건→수십건 ②한 블로거 의존 소멸 ③여러 블로그 동시 주제
    = 진짜 화제 판별 기반. 로테이션인 이유: 60개 전부 매일 긁으면 RSS 240콜/일 —
    후보 과다·요청 낭비라 하루 12개(코어 3 + 순환 9)로 캡."""
    ext: list[tuple[str, str]] = []
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "econ_sources.json")
        for e in json.load(open(path, encoding="utf-8")):
            if e.get("id"):
                ext.append((e["id"], e.get("name") or e["id"]))
    except Exception:
        pass
    core_ids = {c[0] for c in SOURCES}
    ext = [p for p in ext if p[0] not in core_ids]
    if not ext:
        return list(SOURCES)
    doy = datetime.now(timezone(timedelta(hours=9))).timetuple().tm_yday
    start = (doy * 9) % len(ext)
    rot = (ext[start:] + ext[:start])[:max(0, max_daily - len(SOURCES))]
    return list(SOURCES) + rot


def fetch_candidates(seen: set[str], per_blog: int = 3) -> list[dict]:
    """RSS에서 신규 글 후보 수집 — [{blog_id, author, title, url, log_no}]."""
    out = []
    for blog_id, author in _active_sources():
        try:
            r = requests.get(f"https://blog.rss.naver.com/{blog_id}.xml", headers=_UA, timeout=15)
            r.raise_for_status()
            items = re.findall(r"<item>(.*?)</item>", r.text, re.S)[:per_blog]
            for it in items:
                t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
                g = re.search(r"<guid[^>]*>(.*?)</guid>", it, re.S) or re.search(r"<link>(.*?)</link>", it, re.S)
                if not (t and g):
                    continue
                url = unescape(g.group(1).strip())
                m = re.search(r"/(\d{9,})", url)
                if not m or url in seen:
                    continue
                out.append({"blog_id": blog_id, "author": author,
                            "title": unescape(t.group(1).strip()), "url": url, "log_no": m.group(1)})
        except Exception as e:
            logger.info(f"{blog_id} RSS 실패(스킵): {e.__class__.__name__}")
    logger.info(f"소스 신규 후보 {len(out)}건")
    return out


def fetch_body_text(blog_id: str, log_no: str) -> str:
    """모바일 본문 텍스트(se-main-container) — requests로 정적 파싱(실측 검증됨)."""
    from bs4 import BeautifulSoup
    r = requests.get(f"https://m.blog.naver.com/{blog_id}/{log_no}", headers=_UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.select_one(".se-main-container") or soup.select_one("#viewTypeSelector")
    if not main:
        return ""
    txt = main.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", txt)


def pick_topic(cands: list[dict], api_key: str) -> dict | None:
    """오늘 1건 선정 — 분석 가치·생활 재테크 관련성 기준(종목 추천성·공지성 배제)."""
    from generator.content import _gen_text
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    listing = "\n".join(f"{i}. [{c['author']}] {c['title']}" for i, c in enumerate(cands))
    try:
        txt = _gen_text(api_key,
                        f"다음 경제 블로그 신규 글 중 '20대 생활 재테크 독자에게 쉽게 풀어줄 가치'가 가장 큰 글 1개를 골라라.\n"
                        f"제외: 특정 종목 매수 유도성, 공지/잡담, 시리즈 중간 회차라 맥락 없이는 이해 불가한 글, "
                        f"언론 인터뷰·기사 전재/인용 위주 글(『』·기사제목 형식 — 발언 인용이 많아 재작성 부적합), "
                        f"★에세이·자기계발·인생조언·감상문류(2026-07-30 실사고: 수치가 없어 재서술이 불가능해 "
                        f"표절 게이트를 3회 연속 통과 못함).\n"
                        f"★필수 조건: 수치·통계·정책·제도 등 '팩트'가 본문에 있는 분석글만 고를 것.\n"
                        f"{listing}\n출력: 번호 하나만.", "글 선정기. 숫자만 출력.", 100, 0.1)
        i = int(re.search(r"\d+", txt).group())
        return cands[i] if 0 <= i < len(cands) else cands[0]
    except Exception:
        return cands[0]


def extract_facts(src_text: str, author: str, api_key: str) -> dict | None:
    """팩트(수치·사건·타임라인·원출처) vs 블로거 견해 분리 추출."""
    from generator.content import _gen_text
    try:
        txt = _gen_text(api_key,
                        "아래 경제 블로그 글에서 정보를 추출해 JSON으로 출력하라.\n"
                        "{\"topic\": 주제 한 줄, \"facts\": [확정 사실·수치·사건 8~15개, 각 항목에 원출처(기관·언론) 있으면 표기],\n"
                        " \"timeline\": [시간 순 사건 0~6개], \"opinions\": [글쓴이의 해석·전망 2~5개],\n"
                        " \"terms\": [독자가 모를 전문용어 2~4개와 한 줄 정의]}\n"
                        "규칙: 원문 문장을 복사하지 말고 정보 단위로 재서술. 수치는 원문 그대로 정확히.\n\n"
                        f"[원문 — {author}의 글]\n{src_text[:9000]}",
                        "정보 추출기. JSON만 출력.", 4000, 0.2)
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        return json.loads(txt)
    except Exception as e:
        logger.error(f"팩트 추출 실패: {e.__class__.__name__}")
        return None


# 불가피 고정용어 — 원문과 그대로 겹쳐도 표절 아님(법정 세목·제도·부동산 용어). 확장 가능.
# 표절 게이트는 '문장(산문) 베끼기'를 잡아야지, 이런 고정 용어·수치 일치를 잡으면 세법·부동산
# 주제가 무한 재생성 실패한다(2026-07-30 요즘경제 '3주택이상중과세율' 등으로 발행 포기).
_FIXED_TERMS = [
    # 세목·과세
    "양도소득세", "종합부동산세", "종부세", "취득세", "재산세", "종합소득세", "부가가치세",
    "중과세율", "누진세율", "기본세율", "과세표준", "비과세", "과세대상", "세액공제", "소득공제",
    "공제한도", "기본공제", "장기보유특별공제", "세대구분", "납부기한", "가산세", "양도차익",
    "취득가액", "실거래가", "기준시가", "공시가격", "공정시장가액비율",
    # 부동산·주택
    "다주택자", "무주택자", "1세대1주택", "1세대2주택", "2주택", "3주택이상", "조정대상지역",
    "투기과열지구", "보유기간", "거주기간", "집합건물", "매도자", "매수자", "분양권", "입주권",
    "전매제한", "실거주의무", "주택담보대출", "총부채원리금상환비율", "담보인정비율",
    # 금융·거시
    "기준금리", "예금자보호", "총부채상환비율", "국내총생산", "소비자물가지수", "경상수지",
    # 2026-07-30 실사고 반영: 세법 조건 나열이 통째로 겹쳐 게이트가 3회 전멸했던 표현들
    "주택이상중과세율", "중과세율", "보유기간", "집합건물", "매도자", "다주택자",
    "취득세중과", "종합부동산세", "일시적2주택", "조정대상지역", "비과세요건",
    "장기보유특별공제", "필요경비", "기본공제", "누진공제", "과세표준",
]


_PROSE_RE = re.compile(
    r"(습니다|입니다|해요|하죠|이라|하는|되는|에서|으로|보다|처럼|만큼|"
    r"늘었|줄었|했다|한다|된다|있다|없다|졌다|겠다|면서|지만|때문|경우|"
    r"라고|다는|라는|이며|하며|이고|하고|해서|아서|어서)")


def overlap_guard(body: str, src_text: str, min_len: int = 18) -> list[str]:
    """생성 본문과 원문의 연속 '산문' 겹침 검출(유사문서·표절 하드 게이트).

    ★2026-07-30: 표절은 '문장 베끼기'다. 숫자(팩트라 반드시 일치)·법정 고정용어(바꿀 수 없음)를
    마스킹한 뒤 비교해, 불가피한 겹침은 제외하고 진짜 산문 복제만 잡는다. hits는 원본 문자열로 보고."""
    norm = lambda s: re.sub(r"\s+", "", s)

    def mask(s: str) -> str:
        s = norm(s)
        for t in _FIXED_TERMS:            # 고정용어 → 단일기호(길이 축소로 임계 미달 유도)
            s = s.replace(t, "·")
        s = re.sub(r"[0-9][0-9.,%]*", "·", s)   # 숫자 토큰 → 단일기호
        return s

    b_raw = norm(body)
    b_m, s_m = mask(body), mask(src_text)
    if len(b_m) != len(b_raw):
        # 마스킹으로 길이가 바뀌면 원본 인덱스 매핑이 깨진다 → 마스킹 문자열끼리 비교하고
        # hits는 마스킹본 청크로 보고(피드백은 '어떤 표현을 바꿀지'만 알려주면 충분).
        b_raw = b_m
    hits = []
    step = max(1, min_len // 3)          # 촘촘히 슬라이딩(어미가 청크 경계 밖으로 밀리는 것 방지)
    for i in range(0, max(1, len(b_m) - min_len + 1), step):
        chunk = b_m[i:i + min_len]
        if len(chunk) < min_len:
            continue
        if "·" * 3 in chunk:             # 마스크 3개 이상 = 고정용어·숫자 나열 → 산문 아님
            continue
        # 산문 판정(2026-07-30 실사고): 서술어·연결어미가 없으면 '용어 나열'로 보고 제외.
        # 예: '울집합건물매도자중보유기간20' = 조건 나열이라 표절 아님 / '~장기보유자가늘었습니다' = 산문.
        if not _PROSE_RE.search(chunk):
            continue
        if chunk and chunk in s_m and chunk not in hits:
            hits.append(b_raw[i:i + min_len])
            if len(hits) >= 5:
                break
    return hits


def paragraphize(body: str, per_para: int = 1) -> str:
    """문장 줄들을 문단으로 묶어 빈 줄로 띄운다(2026-07-31 사용자 지시).

    ★2026-07-31 골격 게이트(B): 기본 1문장 = 1문단. 메르 24건 전수 실측에서
    한 문장이 한 문단이었다(상한 87자). generator/skeleton_gate.py 상수와 정합.

    ★배경: 문장은 짧게 끊었는데 줄바꿈(\\n)만 써서 에디터에서 한 문단으로 붙었다.
    poster._type_in_editor는 '\\n\\n'을 문단 경계로 쓰므로, 빈 줄이 없으면
    열 문장이 한 덩어리로 보인다. 벤치마크(메르)는 1~2문장마다 문단을 끊어
    한 화면의 글자 수가 훨씬 적고 읽기 쉽다.

    문단 경계 규칙: 사진 마커·소제목·참고 줄은 항상 단독 문단으로 분리한다.
    """
    out, buf = [], []

    def flush():
        if buf:
            out.append("\n".join(buf))
            buf.clear()

    for raw in body.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if re.match(r"^\[사진\d+\]$", ln) or ln.startswith("참고:"):
            flush()
            out.append(ln)
            continue
        buf.append(ln)
        # 문단 길이: 기본 per_para 문장, 단 누적 글자수가 87자(메르 실측 상한)를 넘으면 즉시 끊는다
        if len(buf) >= per_para or sum(len(x) for x in buf) > 87:
            flush()
    flush()
    return "\n\n".join(out)


def place_body_images(body: str, n: int = 2, start_no: int = 2) -> tuple[str, list[str]]:
    """[사진N] 마커를 누적 글자수 기준으로 배치 (2026-07-31 골격 게이트 B로 교체).

    종전: 문단 개수 균등 분할. 메르 24건 실측은 누적 문자수 기준 —
    첫 장 본문 125자 뒤 → 이후 509자당 1장 → 마지막 장은 88.6% 지점.
    첫 블록 앞에는 절대 배치하지 않는다(첫 블록 텍스트 24/24).
    """
    from generator.skeleton_gate import place_markers_by_chars
    return place_markers_by_chars(body, n, start_no=start_no)


def rhythm_issues(body: str) -> list[str]:
    """서사형 호흡 게이트 — 짧은 호흡·서술체·도입부를 결정론으로 검사(2026-07-31 신설).

    근거(원본 대조 실측): 메르 원본은 117줄·평균 17자·최장 87자인데, 현지언니 톤으로
    쓴 첫 발행본은 48줄·평균 53자·최장 241자였다. 몰입감 차이의 실체가 이 호흡이다.
    프롬프트만으로는 모델이 금세 긴 문단으로 돌아가므로 게이트로 못 박는다.
    """
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        return ["본문 없음"]
    issues = []
    lens = [len(ln) for ln in lines]
    avg = sum(lens) / len(lens)
    if avg > 38:
        issues.append(f"줄 평균 {avg:.0f}자 — 한 줄에 한 문장으로 끊어라(목표 15~25자)")
    over = [ln for ln in lines if len(ln) > 87]
    if over:
        issues.append(f"87자(메르 실측 상한) 넘는 줄 {len(over)}개 — 쪼개라: {over[0][:40]}…")
    head = lines[0]
    for bad in ("안녕하세요", "현지언니", "정리해 드릴", "정리해드릴", "드릴게요"):
        if bad in body:
            issues.append(f"페르소나 인사말 사용 금지: {bad!r}")
            break
    if "결론부터 말하면" in body:
        issues.append("두괄식 금지 — 시간순 서사로 풀어라('결론부터 말하면' 사용됨)")
    if "❓" in body:
        issues.append("용어 정의 줄(❓) 금지 — 문장 안에서 풀어라")
    # 도입부: 첫 줄이 인사·요약이 아니라 장면·날짜여야 한다
    if not re.search(r"\d{4}년|\d+월 \d+일|였다|이었다|시작", head):
        issues.append(f"첫 줄이 장면·날짜로 열리지 않음: {head[:40]!r}")
    return issues


def write_post(facts: dict, author: str, api_key: str, avoid: list[str] | None = None,
               style_feedback: list[str] | None = None) -> dict | None:
    """서사형 글 생성 — 완전히 새 구조·새 문장(TITLE/TAGS/본문 마커 형식).

    avoid: 직전 시도에서 원문과 겹친 문자열 — 어순·표현을 바꿔 다시 쓰도록 되먹임.
    style_feedback: 직전 시도의 서사 호흡 게이트 지적 — 문장 길이·도입부를 고치도록 되먹임.
    """
    from generator.content import _gen_text
    facts_json = json.dumps(facts, ensure_ascii=False, indent=1)
    style_block = ""
    if style_feedback:
        style_block = ("\n⚠️직전 초안이 서사 호흡 기준에 미달했다. 아래를 고쳐 다시 써라:\n- "
                       + "\n- ".join(style_feedback) + "\n")
    avoid_block = ""
    if avoid:
        avoid_block = ("\n⚠️직전 초안이 원문과 겹쳤다. 아래 문자열이 그대로 나오지 않게 "
                       "어순을 바꾸고 풀어 써라(제도명·수치는 쓰되 배열을 다르게):\n- "
                       + "\n- ".join(avoid) + "\n")
    prompt = (
        "'쉽게보는 요즘경제'는 경제 사건을 **시간순 이야기**로 풀어주는 코너다.\n"
        "정보 정리글이 아니라 **끝까지 읽히는 글**이 목적이다. 독자가 첫 줄에서 멈추지 않고\n"
        "스크롤을 계속하게 만드는 것이 유일한 성공 기준이다.\n\n"
        f"[추출 정보]\n{facts_json}\n\n"
        "★문체 — 이 코너는 '현지언니' 페르소나를 쓰지 않는다(2026-07-31 사용자 지시).\n"
        "1. 담백한 서술체로 쓴다('~다', '~였다', '~이다'). 인사말·자기소개·맺음인사 전부 금지"
        "('안녕하세요', '현지언니입니다', '~해 드릴게요', '~정리해 드릴게요').\n"
        "2. ★한 줄에 한 문장. 평균 15~25자, 한 문장이 60자를 넘지 않게 끊어라.\n"
        "   이 코너의 몰입감은 짧은 호흡에서 나온다. 문장이 길어지면 무조건 쪼갠다.\n"
        "3. 첫 줄은 날짜나 장면으로 연다. 예: '1987년 10월 19일은 월요일이었다.'\n"
        "   요약·결론·인사로 시작하지 마라. 첫 줄이 재미없으면 글 전체가 실패다.\n\n"
        "★구조 — 시간순 서사\n"
        "4. 사건을 일어난 순서대로 따라간다: 기원 → 도입 → 첫 사건 → 되풀이된 사건들 → 지금.\n"
        "   '결론부터 말하면' 같은 두괄식 금지. 결론은 마지막에 드러난다.\n"
        "5. ★소제목 금지(0개 — 메르 24건 실측 소제목 0). 흐름을 끊지 마라. '❓ 용어' 정의 줄 금지 —\n"
        "   용어는 문장 안에서 자연스럽게 풀어 설명한다. 번호 목록(1. 2. 3.)도 금지 — 서술체다.\n"
        "6. 날짜와 숫자가 이야기의 뼈대다. facts의 수치를 시간 순서로 배치하라.\n"
        "7. 어려운 개념은 일상 사물 비유 1~2개로 푼다(예: 두꺼비집, 브레이크).\n\n"
        "★사실 규칙(유지)\n"
        "8. facts의 수치만 사용(새 수치 창작 금지). opinions는 반드시 "
        "'한 경제 블로거는 ~로 본다'처럼 견해로 분리 표기 — 사실처럼 단정 금지.\n"
        "9. ★직접 인용 절대 금지 — 발언·문구를 따옴표로 옮기지 말고 전부 네 말로 다시 써라"
        "(원문과 15자만 겹쳐도 글 전체가 폐기된다).\n"
        "10. 전망은 개연 화법(~가능성이 있다/~로 보인다).\n"
        "11. 본문 1,800~2,400자. 표·이모지·마크다운 금지.\n"
        "12. ★연도는 반드시 2026년(또는 추출 정보의 최신 연도) — 2024·2025년 구식 연도 금지.\n"
        "13. ★마감 코멘트(본문 끝, '참고:' 줄 바로 앞) — 정확히 3문장, 전부 사실문장:\n"
        "    ①본문에 쓴 핵심 수치 2개를 다시 적는다 ②그 두 수치의 단순 산술 결과 1개\n"
        "    (배수·차이·비율 — facts 수치로만 계산) ③확정된 다음 공식 일정(발표일·시행일).\n"
        "    '전망된다'·'할 것 같다'·'보인다' 같은 예측·판단 표현 절대 금지.\n"
        "14. 마지막 줄: '참고: 공개 경제 데이터 및 경제 블로거 분석 재구성' 한 줄.\n"
        "출력 형식:\nTITLE: {제목 — 숫자 포함 30자 이내, 쉬운 말}\nTAGS: {태그 6개 쉼표구분}\n---\n{본문}"
        + avoid_block + style_block
    )
    try:
        txt = _gen_text(api_key, prompt, "경제 사건을 시간순으로 풀어 쓰는 기록자. 짧은 문장으로 끊어 쓴다.", 8000, 0.7)
    except Exception as e:
        logger.error(f"글 생성 실패: {e}")
        return None
    m = re.search(r"TITLE:\s*(.+)", txt)
    tg = re.search(r"TAGS:\s*(.+)", txt)
    body = txt.split("---", 1)[-1].strip()
    # ★헤더 누출 방어(2026-07-31 실사고): 모델이 '---' 구분선을 빼먹으면 split이 원문을
    # 그대로 돌려줘 'TITLE: …' 'TAGS: …' 두 줄이 본문 맨 위에 발행됐다(224363841201).
    body = "\n".join(ln for ln in body.splitlines()
                     if not re.match(r"^\s*(TITLE|TAGS)\s*:", ln)).strip()
    if not m or len(body) < 800:
        logger.error("생성 형식 불량")
        return None
    subs = [ln.strip().replace("[소제목]", "").strip() for ln in body.splitlines()
            if ln.strip().startswith("[소제목]")]
    body = "\n".join(ln.replace("[소제목]", "").strip() if ln.strip().startswith("[소제목]") else ln
                     for ln in body.splitlines())
    tags = [t.strip() for t in (tg.group(1) if tg else "경제이슈,재테크").split(",") if t.strip()][:7]
    return {"title": m.group(1).strip()[:48], "body": body, "tags": tags, "subheadings": subs}
