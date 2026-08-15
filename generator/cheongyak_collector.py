"""청약홈(한국부동산원) 분양공고 수집 — 건별 청약 분석글 파이프라인 (2026-07-17 사용자 지시).

데이터: 공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스' (odcloud v1)
  · getAPTLttotPblancDetail — APT 분양공고 상세(일정·지역·규제·URL)
  · getAPTLttotPblancMdl    — 주택형별 공급세대·최고분양가
  · getRemndrLttotPblancDetail — 무순위/잔여세대(줍줍)
키: config.PUBLIC_DATA_KEY (미설정 시 수집 스킵 — 파이프라인은 조용히 종료)

공고문 PDF: 공고 상세페이지(PBLANC_URL)에서 모집공고문 링크를 찾아 텍스트 발췌
  → 계약금 비율·중도금 대출 조건 등 API에 없는 디테일을 팩트로 주입(best-effort,
  실패해도 API 팩트만으로 발행 가능).

대상 지역: 수도권+광역시(2026-07-17 사용자 승인 범위). 임대 공고는 제외.
"""
import io
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import PUBLIC_DATA_KEY, GOOGLE_API_KEY

logger = logging.getLogger("cheongyak_collector")

KST = timezone(timedelta(hours=9))
_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
_TIMEOUT = 30

# 수도권 + 광역시 + 세종 (청약홈 SUBSCRPT_AREA_CODE_NM 표기)
REGIONS = {"서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종"}


def _call(endpoint: str, cond: dict | None = None, per_page: int = 100) -> list[dict]:
    """odcloud 공통 호출. 실패/키 없음 → 빈 리스트."""
    if not PUBLIC_DATA_KEY:
        logger.warning("PUBLIC_DATA_KEY 미설정 — 청약홈 수집 스킵 "
                       "(data.go.kr에서 '청약홈 분양정보' 활용신청 후 키 등록 필요)")
        return []
    params = {"page": 1, "perPage": per_page, "serviceKey": PUBLIC_DATA_KEY}
    for k, v in (cond or {}).items():
        params[f"cond[{k}]"] = v
    try:
        r = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"청약홈 API 호출 실패 ({endpoint}): {e}")
        return []


def _is_target(d: dict) -> bool:
    region = (d.get("SUBSCRPT_AREA_CODE_NM") or "").strip()
    if region not in REGIONS:
        return False
    # 임대 공고 제외(분양만) — RENT_SECD: 0=분양, 1=임대(명칭 필드가 더 안정적)
    rent_nm = str(d.get("RENT_SECD_NM") or d.get("RENT_SECD") or "")
    if "임대" in rent_nm or rent_nm == "1":
        return False
    return True


def fetch_new_apt_notices(days: int = 7) -> list[dict]:
    """최근 N일 모집공고(APT 분양) — 대상 지역·분양만."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _call("getAPTLttotPblancDetail", {"RCRIT_PBLANC_DE::GTE": cutoff})
    out = [d for d in rows if _is_target(d)]
    logger.info(f"청약홈 APT 공고: 최근 {days}일 {len(rows)}건 → 대상지역 {len(out)}건")
    return out


def fetch_new_remainder_notices(days: int = 7) -> list[dict]:
    """최근 N일 무순위/잔여세대(줍줍) 공고."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = _call("getRemndrLttotPblancDetail", {"RCRIT_PBLANC_DE::GTE": cutoff})
    out = [d for d in rows if _is_target(d)]
    for d in out:
        d["_remainder"] = True
    logger.info(f"청약홈 무순위 공고: 최근 {days}일 {len(rows)}건 → 대상지역 {len(out)}건")
    return out


def fetch_house_types(house_manage_no: str, remainder: bool = False) -> list[dict]:
    """주택형별 공급세대수·최고분양가."""
    ep = "getRemndrLttotPblancMdl" if remainder else "getAPTLttotPblancMdl"
    return _call(ep, {"HOUSE_MANAGE_NO::EQ": house_manage_no})


