"""
본문 이미지 소싱 — 다층 쿼리 사다리 × 멀티 프로바이더 폴백 (2026-07-27 고도화)

쿼리 사다리(상위 티어 성공 시 중단):
  T1: 글 생성기가 준 이미지 키워드(한→영 변환, 기존 경로)
  T2: 제품/주제의 상위 카테고리 일반어(_T2_GENERALIZE 매핑 → 실패 시 Gemini 1콜)
  T3: 카테고리별 광의 기본어
프로바이더(각 티어 안에서 순차): Pexels(키 필요) → Wikimedia Commons → Openverse(둘 다 무키·CC).
관련성 필터(_OFFTOPIC_RE)는 전 티어·전 프로바이더에 유지 — 전부 탈락 시 억지로 쓰지 않고
다음 프로바이더/티어로 진행한다. 같은 글 안에서는 URL 중복 방지.
무키 프로바이더는 비영어 메타데이터가 흔해 3중 보강(2026-07-28 검증 라운드2):
  ①다국어 인물어 필터(_OFFTOPIC_I18N_RE) ②쿼리 내용어-메타데이터 일치 게이트(_meta_relevant)
  ③채택 직전 Gemini 비전 게이트(_vision_offtopic, 호출당 2콜 상한·실패 시 텍스트 필터 결과 유지).
image_keywords (content.py에서 생성된 7개 키워드) 사용 시 각 위치별 적합한 이미지 수집.
"""
import logging
import os
import re
import tempfile

import requests

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"
_WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
_OPENVERSE_API = "https://api.openverse.org/v1/images/"
# Wikimedia는 식별 가능한 UA를 요구(무UA/브라우저 위장 UA는 403 가능)
_PROVIDER_UA = "benefit-genie-blog-pipeline/1.0 (image sourcing; python-requests)"


def generate_dish_image(dish: str, api_key: str) -> str | None:
    """레시피 대표 이미지를 AI로 생성(실제 한국 가정식 사진 톤). 성공 시 로컬 PNG 경로, 실패 시 None.
    Pexels는 한식 사진이 빈약해 대표컷이 어색하므로, 같은 GOOGLE_API_KEY로 이미지를 생성한다.
    Imagen → Gemini 이미지생성 순으로 시도하고, 둘 다 실패하면 None(상위에서 Pexels/카드 폴백)."""
    if not dish or not api_key:
        return None
    prompt = (
        f"A realistic, appetizing top-down food photograph of Korean home-style dish '{dish}', "
        f"served on a plate on a clean wooden table, natural soft daylight, cozy home kitchen mood, "
        f"high detail, no text, no people, no watermark."
    )

    def _save_png(data) -> str:
        import base64
        raw = base64.b64decode(data) if isinstance(data, str) else data
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(raw)
        tmp.close()
        return tmp.name

    # 베네핏지니씨(coupang) 파이프라인에서 검증된 방식: gemini-3.1-flash-image, response_modalities=['IMAGE'].
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        for model in ("gemini-3.1-flash-image", "gemini-2.5-flash-image"):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=gtypes.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.parts:
                    if getattr(part, "thought", False):
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        path = _save_png(inline.data)
                        logger.info(f"대표 이미지 AI 생성 성공({model}): {dish} -> {path}")
                        return path
            except Exception as e:
                logger.info(f"Gemini 이미지({model}) 생성 실패: {e.__class__.__name__}: {str(e)[:90]}")
    except Exception as e:
        logger.warning(f"AI 이미지 생성 모듈 오류(폴백 진행): {e}")

    logger.warning(f"대표 이미지 AI 생성 실패 — Pexels/카드로 폴백: {dish}")
    return None

