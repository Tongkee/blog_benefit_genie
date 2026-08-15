"""
본문 이미지 마커([사진N]) 배치 — info/gov 공용(중복 제거).

순서(=images 리스트 순서와 일치): 헤더[사진1] · 일러스트[사진2] · 개념카드[사진3].
poster는 img_idx=마커번호-1로 매핑([naver_blog] L914)하므로 마커 번호는 실제
images 리스트 인덱스와 정확히 일치해야 한다(누락 시 헤더 고아화).

- 일러스트: 1번째 [구분선](첫 소제목) 앞 = 도입/요약 뒤(엔게이지먼트 조기 노출).
- 개념카드: 2번째 [구분선](둘째 소제목) 앞 = 첫 섹션 뒤. 폴백 [표삽입] 뒤.
- 앵커 없으면 해당 이미지는 스킵(플래그로 반환 → 호출측이 images에서 제외).

★2026-07-07: 본문 이미지가 '앞 산문 문단의 끝'에 앵커되면 poster가 랩된 긴 문단
  중간에 캐럿을 놓아 문장을 두 동강 냈다(보험 라이브 '거예요'·'진단' 실사고). →
  각 본문 이미지가 '어느 소제목 바로 앞'에 들어가야 하는지를 함께 반환한다. poster는
  짧아서 랩되지 않는 소제목 단락을 클릭→Home으로 삽입해 안정적으로 소제목 위에 놓는다.
"""
import re


def _subheading_after(b: str, div_pos: int) -> str:
    """[구분선] 위치(div_pos) 바로 다음의 소제목 텍스트 한 줄을 반환."""
    tail = b[div_pos:].split("\n")
    for ln in tail[1:]:  # tail[0] == "[구분선]"
        s = ln.strip()
        if s and not s.startswith("["):
            return s
    return ""


def arrange_body_image_markers(body: str, has_illust: bool, has_concept: bool):
    """반환 (new_body, placed_illust, placed_concept, illust_sub, concept_sub).
    헤더[사진1]은 항상 최상단. 나머지는 앵커 있을 때만 배치하고 번호를 순차 부여.
    illust_sub/concept_sub = 그 이미지가 '바로 앞'에 삽입될 소제목 텍스트('' 가능=폴백)."""
    b = re.sub(r"^[ \t]*\[사진\d+\]\s*$\n?", "", body, flags=re.MULTILINE)
    b = re.sub(r"\[사진\d+\]", "", b)
    divs = [m.start() for m in re.finditer(r"^\[구분선\]", b, flags=re.MULTILINE)]

    place_illust = bool(has_illust and len(divs) >= 1)
    place_concept = bool(has_concept and (len(divs) >= 2 or "[표삽입]" in b))

    n = 2  # 헤더=1
    illust_marker = concept_marker = None
    illust_sub = concept_sub = ""
    if place_illust:
        illust_marker = f"[사진{n}]"
        illust_sub = _subheading_after(b, divs[0])
        n += 1
    if place_concept:
        concept_marker = f"[사진{n}]"
        if len(divs) >= 2:
            concept_sub = _subheading_after(b, divs[1])
        n += 1

    inserts = []  # (position, text) — 위치 내림차순 삽입으로 오프셋 밀림 방지
    if place_concept:
        if len(divs) >= 2:
            inserts.append((divs[1], f"{concept_marker}\n\n"))
        else:
            ti = b.find("[표삽입]")
            inserts.append((ti + len("[표삽입]"), f"\n\n{concept_marker}"))
    if place_illust:
        inserts.append((divs[0], f"{illust_marker}\n\n"))

    for pos, text in sorted(inserts, key=lambda x: -x[0]):
        b = b[:pos] + text + b[pos:]

    return "[사진1]\n" + b.lstrip("\n"), place_illust, place_concept, illust_sub, concept_sub