def notice_key(d: dict) -> str:
    return f"{d.get('HOUSE_MANAGE_NO', '')}-{d.get('PBLANC_NO', '')}"


# ── 공고문 PDF: 다운로드 → 텍스트 발췌 + 핵심 페이지 이미지 캡처 ─────────────

_PDF_KEYWORDS = ("계약금", "중도금", "잔금", "공급금액", "납부", "대출", "발코니", "옵션")
# 이미지 캡처 대상 페이지 분류 (2026-07-17 사용자 지시: 금액표·평면도 캡처를 본문에)
_PRICE_PAGE_KWS = ("공급금액", "납부일정", "납부조건")
# 평면도 = '평면도' 키워드 + 도면형 페이지(텍스트 희박). '단위세대'는 유의사항 문단에도
# 흔해 오탐(월계 공고 p42/54 실측) — 제외. 도면 없는 공고(월계 등)에선 캡처 안 됨이 정답.
_PLAN_KW = "평면도"
_PLAN_MAX_TEXT = 900
# 단지 도면류(2026-07-28 벤치마킹: 배치도·조감도·위치도도 본문 삽입) — 키워드 + 텍스트
# 희박(도면형) 페이지만. 유의사항 문단("견본주택 내 비치된 조감도·투시도…")에도 키워드가
# 흔해(더샵 트리센트 p54=2,448자 실측 오탐) 평면도와 같은 잣대(_PLAN_MAX_TEXT)로 거른다.
# 도면 없는 공고(더샵 트리센트: 73p 전부 텍스트, 대형 임베디드 이미지 0 실측)에선 캡처 0장이 정답.
_SITE_KW_LABELS = {"배치도": "단지 배치도", "조감도": "단지 조감도", "투시도": "단지 조감도",
                   "위치도": "단지 위치도"}


_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def fetch_notice_pdf(detail: dict) -> bytes | None:
    """공고 상세페이지(PBLANC_URL)에서 모집공고문 PDF 바이트 확보. 실패 시 None.
    세션 유지+브라우저 헤더 — GitHub Actions(해외 IP)에서 차단되는 경우 대비(2026-07-17 실측)."""
    page_url = (detail.get("PBLANC_URL") or "").strip()
    if not page_url:
        return None
    try:
        import html as _html
        sess = requests.Session()
        sess.headers.update(_BROWSER_HEADERS)
        html = sess.get(page_url, timeout=_TIMEOUT).text
        # 1순위: '모집공고문 보기' 앵커 href — 실측 패턴(2026-07-17 월계 중흥S-클래스):
        #   https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=…&atchmnflSn=…
        pdf_url = ""
        m = re.search(r"""<a[^>]+href=["']([^"']+)["'][^>]*>[^<]*모집공고문[^<]*</a>""", html)
        if m:
            pdf_url = _html.unescape(m.group(1))
        if not pdf_url:
            # 2순위: 첨부파일/PDF 계열 링크 패턴
            cands = re.findall(
                r"""["']([^"']+(?:getAtchmnfl\.do[^"']*|\.pdf[^"']*|[Ff]ile[Dd]own[^"']*))["']""", html)
            if cands:
                pdf_url = _html.unescape(cands[0])
        if not pdf_url:
            logger.info("공고문 PDF 링크 미발견 — API 팩트만 사용")
            return None
        if not pdf_url.startswith("http"):
            pdf_url = f"https://www.applyhome.co.kr{pdf_url}"
        r = sess.get(pdf_url, timeout=60, headers={"Referer": page_url})
        pdf_bytes = r.content
        if pdf_bytes[:4] != b"%PDF":
            # 진단용: 차단/오류 페이지 앞부분 기록 (CI 해외 IP 차단 여부 판별)
            head = pdf_bytes[:150].decode("utf-8", errors="replace").replace("\n", " ")
            logger.info(f"공고문 응답이 PDF 아님(HTTP {r.status_code}) — 사용 안 함: {head}")
            return None
        logger.info(f"공고문 PDF 확보: {len(pdf_bytes) // 1024}KB")
        return pdf_bytes
    except Exception as e:
        logger.info(f"공고문 PDF 확보 실패(무시): {e}")
        return None