# 카테고리/키워드 → 영문 검색어 매핑
_KO_TO_EN: list[tuple[re.Pattern, str]] = [
    # ── 건강·의학 ──────────────────────────────────────────────────
    (re.compile(r"탈모|두피|모발"), "hair care healthy scalp shampoo herbal no people"),
    (re.compile(r"철분|빈혈|헤모글로빈|페리틴"), "iron rich food spinach lentils dark greens no people"),
    (re.compile(r"호르몬|에스트로겐|갑상선|안드로겐"), "herbal wellness tea hormone health food no people"),
    (re.compile(r"단백질|아미노산|케라틴"), "eggs nuts beans protein food ingredients no people"),
    (re.compile(r"비타민|영양소|미네랄|영양제"), "colorful fresh vegetables vitamins supplements no people"),
    (re.compile(r"다이어트|체중|비만|살빼"), "healthy meal prep salad vegetables weight loss no people"),
    (re.compile(r"혈당|혈압|혈류|혈관"), "fresh berries vegetables heart health food no people"),
    (re.compile(r"장|유산균|프로바이오틱|장내"), "yogurt fermented kimchi gut health food no people"),
    (re.compile(r"피부|콜라겐|항산화|기미"), "fresh berries antioxidant fruits beautiful skin no people"),
    (re.compile(r"면역|항체|염증"), "lemon ginger honey immune boost drink no people"),
    (re.compile(r"뇌|인지|기억력|치매"), "omega fish walnuts brain health food no people"),
    (re.compile(r"뼈|칼슘|골다공증|관절"), "dairy milk calcium rich food bones no people"),
    (re.compile(r"심장|심혈관|동맥경화"), "heart healthy food salmon berries omega no people"),
    (re.compile(r"눈|시력|루테인|안구"), "colorful carrots blueberries eye health food no people"),
    (re.compile(r"스트레스|피로|수면|불면"), "calm relaxing herbal tea sleep wellness no people"),
    (re.compile(r"식단|영양|건강식"), "healthy balanced meal colorful vegetables no people"),
    (re.compile(r"운동|근육|근력|헬스"), "fitness exercise healthy lifestyle workout no people"),
    # ── 살림/생활 ──────────────────────────────────────────────────
    (re.compile(r"욕실|화장실|샤워"), "clean bathroom interior aesthetic no people"),
    (re.compile(r"주방|부엌|싱크대"), "cozy kitchen counter still life aesthetic no people"),
    (re.compile(r"세탁기|빨래"), "laundry room aesthetic details no people"),
    (re.compile(r"청소|정리|루틴"), "home interior organization aesthetic minimalist no people"),
    (re.compile(r"곰팡이|습기"), "bathroom tiles clean detail still life"),
    (re.compile(r"요리|레시피|밥|식단|냉파"), "korean food table setting cozy aesthetic no people"),
    (re.compile(r"도시락|아침\s*메뉴"), "bento box lunch box still life cozy"),
    (re.compile(r"식비\s*절약"), "cozy study desk notebook coffee still life"),
    (re.compile(r"인테리어|꾸미|홈\s*데코"), "cozy home interior aesthetic minimalist no people"),
    (re.compile(r"수납|정리함|선반"), "organized storage shelves aesthetic details no people"),
    (re.compile(r"옷장|드레스룸"), "organized closet wardrobe aesthetic minimalist no people"),
    (re.compile(r"냉장고"), "organized refrigerator shelves inside close up no people"),
    (re.compile(r"베란다|발코니"), "balcony terrace cozy plants aesthetic no people"),
    (re.compile(r"무드등|조명"), "cozy bedroom mood lighting aesthetic no people"),
    (re.compile(r"절약|생활비|가계부"), "cozy study desk piggy bank still life"),
    (re.compile(r"전기세|난방비|냉방비"), "cozy home warm lighting detail"),
    (re.compile(r"에어컨"), "air conditioner clean minimalist white no people"),
    (re.compile(r"다이소"), "cozy home organizer aesthetic design no people"),
    (re.compile(r"이케아"), "ikea home organization shelves aesthetic no people"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner minimalist home no people"),
    (re.compile(r"공기청정기"), "home air purifier close up minimalist no people"),
    (re.compile(r"필터|교체"), "clean home appliance minimalist details"),
    (re.compile(r"신혼|살림"), "cozy new home living room aesthetic no people"),
    (re.compile(r"자취|1인\s*가구"), "cozy small apartment interior aesthetic no people"),
    (re.compile(r"혼수|결혼\s*준비"), "cozy bridal room decoration aesthetic details"),
]
_DEFAULT_QUERY = "cozy Korean home interior aesthetic no people"

# 살림/생활 블로그에 '뜬금없는' 스톡사진 제외용 (alt 텍스트 기준)
# 달러사진, 인물, 자동차, 방독면, 스마트폰, 보석 등 뜬금없는 사물 차단
_OFFTOPIC_RE = re.compile(
    r"\b(money|dollar|cash|currency|coin|finance|financial|banking|invest|investment|"
    r"stock\s*market|business|office|meeting|conference|corporate|suit|handshake|"
    r"graph|chart|mountain|beach|forest|ocean|sunset|sky|desert|wildlife|animal|"
    r"abstract|texture|pattern|gradient|wedding\s*dress|model\s*pose|"
    r"person|people|man|woman|model|face|hand|finger|arm|leg|body|portrait|couple|family|"
    r"human|girl|boy|guy|lady|male|female|"
    # 유저 피드백 반영: 차량용 필터, 방독면, 스마트폰, 반지/액세서리 등 원천 배제
    r"car|auto|vehicle|automotive|engine|gas\s*mask|respirator|mask|phone|smartphone|mobile|ring|jewelry|necklace|bracelet|earring)\b",
    re.I,
)

# ── 무키 프로바이더(Wikimedia/Openverse) 비영어 메타데이터 방어 3종 (2026-07-28) ──
# 검증 실측: 영어 전용 _OFFTOPIC_RE가 이탈리아어 제목 'Frans hals, ritratto di donna, 1634'
# (여인 초상 회화)를 통과시킴. 주요 언어의 인물·초상 어휘를 추가 차단한다.
_OFFTOPIC_I18N_RE = re.compile(
    r"\b(?:"
    # 초상·인물화·셀피 (it/es/pt/fr/de/nl/pl/cs/ru)
    r"ritratt\w*|retrat\w*|portr[aeä]t\w*|portret\w*|autoportret\w*|selfie|"
    # 여성/남성/사람 — 로망스
    r"donna|donne|uomo|uomini|signor[ae]|ragazz[aio]|bambin[aio]|"
    r"femme|homme|fille|gar[cç]on|enfant|madame|monsieur|"
    r"mujer(?:es)?|hombre|se[ñn]or[a]?|chic[ao]s?|ni[ñn][ao]s?|"
    r"mulher|homem|menin[ao]|senhora|crian[cç]a|"
    # 게르만·북유럽
    r"frau|frauen|mann|m[aä]nner|m[aä]dchen|junge[n]?|kinder|mensch(?:en)?|"
    r"vrouw|meisje|jongen|kvinn\w*|kvinde|flicka|pojke|pige|dreng|"
    # 슬라브(라틴 표기)
    r"kobiet\w*|m[eę][zż]czyzn\w*|dziewczyn\w*|ch[lł]opiec|[zž]ena|[zž]eny|"
    # 러시아어(키릴)
    r"портрет\w*|женщин\w*|мужчин\w*|девушк\w*|девочк\w*|мальчик\w*|человек|люди|"
    # 누드
    r"nudo|desnud[ao]|akt"
    r")\b",
    re.IGNORECASE,
)

# 쿼리-메타데이터 관련성 게이트용 불용어 — 장면·톤 수식어는 내용어로 치지 않는다.
_QUERY_STOPWORDS = frozenset({
    "the", "and", "with", "for", "from", "over", "under", "near", "into",
    "no", "not", "people", "person", "aesthetic", "aesthetics", "style",
    "photo", "photograph", "photography", "image", "picture", "closeup", "close",
    "still", "life", "flat", "lay", "background", "view", "shot", "scene",
    "cozy", "minimal", "minimalist", "modern", "clean", "beautiful", "neatly",
    "arranged", "organized", "detail", "details", "empty", "natural", "soft", "warm",
})


def _norm_meta(s: str) -> str:
    """파일명형 메타데이터 정규화 — '_'·'-'·'/'는 \\w에 속해 \\b 단어 경계 매칭을 막으므로
    (예: 'ritratto_di_donna') 공백으로 치환한다."""
    return re.sub(r"[_\-/]+", " ", s or "")


def _is_offtopic_meta(text: str) -> bool:
    """영어 오프토픽 필터 + 다국어 인물어 필터 통합 판정(전 프로바이더 공용)."""
    t = _norm_meta(text)
    return bool(_OFFTOPIC_RE.search(t) or _OFFTOPIC_I18N_RE.search(t))


def _query_stems(query: str) -> list[str]:
    """쿼리에서 내용어 어간(앞 5자) 추출 — 불용어(장면·톤 수식어) 제외."""
    return [t[:5] for t in re.findall(r"[a-z]{3,}", (query or "").lower())
            if t not in _QUERY_STOPWORDS]


def _meta_relevant(query: str, meta_text: str) -> bool:
    """무키 프로바이더 전용 관련성 게이트 — Wikimedia 전문(full-text)검색이 쿼리와 무관한
    파일(2026-07-28 검증 실측: 'battery charging' 검색에 정당 당사 건물 사진)을 돌려주는
    노이즈 차단. 쿼리 내용어 어간이 제목·설명·카테고리에 하나도 없으면 채택하지 않는다."""
    stems = _query_stems(query)
    if not stems:  # 내용어가 없는 광의 쿼리 — 오프토픽 필터에만 위임
        return True
    t = _norm_meta(meta_text).lower()
    return any(s in t for s in stems)


def _vision_offtopic(img_url: str, query: str) -> bool | None:
    """무키 프로바이더 채택 직전 Gemini 비전 1콜 게이트(2026-07-28) — 텍스트 필터가 못 거른
    비영어·무설명 메타데이터의 인물/무관 사진 최종 방어선(tech_image._person_dominant류).
    True=거부, False=통과, None=판정 불가(키 없음·API 실패 — 텍스트 필터를 이미 통과했으므로
    기존 동작대로 채택 유지). 새 API 의존 추가 없음(기존 google-genai 재사용)."""
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")).strip()
    if not api_key:
        return None
    try:
        r = requests.get(img_url, headers={"User-Agent": _PROVIDER_UA}, timeout=10)
        r.raise_for_status()
        data = r.content
        if not (4_000 <= len(data) <= 8_000_000):
            return None
        mime = (r.headers.get("Content-Type") or "").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        from google import genai
        from google.genai import types as gtypes
        # timeout 필수(2026-07-28 리뷰): 기본값은 무제한 대기 — 쿼리 사다리×프로바이더 루프
        # 안에서 1콜이라도 행이면 GH Actions 크론 전체가 멈춤
        client = genai.Client(api_key=api_key,
                              http_options=gtypes.HttpOptions(timeout=30_000))
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[gtypes.Part.from_bytes(data=data, mime_type=mime),
                      f"블로그 이미지 후보 검증. 검색 주제: '{query}'. "
                      "①사람(얼굴·초상·인물화·군중 포함)이 주요 피사체이거나 "
                      "②주제와 명백히 무관한 사진이면 NO, "
                      "주제에 어울리는 사물·장면 사진이면 YES. 대답은 YES 또는 NO 한 단어만."])
        ans = (getattr(resp, "text", "") or "").strip().upper()
        if ans.startswith("NO"):
            logger.info(f"비전 게이트: 인물/무관 판정으로 제외 (query={query!r})")
            return True
        if ans.startswith("YES"):
            return False
        return None
    except Exception as e:
        logger.info(f"비전 게이트 생략({e.__class__.__name__}: {str(e)[:50]})")
        return None