def _page_texts(pdf_bytes: bytes, max_pages: int = 40) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out = []
    for p in reader.pages[:max_pages]:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            out.append("")
    return out


def pdf_excerpt(pdf_bytes: bytes, max_chars: int = 12000) -> str:
    """납부조건·대출 등 핵심 키워드 페이지 위주 텍스트 발췌 (팩트 주입용)."""
    try:
        pages = _page_texts(pdf_bytes)
        keyed = [t for t in pages if any(k in t for k in _PDF_KEYWORDS)]
        text = "\n".join(keyed or pages[:6])
        text = re.sub(r"[ \t]+", " ", text)
        logger.info(f"공고문 PDF 발췌 {len(text)}자 (키워드 페이지 {len(keyed)}개)")
        return text[:max_chars]
    except Exception as e:
        logger.info(f"공고문 텍스트 발췌 실패(무시): {e}")
        return ""


def pdf_capture_key_pages(pdf_bytes: bytes, max_price: int = 2, max_plan: int = 2,
                          max_site: int = 2) -> list[dict]:
    """공급금액표·평면도·단지 도면(배치도/조감도/위치도) 페이지를 PNG로 렌더
    → [{path, label, page}] (본문 삽입용, PyMuPDF).
    도면이 공고문에 없는 단지는 금액표만 캡처된다. 실패 시 빈 리스트."""
    import tempfile
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.info("PyMuPDF 미설치 — 공고문 페이지 캡처 생략")
        return []
    out: list[dict] = []
    try:
        # 도면류는 공고문 '끝'에 몰림 — 상한 60p 시절 이천 휴먼빌 클래스원 위치도(63p 문서의
        # p.63, 2026-07-28 실측)를 놓쳤다. 120p까지 스캔(실공고 60~73p 수준, 여유 포함).
        texts = _page_texts(pdf_bytes, max_pages=120)
        price_idx = [i for i, t in enumerate(texts) if any(k in t for k in _PRICE_PAGE_KWS)]
        plan_idx = [i for i, t in enumerate(texts)
                    if _PLAN_KW in t and len(t) < _PLAN_MAX_TEXT and i not in price_idx]
        used = set(price_idx) | set(plan_idx)
        site_targets: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            if i in used or len(t) >= _PLAN_MAX_TEXT:
                continue
            for kw, label in _SITE_KW_LABELS.items():
                if kw in t:
                    site_targets.append((i, label))
                    used.add(i)
                    break
        targets = ([(i, "공급금액·납부조건") for i in price_idx[:max_price]]
                   + [(i, "타입별 평면도") for i in plan_idx[:max_plan]]
                   + site_targets[:max_site])
        if not targets:
            logger.info("공고문에서 금액표/평면도 페이지 미검출 — 캡처 생략")
            return []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for i, label in targets:
            if i >= doc.page_count:
                continue
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))  # 2배율 — 표 글자 가독
            # Windows: 핸들 열린 채 save하면 PermissionError — 먼저 닫고 경로에 저장
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp.close()
            pix.save(tmp.name)
            out.append({"path": tmp.name, "label": label, "page": i + 1})
        doc.close()
        logger.info(f"공고문 페이지 캡처 {len(out)}장: {[o['label'] for o in out]}")
        return out
    except Exception as e:
        logger.info(f"공고문 페이지 캡처 실패(무시): {e}")
        return []


# ── 분양 홈페이지 이미지 수집: 타입별 평면도·단지 배치도 (2026-07-29 사용자 지시) ──
# 배경: 공고문 PDF에 도면이 없는 단지가 대부분(판교TH212 433KB·한화포레나 231KB 실측 —
# 텍스트 전용)이라, 실질 도면 소스는 분양 공식 홈페이지(API HMPG_ADRES)다.
# best-effort: 사이트 구조가 단지마다 달라 실패해도 빈 리스트(발행엔 지장 없음).

# 페이지·이미지 분류 — 느슨하면 마케팅 배너를 배치도로 오인(더샵 트리센트 'PREMIUM 6' 실측
# 오탐, 2026-07-29). 페이지는 도면 전용 키워드만, 이미지도 같은 키워드를 재확인한다.
_HP_PLAN_PAT = re.compile(r"평면|평형|타입|세대안내|유니트|unit|floorplan|floor_?plan|type", re.I)
_HP_SITE_PAT = re.compile(r"배치도|단지배치|조감도|siteplan|site_?plan|birdview|masterplan", re.I)
_HP_IMG_SKIP = re.compile(r"logo|icon|btn|button|bullet|blank|spacer|banner|favicon|arrow|"
                          r"quick|top_|_bg|nav|menu|premium|popup|visual|intro|main_|event|"
                          r"prize|coupon|sns", re.I)
_HP_MIN_W, _HP_MIN_H = 620, 420   # 평면도/배치도는 대형 이미지 — 소형 UI 이미지 배제


def _hp_get(sess, url: str, **kw):
    """분양 홈페이지는 만료/사설 인증서가 흔함 — SSL 실패 시 1회 무검증 재시도."""
    try:
        return sess.get(url, timeout=_TIMEOUT, **kw)
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return sess.get(url, timeout=_TIMEOUT, verify=False, **kw)


def _hp_image_ok(content: bytes) -> bool:
    if len(content) < 30_000:          # 30KB 미만 = 아이콘·장식 이미지일 확률 높음
        return False
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(content))
        w, h = im.size
        return w >= _HP_MIN_W and h >= _HP_MIN_H
    except Exception:
        return False