def _keyword_to_en(keyword: str) -> str:
    """한국어 키워드를 Pexels 검색용 영어 쿼리로 변환"""
    # 영어가 이미 포함된 경우 그대로 사용
    query = keyword
    if not re.search(r"[a-zA-Z]{3,}", keyword):
        found = False
        for pattern, eng in _KO_TO_EN:
            if pattern.search(keyword):
                query = eng
                found = True
                break
        if not found:
            query = _DEFAULT_QUERY

    # 모든 쿼리에 대해 people-free 필터링 및 감성 톤 강화
    if "no people" not in query.lower() and "people" not in query.lower():
        query = f"{query} no people"
    if "aesthetic" not in query.lower():
        query = f"{query} aesthetic"

    # 레시피/요리 관련 영어 키워드에 대해 korean 묵시적 접두사 부여 (양식/스톡 사진 방지)
    food_kws = ["food", "dish", "cooking", "meal", "recipe", "stew", "soup", "vegetable", "kitchen"]
    if any(fw in query.lower() for fw in food_kws) and "korean" not in query.lower():
        query = f"korean {query}"

    return query


def _fetch_one_image(query: str, api_key: str, exclude_ids: set | None = None,
                     exclude_urls: set | None = None) -> dict | None:
    """단일 쿼리로 이미지 1장 수집 (중복 제외 + 관련성 필터로 뜬금없는 사진 제외)"""
    try:
        r = requests.get(
            _PEXELS_SEARCH,
            headers={"Authorization": api_key},
            params={
                "query": query,
                "per_page": 12,  # 후보 넉넉히 받아 필터링
                "orientation": "landscape",
                "size": "medium",
            },
            timeout=10,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        for p in photos:
            if exclude_ids and p["id"] in exclude_ids:
                continue
            cand = {
                "url": p["src"]["large"],
                "alt_text": query,
                "photographer": p.get("photographer", ""),
                "pexels_id": p["id"],
                "source": "pexels",
            }
            if exclude_urls and cand["url"] in exclude_urls:
                continue
            alt = p.get("alt") or ""
            if _is_offtopic_meta(alt):
                logger.info(f"관련성 필터: 뜬금없는 사진 제외 (alt={alt[:45]!r}, query={query!r})")
                continue
            return cand
        # 후보가 전부 off-topic(사람 노출 등)이면 억지로 첫 후보를 쓰지 않고 None 반환
        return None
    except Exception as e:
        logger.warning(f"Pexels 단일 수집 실패 (query={query!r}): {e}")
    return None


def _strip_html_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").strip()


def _fetch_wikimedia(query: str, exclude_urls: set | None = None) -> dict | None:
    """Wikimedia Commons 검색(API키 불요, CC/퍼블릭도메인 위주).
    제목+설명+카테고리를 오프토픽(영어+다국어)·관련성·비전 3중 게이트로 검사(2026-07-28) —
    전부 탈락 시 None(다음 프로바이더로)."""
    try:
        r = requests.get(
            _WIKIMEDIA_API,
            headers={"User-Agent": _PROVIDER_UA},
            params={
                "action": "query", "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}",
                "gsrnamespace": 6, "gsrlimit": 12,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 1200,
            },
            timeout=10,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        vision_budget = 2  # 채택 직전 비전 게이트 상한(비용·지연 바운드)
        for page in sorted(pages.values(), key=lambda p: p.get("index", 999)):
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url") or ""
            if not url.startswith("http"):
                continue
            if info.get("mime", "") not in ("image/jpeg", "image/png"):
                continue
            if (info.get("width") or 0) < 500:  # 아이콘·로고 배제
                continue
            if exclude_urls and url in exclude_urls:
                continue
            meta = info.get("extmetadata") or {}
            desc = _strip_html_tags((meta.get("ImageDescription") or {}).get("value", ""))
            cats = _strip_html_tags((meta.get("Categories") or {}).get("value", ""))
            title = re.sub(r"^File:|\.[A-Za-z]{3,4}$", "", page.get("title", ""))
            meta_text = f"{title} {desc} {cats}"
            if _is_offtopic_meta(meta_text):
                logger.info(f"관련성 필터(wikimedia): 제외 (title={title[:40]!r}, query={query!r})")
                continue
            # 전문검색 노이즈 차단: 쿼리 내용어가 메타데이터에 전무하면 무관 파일로 간주
            if not _meta_relevant(query, meta_text):
                logger.info(f"관련성 게이트(wikimedia): 쿼리 어간 불일치로 제외 "
                            f"(title={title[:40]!r}, query={query!r})")
                continue
            if vision_budget > 0:
                vision_budget -= 1
                if _vision_offtopic(url, query):
                    continue
            artist = _strip_html_tags((meta.get("Artist") or {}).get("value", ""))[:60]
            return {"url": url, "alt_text": query, "photographer": artist,
                    "source": "wikimedia"}
        return None
    except Exception as e:
        logger.warning(f"Wikimedia 수집 실패 (query={query!r}): {e}")
    return None


def _fetch_openverse(query: str, exclude_urls: set | None = None) -> dict | None:
    """Openverse 검색(API키 불요, CC 라이선스 모음).
    제목+태그를 오프토픽(영어+다국어)·관련성·비전 3중 게이트로 검사(2026-07-28)."""
    try:
        r = requests.get(
            _OPENVERSE_API,
            headers={"User-Agent": _PROVIDER_UA},
            params={"q": query, "page_size": 12, "mature": "false"},
            timeout=10,
        )
        r.raise_for_status()
        vision_budget = 2  # 채택 직전 비전 게이트 상한(비용·지연 바운드)
        for it in r.json().get("results", []):
            url = (it.get("url") or "").strip()
            if not url.startswith("http") or url.lower().endswith((".svg", ".gif")):
                continue
            if (it.get("width") or 600) < 500:  # width 미제공이면 통과, 저해상만 배제
                continue
            if exclude_urls and url in exclude_urls:
                continue
            tags = " ".join((t or {}).get("name", "") for t in (it.get("tags") or [])[:12])
            alt_check = f"{it.get('title', '')} {tags}"
            if _is_offtopic_meta(alt_check):
                logger.info(f"관련성 필터(openverse): 제외 (title={str(it.get('title'))[:40]!r}, query={query!r})")
                continue
            if not _meta_relevant(query, alt_check):
                logger.info(f"관련성 게이트(openverse): 쿼리 어간 불일치로 제외 "
                            f"(title={str(it.get('title'))[:40]!r}, query={query!r})")
                continue
            if vision_budget > 0:
                vision_budget -= 1
                if _vision_offtopic(url, query):
                    continue
            return {"url": url, "alt_text": query,
                    "photographer": (it.get("creator") or "")[:60], "source": "openverse"}
        return None
    except Exception as e:
        logger.warning(f"Openverse 수집 실패 (query={query!r}): {e}")
    return None


# Pexels 전용 무드 접미어 — Wikimedia/Openverse는 전문(full-text) 검색이라 이 접미어가
# 붙으면 0건이 되므로(자가 테스트 실측) 무키 프로바이더엔 제거한 원형 쿼리를 쓴다.
_QUERY_SUFFIX_RE = re.compile(r"\b(no people|aesthetic)\b", re.I)


def _bare_query(query: str) -> str:
    return re.sub(r"\s{2,}", " ", _QUERY_SUFFIX_RE.sub(" ", query)).strip()


def _fetch_any_provider(query: str, api_key: str, used_ids: set, used_urls: set) -> dict | None:
    """한 쿼리를 프로바이더 순차 폴백으로 시도: Pexels(키 있을 때만) → Wikimedia → Openverse.
    각 프로바이더 실패·전부 필터 탈락은 조용히 다음으로."""
    if api_key:
        img = _fetch_one_image(query, api_key, exclude_ids=used_ids, exclude_urls=used_urls)
        if img:
            return img
    bare = _bare_query(query)
    for fetch in (_fetch_wikimedia, _fetch_openverse):
        img = fetch(bare, exclude_urls=used_urls)
        if img:
            return img
    return None


# ── T2: 상위 카테고리 일반어 매핑 (브랜드·모델 → 일반 사물/장면) ─────────────
_T2_GENERALIZE: list[tuple[re.Pattern, str]] = [
    # 테크·가전 (※_OFFTOPIC_RE는 전 티어 유지 — phone 등은 alt 필터에서 걸러질 수 있음)
    (re.compile(r"폴더블|폴드|플립"), "foldable smartphone on desk"),
    (re.compile(r"키보드"), "mechanical keyboard closeup"),
    (re.compile(r"마우스"), "computer mouse on desk"),
    (re.compile(r"보조배터리|배터리|충전기"), "battery charging closeup"),
    (re.compile(r"노트북|맥북|랩탑"), "laptop computer on wooden desk"),
    (re.compile(r"모니터|디스플레이"), "computer monitor on desk"),
    (re.compile(r"이어폰|에어팟|버즈|헤드폰|헤드셋"), "wireless earbuds closeup"),
    (re.compile(r"스마트워치|워치"), "smartwatch on table closeup"),
    (re.compile(r"태블릿|아이패드"), "tablet device on desk"),
    (re.compile(r"로봇청소기"), "robot vacuum cleaner on floor"),
    (re.compile(r"청소기"), "vacuum cleaner in home"),
    (re.compile(r"에어프라이어|오븐"), "kitchen oven appliance closeup"),
    (re.compile(r"그래픽카드|GPU|RTX"), "computer graphics card closeup"),
    (re.compile(r"데스크탑|컴퓨터|PC"), "desktop computer setup on desk"),
    (re.compile(r"인공지능|챗봇|챗GPT|AI"), "circuit board technology closeup"),
    (re.compile(r"카메라"), "digital camera on table"),
    (re.compile(r"스피커"), "bluetooth speaker on shelf"),
    # 생활·살림 일반화
    (re.compile(r"수건|타월"), "folded towels neatly stacked"),
    (re.compile(r"이불|침구|매트리스"), "cozy bedding neatly arranged"),
    (re.compile(r"커튼|블라인드"), "window curtains natural light"),
    (re.compile(r"세제|섬유유연제|청소용품"), "cleaning supplies bottles"),
    (re.compile(r"그릇|접시|식기"), "ceramic dishes tableware stacked"),
    (re.compile(r"커피|원두"), "coffee cup on wooden table"),
    (re.compile(r"녹차|홍차|허브티"), "herbal tea cup still life"),
    (re.compile(r"화분|식물|플랜테리어"), "indoor house plant pot"),
    (re.compile(r"욕조|샤워기"), "clean bathroom shower detail"),
    (re.compile(r"수납함|바구니|정리함"), "storage baskets organized shelf"),
    # 건강 일반화
    (re.compile(r"영양제|비타민|유산균|오메가"), "vitamin supplement bottles closeup"),
    (re.compile(r"샐러드|채소|과일"), "fresh vegetables and fruits"),
    (re.compile(r"요가|스트레칭"), "yoga mat home fitness"),
]


def _generalize_kw(keyword: str) -> str:
    """T2: 키워드를 상위 카테고리 일반어(영문)로. 매핑 실패 시 빈 문자열."""
    if not keyword:
        return ""
    for pat, eng in _T2_GENERALIZE:
        if pat.search(keyword):
            return eng
    return ""


def _llm_generic_query(keyword: str) -> str:
    """T2 매핑 실패 시 기존 Gemini 의존성(google-genai)으로 상위 카테고리 일반어 1콜 추출.
    GOOGLE_API_KEY 없거나 실패 시 빈 문자열(다음 티어로) — 새 API 의존 추가 없음."""
    kw = (keyword or "").strip()
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")).strip()
    if not kw or not api_key:
        return ""
    try:
        from google import genai
        from google.genai import types as gtypes
        # timeout 필수 — _vision_offtopic과 동일 사유(크론 행 방지)
        client = genai.Client(api_key=api_key,
                              http_options=gtypes.HttpOptions(timeout=30_000))
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=(
                "Convert this Korean blog image keyword into a generic English stock-photo "
                "search query (2-5 words). Use the broader product/scene category, "
                "no brand or model names, objects only, no people. "
                f"Keyword: {kw}\nAnswer with the query only."),
        )
        lines = [l.strip().strip('"\'') for l in (getattr(resp, "text", "") or "").splitlines()
                 if l.strip()]
        q = lines[0] if lines else ""
        if q and re.fullmatch(r"[A-Za-z][A-Za-z \-]{2,60}", q) and 1 <= len(q.split()) <= 6:
            return q.lower()
    except Exception as e:
        logger.info(f"LLM 일반어 추출 실패(무시): {str(e)[:60]}")
    return ""


# ── T3: 카테고리별 광의 기본어 ───────────────────────────────────────────
_T3_BROAD = {
    "신혼살림기초": "cozy home living room still life",
    "청소정리": "tidy organized home shelves",
    "요리식비": "korean home meal on table",
    "절약재테크": "notebook and pen on desk still life",
    "인테리어": "minimal cozy home interior",
    "쇼핑정보": "home goods flat lay",
    "건강": "fresh healthy food ingredients",
}
_T3_FALLBACK = "minimal still life objects on wooden table"


def _t1_mappable(raw_q: str) -> bool:
    """T1에서 쓸 수 있는 키워드인지 — 영어 포함 또는 _KO_TO_EN 실매핑일 때만.
    미매칭 한국어는 _keyword_to_en이 _DEFAULT_QUERY(무관 인테리어)로 강제하던 구조적
    맹점이 있어(2026-07-27), T1을 건너뛰고 T2 일반어/T3 광의어가 담당하게 한다."""
    if not raw_q:
        return False
    if re.search(r"[a-zA-Z]{3,}", raw_q):
        return True
    return any(pattern.search(raw_q) for pattern, _eng in _KO_TO_EN)


def _source_one_image(img_kw: str, base_keyword: str, category: str, api_key: str,
                      used_ids: set, used_urls: set) -> dict | None:
    """이미지 1장을 사다리(T1→T2→T3) × 프로바이더 폴백으로 소싱.
    상위 티어 성공 시 즉시 반환. 전부 실패 시 None(호출부 폴백)."""
    tried: set[str] = set()

    def _attempt(raw_q: str, tier: str) -> dict | None:
        if not raw_q or not raw_q.strip():
            return None
        q = _keyword_to_en(raw_q)
        if q in tried:
            return None
        tried.add(q)
        img = _fetch_any_provider(q, api_key, used_ids, used_urls)
        if img:
            logger.info(f"이미지 소싱 성공 [{tier}/{img.get('source', '?')}] query={q!r}")
        return img

    # T1: 생성기 키워드(기존 경로) + 원 keyword 폴백(기존 동작 보존)
    if _t1_mappable(img_kw):
        img = _attempt(img_kw, "T1")
        if img:
            return img
    if base_keyword and base_keyword != img_kw and _t1_mappable(base_keyword):
        img = _attempt(base_keyword, "T1")
        if img:
            return img
    # T2: 상위 카테고리 일반어(매핑 테이블 → LLM 1콜)
    for src in (img_kw, base_keyword):
        img = _attempt(_generalize_kw(src), "T2")
        if img:
            return img
    img = _attempt(_llm_generic_query(img_kw or base_keyword), "T2-llm")
    if img:
        return img
    # T3: 카테고리 광의 기본어
    img = _attempt(_T3_BROAD.get(category, ""), "T3")
    if img:
        return img
    return _attempt(_T3_FALLBACK, "T3")


def get_post_images(
    keyword: str,
    api_key: str,
    count: int = 7,
    category: str = "",
    image_keywords: list[str] | None = None,
) -> list[dict]:
    """
    이미지 수집 — 다층 사다리(T1→T2→T3) × 멀티 프로바이더(Pexels→Wikimedia→Openverse).
    image_keywords (content.py에서 생성된 7개)가 있으면 각 키워드별로 1장씩 수집.
    없으면 기존 방식(키워드 → 영어 변환, Pexels 벌크)으로 count장 수집 후 부족분 사다리 폴백.
    api_key(Pexels)가 없어도 무키 프로바이더(Wikimedia/Openverse)로 계속 시도한다.
    """
    if not api_key:
        logger.warning("PEXELS_API_KEY 없음 — 무키 프로바이더(Wikimedia/Openverse)로만 시도")

    # image_keywords가 있으면 각 위치별 맞춤 이미지 수집
    if image_keywords and len(image_keywords) >= 1:
        results = []
        used_ids: set = set()
        used_urls: set = set()
        for img_kw in image_keywords[:count]:
            img = _source_one_image(img_kw, keyword, category, api_key, used_ids, used_urls)
            if not img:
                logger.info(f"이미지 소싱 실패(전 티어·프로바이더 탈락): {img_kw!r}")
                continue
            if img.get("pexels_id"):
                used_ids.add(img["pexels_id"])
            used_urls.add(img["url"])
            img["alt_text"] = img_kw  # 원본 키워드를 alt_text로 보존
            results.append(img)
        logger.info(f"이미지 {len(results)}개 수집 (image_keywords {len(image_keywords)}개, "
                    f"사다리 T1→T3 × Pexels→Wikimedia→Openverse)")
        return results

    # 기존 방식: 단일 쿼리로 count장 수집
    search_keyword = keyword
    if category:
        cat_hints = {
            "신혼살림기초": "newlywed home",
            "청소정리": "cleaning organization",
            "요리식비": "cooking food",
            "절약재테크": "budget saving",
            "인테리어": "interior decor",
            "쇼핑정보": "home goods",
        }
        if category in cat_hints:
            search_keyword = f"{keyword} {cat_hints[category]}"

    query = _keyword_to_en(search_keyword)
    results = []
    used_ids: set = set()
    used_urls: set = set()
    if api_key:
        try:
            r = requests.get(
                _PEXELS_SEARCH,
                headers={"Authorization": api_key},
                params={
                    "query": query,
                    "per_page": count + 3,
                    "orientation": "landscape",
                    "size": "medium",
                },
                timeout=10,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            for p in photos:
                if len(results) >= count:
                    break
                if p["id"] in used_ids:
                    continue
                # 레거시 경로도 오프토픽 필터 적용 — image_keywords 경로와의 비대칭 해소(2026-07-28)
                alt = p.get("alt") or ""
                if _is_offtopic_meta(alt):
                    logger.info(f"관련성 필터(레거시): 제외 (alt={alt[:45]!r})")
                    continue
                used_ids.add(p["id"])
                used_urls.add(p["src"]["large"])
                results.append({
                    "url": p["src"]["large"],
                    "alt_text": f"{keyword} 관련 이미지",
                    "photographer": p.get("photographer", ""),
                    "pexels_id": p["id"],
                    "source": "pexels",
                })
            logger.info(f"Pexels 이미지 {len(results)}개 수집 (query={query!r})")
        except Exception as e:
            logger.warning(f"Pexels 수집 실패: {e}")

    # 결과 0장이면 사다리(T2·T3 포함 + 무키 프로바이더)로 폴백해 count장까지 시도
    if not results:
        for _ in range(count):
            img = _source_one_image(search_keyword, keyword, category, api_key,
                                    used_ids, used_urls)
            if not img:
                break
            if img.get("pexels_id"):
                used_ids.add(img["pexels_id"])
            used_urls.add(img["url"])
            img["alt_text"] = f"{keyword} 관련 이미지"
            results.append(img)
        if results:
            logger.info(f"레거시 경로 사다리 폴백으로 {len(results)}개 수집")
    return results


def fetch_image_urls(keyword: str, count: int = 4, api_key: str = "") -> list[str]:
    """기존 인터페이스 호환용 래퍼"""
    images = get_post_images(keyword=keyword, api_key=api_key, count=count)
    return [img["url"] for img in images]


def generate_recipe_step_image(
    dish: str,
    scene_desc: str,
    step_desc: str,
    api_key: str,
    step_index: int = 0,
) -> str | None:
    """레시피 단계별 AI 이미지 생성.
    scene_desc: 모든 이미지에 공통으로 적용되는 주방 배경 묘사 (일관성 anchor).
    step_desc: 이 단계에서 보여줄 구체적인 조리 장면 묘사.
    성공 시 로컬 PNG 경로, 실패 시 None."""
    if not api_key or not step_desc:
        return None

    # scene_desc가 없으면 기본 한국 가정식 주방 묘사 사용
    if not scene_desc:
        scene_desc = (
            "Cozy Korean home kitchen with cream-colored tile countertop. "
            "Stainless steel frying pan on gas stove, wooden cutting board, "
            "natural soft window light from the left side."
        )

    is_final = step_index == 0
    if is_final:
        prompt = (
            f"{scene_desc} "
            f"Beautiful finished Korean home-cooked dish '{dish}': {step_desc} "
            f"Plated elegantly on white ceramic dish, garnished, appetizing and photorealistic. "
            f"No people, no text, no watermarks. Top-down or 45-degree food photography angle."
        )
    else:
        prompt = (
            f"{scene_desc} "
            f"Cooking step {step_index} for '{dish}': {step_desc} "
            f"Show the key action of this step clearly. Same kitchen and cookware as the scene description. "
            f"Photorealistic food photography, no people, no text, no watermarks. "
            f"45-degree overhead angle, warm natural lighting."
        )

    def _save_png(data) -> str:
        import base64
        raw = base64.b64decode(data) if isinstance(data, str) else data
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_step{step_index}.png")
        tmp.write(raw)
        tmp.close()
        return tmp.name

    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        for model in ("gemini-3.1-flash-image", "gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=gtypes.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.parts:
                    if getattr(part, "thought", False):
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        path = _save_png(inline.data)
                        label = "완성" if is_final else f"단계{step_index}"
                        logger.info(f"레시피 {label} 이미지 생성 성공({model}): {path}")
                        return path
            except Exception as e:
                logger.info(f"레시피 이미지({model}) 실패: {e.__class__.__name__}: {str(e)[:80]}")
    except Exception as e:
        logger.warning(f"레시피 이미지 생성 모듈 오류: {e}")

    logger.warning(f"레시피 단계{step_index} 이미지 생성 실패: {dish}")
    return None


def generate_health_infographic(title: str, subheadings: list[str], api_key: str) -> str | None:
    """건강 포스팅 요약 인포그래픽 AI 생성 (Gemini 이미지 생성 API).
    subheadings: 섹션 제목 목록 (최대 5개). 성공 시 로컬 PNG 경로, 실패 시 None."""
    if not api_key or not title:
        return None

    n = min(len(subheadings), 5)
    if n == 0:
        return None

    points = " / ".join([f"{i+1}. {sh}" for i, sh in enumerate(subheadings[:n])])
    prompt = (
        f"Create a vibrant Korean health infographic. "
        f"Main title in Korean: '{title}'. "
        f"Show exactly {n} health benefit sections with icons and Korean labels: {points}. "
        f"Design: light pastel background, {n} colorful numbered circular badges, "
        f"Korean text labels inside each badge, clean magazine-style layout, "
        f"no watermarks, no English brand logos. "
        f"Style: similar to Korean health blog summary card with numbered sections 1 to {n}."
    )

    def _save_png(data) -> str:
        import base64
        raw = base64.b64decode(data) if isinstance(data, str) else data
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(raw)
        tmp.close()
        return tmp.name

    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        for model in ("gemini-2.0-flash-preview-image-generation", "gemini-3.1-flash-image", "gemini-2.5-flash-image"):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt],
                    config=gtypes.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.parts:
                    if getattr(part, "thought", False):
                        continue
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        path = _save_png(inline.data)
                        logger.info(f"인포그래픽 AI 생성 성공({model}): {title[:30]} → {path}")
                        return path
            except Exception as e:
                logger.info(f"인포그래픽 생성 실패({model}): {e.__class__.__name__}: {str(e)[:90]}")
    except Exception as e:
        logger.warning(f"인포그래픽 생성 모듈 오류: {e}")

    logger.warning(f"인포그래픽 AI 생성 실패 — PIL 폴백 없음: {title[:30]}")
    return None