def _hp_plan_like(content: bytes) -> bool:
    """평면도 도면 판별 — 인테리어 렌더 사진 오탐 차단(이천 휴먼빌 실측, 2026-07-29).
    도면은 밝은 배경(백색/크림) 비중이 높고 사진은 어둡다. 밝은 픽셀(L≥215) 20% 이상만 통과.
    ※배치도는 위성합성·어두운 조감 스타일이 흔해 이 필터를 적용하지 않는다."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(content)).convert("L").resize((64, 64))
        px = list(im.getdata())
        return sum(1 for v in px if v >= 215) / len(px) >= 0.20
    except Exception:
        return True  # 판별 불가면 통과(키워드 필터는 이미 거침)


def _hp_vision_verify(items: list[dict]) -> list[dict]:
    """Gemini Vision으로 수집 이미지 최종 분류 — 휴리스틱이 못 거르는 오탐 제거
    (이천 실측: 커뮤니티 시설 컷어웨이가 밝기 필터 통과, 인테리어 렌더 등).
    키 없음/호출 실패 시 해당 이미지는 보수적으로 유지(휴리스틱은 이미 통과)."""
    if not GOOGLE_API_KEY or not items:
        return items
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=GOOGLE_API_KEY)
    except Exception as e:
        logger.info(f"비전 검증 클라이언트 실패(스킵): {e.__class__.__name__}")
        return items
    out = []
    for c in items:
        try:
            with open(c["path"], "rb") as f:
                img = f.read()
            mime = "image/png" if c["path"].lower().endswith(".png") else "image/jpeg"
            resp = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=[gtypes.Part.from_bytes(data=img, mime_type=mime),
                          "이 이미지를 분류하라. 아파트 '세대 내부 평면도'(방·거실 구조 도면)=PLAN, "
                          "'단지 배치도/조감도/위치도'(단지 전체를 위에서 본 도면·지도)=SITE, "
                          "그 외(인테리어 사진, 커뮤니티/부대시설 안내, 광고 배너, 프리미엄 홍보)=OTHER. "
                          "답변은 PLAN, SITE, OTHER 중 한 단어만."])
            verdict = (resp.text or "").strip().upper()
            want = "PLAN" if "평면" in c["label"] else "SITE"
            if want in verdict:
                out.append(c)
            else:
                logger.info(f"홈페이지 도면 비전 검증 탈락({verdict[:12]} ≠ {want}): {c['label']}")
        except Exception as e:
            logger.info(f"비전 검증 호출 실패(유지): {e.__class__.__name__}")
            out.append(c)
    return out


def fetch_homepage_assets(detail: dict, max_plan: int = 4, max_site: int = 2) -> list[dict]:
    """분양 홈페이지에서 타입별 평면도·단지 배치도/조감도 이미지 수집.
    반환: [{path, label, page: 0, src: 'homepage', home: url}] — pdf_capture_key_pages와
    동일 형태(page=0은 '공고문 페이지 아님' 표시). 실패·미발견 시 []."""
    import hashlib
    import tempfile
    from urllib.parse import urljoin, urlparse

    home = (detail.get("HMPG_ADRES") or "").strip()
    if not home or "." not in home:
        logger.info("분양 홈페이지 주소(HMPG_ADRES) 없음 — 홈페이지 도면 수집 스킵")
        return []
    if not home.startswith("http"):
        home = "http://" + home
    try:
        from bs4 import BeautifulSoup
        sess = requests.Session()
        sess.headers.update(_BROWSER_HEADERS)
        r = _hp_get(sess, home)
        base = r.url  # 리다이렉트 최종 주소 기준
        host = urlparse(base).netloc.split(":")[0].removeprefix("www.")
        soup = BeautifulSoup(r.text, "html.parser")

        # 1) 서브페이지 후보: 링크 텍스트/URL이 평면·배치 키워드에 걸리는 같은 도메인 페이지
        plan_pages, site_pages = [], []
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"].strip())
            p = urlparse(href)
            if p.scheme not in ("http", "https") or host not in p.netloc:
                continue
            label_txt = f"{a.get_text(' ', strip=True)} {p.path}"
            if _HP_PLAN_PAT.search(label_txt) and href not in plan_pages:
                plan_pages.append(href)
            elif _HP_SITE_PAT.search(label_txt) and href not in site_pages:
                site_pages.append(href)
        # 단일 페이지형 사이트 대비 — 홈 자체도 스캔 대상
        scan = ([(home, "home")] + [(u, "plan") for u in plan_pages[:3]]
                + [(u, "site") for u in site_pages[:3]])

        # 2) 각 페이지의 <img> 수집 → 키워드/페이지 맥락으로 평면·단지 분류
        cand: list[tuple[str, str]] = []  # (img_url, kind)
        seen_urls = set()
        for page_url, kind in scan:
            try:
                ph = _hp_get(sess, page_url).text if page_url != home else r.text
            except Exception:
                continue
            psoup = BeautifulSoup(ph, "html.parser")
            for img in psoup.find_all("img"):
                src = (img.get("src") or img.get("data-src") or img.get("data-original") or "").strip()
                if not src or src.startswith("data:"):
                    continue
                iu = urljoin(page_url, src)
                if iu in seen_urls or _HP_IMG_SKIP.search(iu):
                    continue
                seen_urls.add(iu)
                ctx = f"{iu} {img.get('alt', '')}"
                # 이미지 자체 키워드 우선 — 페이지 맥락(kind)은 이미지가 무기명(img_01.jpg 등)일
                # 때만 보조로. 홈 스캔(kind='home')에서는 이미지 키워드 필수(정밀도 우선).
                if _HP_PLAN_PAT.search(ctx):
                    cand.append((iu, "plan"))
                elif _HP_SITE_PAT.search(ctx):
                    cand.append((iu, "site"))
                elif kind in ("plan", "site"):
                    cand.append((iu, kind))

        # 3) 다운로드·검증(대형 이미지만)·중복 제거 → 상한만큼 채택
        out: list[dict] = []
        hashes = set()
        n_plan = n_site = 0
        for iu, kind in cand:
            if n_plan >= max_plan and n_site >= max_site:
                break
            if (kind == "plan" and n_plan >= max_plan) or (kind == "site" and n_site >= max_site):
                continue
            try:
                ir = _hp_get(sess, iu, headers={"Referer": base})
                if not _hp_image_ok(ir.content):
                    continue
                if kind == "plan" and not _hp_plan_like(ir.content):
                    continue  # 어두운 사진(인테리어 렌더 등) — 평면도 아님
                h = hashlib.md5(ir.content).hexdigest()
                if h in hashes:
                    continue
                hashes.add(h)
                ext = ".png" if iu.lower().endswith(".png") else ".jpg"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                tmp.write(ir.content)
                tmp.close()
                if kind == "plan":
                    label, n_plan = "타입별 평면도", n_plan + 1
                else:
                    label = "단지 조감도" if re.search(r"조감|birdview", iu, re.I) else "단지 배치도"
                    n_site += 1
                out.append({"path": tmp.name, "label": label, "page": 0,
                            "src": "homepage", "home": base})
            except Exception:
                continue
        out = _hp_vision_verify(out)
        n_plan = sum(1 for c in out if "평면" in c["label"])
        n_site = len(out) - n_plan
        logger.info(f"분양 홈페이지 도면 수집(비전 검증 후): 평면 {n_plan}·단지 {n_site}장 "
                    f"(후보 {len(cand)}, 서브페이지 평면 {len(plan_pages)}·단지 {len(site_pages)}) — {base}")
        return out
    except Exception as e:
        logger.info(f"분양 홈페이지 도면 수집 실패(무시): {e.__class__.__name__}: {e}")
        return []


# ── 팩트 빌드 ────────────────────────────────────────────────────────────────

def _money(val) -> str:
    """LTTOT_TOP_AMOUNT(만원 단위) → '5억 2,000만 원' 표기."""
    try:
        n = int(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    eok, man = divmod(n, 10000)
    if eok and man:
        return f"{eok}억 {man:,}만 원"
    if eok:
        return f"{eok}억 원"
    return f"{man:,}만 원"


def build_facts(detail: dict, types: list[dict], pdf_excerpt: str = "") -> dict:
    """generate_deep_post의 facts(dict) — 공고 확정 팩트만 담는다."""
    g = detail.get
    schedule = {
        "모집공고일": g("RCRIT_PBLANC_DE", ""),
        "특별공급 접수": f"{g('SPSPLY_RCEPT_BGNDE', '')} ~ {g('SPSPLY_RCEPT_ENDDE', '')}",
        "1순위 접수": f"{g('GNRL_RNK1_CRSPAREA_RCPTDE', '')} (해당지역) / "
                    f"{g('GNRL_RNK1_ETC_AREA_RCPTDE', '')} (기타지역)",
        "2순위 접수": f"{g('GNRL_RNK2_CRSPAREA_RCPTDE', '')} (해당지역)",
        "당첨자 발표": g("PRZWNER_PRESNATN_DE", ""),
        "계약": f"{g('CNTRCT_CNCLS_BGNDE', '')} ~ {g('CNTRCT_CNCLS_ENDDE', '')}",
        "입주 예정": g("MVN_PREARNGE_YM", ""),
    }
    if detail.get("_remainder"):
        schedule = {
            "모집공고일": g("RCRIT_PBLANC_DE", ""),
            "접수": f"{g('SUBSCRPT_RCEPT_BGNDE', '') or g('RCEPT_BGNDE', '')} ~ "
                  f"{g('SUBSCRPT_RCEPT_ENDDE', '') or g('RCEPT_ENDDE', '')}",
            "당첨자 발표": g("PRZWNER_PRESNATN_DE", ""),
            "계약": f"{g('CNTRCT_CNCLS_BGNDE', '')} ~ {g('CNTRCT_CNCLS_ENDDE', '')}",
        }

    type_rows = []
    top_prices = []
    for t in types:
        price = _money(t.get("LTTOT_TOP_AMOUNT"))
        row = {
            "주택형": t.get("HOUSE_TY", ""),
            "공급면적": f"{t.get('SUPLY_AR', '')}㎡",
            "일반공급": t.get("SUPLY_HSHLDCO", ""),
            "특별공급": t.get("SPSPLY_HSHLDCO", ""),
            "최고분양가": price or "공고문 확인",
        }
        type_rows.append(row)
        try:
            top_prices.append(int(str(t.get("LTTOT_TOP_AMOUNT")).replace(",", "")))
        except (TypeError, ValueError):
            pass

    facts = {
        "단지명": g("HOUSE_NM", ""),
        "공급위치": g("HSSPLY_ADRES", ""),
        "공급지역": g("SUBSCRPT_AREA_CODE_NM", ""),
        "공고유형": "무순위/잔여세대(줍줍)" if detail.get("_remainder") else "APT 일반분양",
        "총공급세대수": g("TOT_SUPLY_HSHLDCO", ""),
        "시공사": g("CNSTRCT_ENTRPS_NM", ""),
        "문의처": g("MDHS_TELNO", ""),
        "일정": schedule,
        "주택형별 공급": type_rows,
        "규제": {
            "투기과열지구": g("SPECLT_RDN_EARTH_AT", ""),
            "조정대상지역": g("MDAT_TRGET_AREA_SECD", ""),
            "분양가상한제": g("PARCPRC_ULS_AT", ""),
            "정비사업": g("IMPRMN_BSNS_AT", ""),
            "공공주택지구": g("PUBLIC_HOUSE_EARTH_AT", ""),
            "생애최초 공급": g("LFE_FRST_SUPLY_AT", ""),
        },
        "청약홈 공고 URL": g("PBLANC_URL", ""),
    }
    if top_prices:
        top = max(top_prices)
        facts["필요현금 참고(최고분양가 기준)"] = {
            "최고분양가": _money(top),
            "계약금 10% 가정": _money(round(top * 0.1)),
            "계약금 20% 가정": _money(round(top * 0.2)),
            "주의": "실제 계약금 비율·중도금 대출 여부는 입주자모집공고문 기준(아래 발췌 참고)",
        }
    if pdf_excerpt:
        facts["모집공고문 발췌(납부조건·대출 관련 원문)"] = pdf_excerpt
    return facts


def build_key_stats(detail: dict, types: list[dict]) -> list:
    stats = []
    if detail.get("TOT_SUPLY_HSHLDCO"):
        stats.append({"label": "총 공급세대", "value": f"{detail['TOT_SUPLY_HSHLDCO']}세대"})
    rc = detail.get("GNRL_RNK1_CRSPAREA_RCPTDE") or detail.get("RCEPT_BGNDE", "")
    if rc:
        stats.append({"label": "청약 접수", "value": rc})
    prices = [t.get("LTTOT_TOP_AMOUNT") for t in types if t.get("LTTOT_TOP_AMOUNT")]
    if prices:
        try:
            stats.append({"label": "최고 분양가", "value": _money(max(int(str(p).replace(',', '')) for p in prices))})
        except ValueError:
            pass
    if detail.get("PRZWNER_PRESNATN_DE"):
        stats.append({"label": "당첨자 발표", "value": detail["PRZWNER_PRESNATN_DE"]})
    return stats[:4]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    notices = fetch_new_apt_notices() + fetch_new_remainder_notices()
    for n in notices[:10]:
        print(notice_key(n), "|", n.get("HOUSE_NM"), "|", n.get("SUBSCRPT_AREA_CODE_NM"),
              "|", n.get("RCRIT_PBLANC_DE"))
    if not notices:
        print("신규 공고 없음(또는 PUBLIC_DATA_KEY 미설정)")
