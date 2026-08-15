"""카테고리별 공식 출처 참조 — 네이버·WP 프롬프트 팩트 주입용."""

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# info_cat_id → (기관명, 확인 URL)
INFO_OFFICIAL_SOURCES: dict[str, list[tuple[str, str]]] = {
    "금융재테크": [
        ("금융감독원 금융상품한눈에", "https://finlife.fss.or.kr"),
        ("국세청 연금·금융소득 안내", "https://www.nts.go.kr"),
        ("금융감독원 통합연금포털", "https://100lifeplan.fss.or.kr"),
    ],
    "세금절세": [
        ("국세청 홈택스", "https://www.hometax.go.kr"),
        ("국세청 연말정산·공제 안내", "https://www.nts.go.kr"),
    ],
    "보험": [
        ("보험다모아(생·손보협회)", "https://www.e-insmarket.or.kr"),
        ("내보험찾아줌", "https://cont.insure.or.kr"),
        ("금융감독원 FINE", "https://fine.fss.or.kr"),
    ],
    "부동산주거": [
        ("마이홈(국토교통부)", "https://www.myhome.go.kr"),
        ("주택도시기금", "https://nhuf.molit.go.kr"),
        ("국토교통부 실거래가", "https://rt.molit.go.kr"),
    ],
}

GOV_OFFICIAL_SOURCES: list[tuple[str, str]] = [
    ("복지로(정부24)", "https://www.bokjiro.go.kr"),
    ("국민신문고", "https://www.epeople.go.kr"),
    ("고용24", "https://www.work24.go.kr"),
]


def format_sources_block(sources: list[tuple[str, str]], header: str = "◆ 공식 확인 경로") -> str:
    if not sources:
        return ""
    lines = [header]
    for name, url in sources:
        lines.append(f"  · {name}: {url}")
    return "\n".join(lines) + "\n"


# ── E-E-A-T 신뢰 시그널 (노매새드 벤치마킹, 2026-07-22) ──────────────────────
# 익명 자동생성 블로그의 신뢰 약점 보완: 요약블록 끝에 '기준시점 + 최종 업데이트'
# 한 줄을 발행일 기준 자동 삽입. 날짜는 코드가 생성(LLM 할루시네이션 차단).
def eeat_asof_line(dt: datetime | None = None) -> str:
    """발행일 기준 '○년 ○월 기준 · 최종 업데이트: YYYY-MM-DD' 한 줄."""
    d = dt or datetime.now(KST)
    return f"{d.year}년 {d.month}월 기준 · 최종 업데이트: {d.strftime('%Y-%m-%d')}"


def append_eeat_line(summary_text: str, dt: datetime | None = None) -> str:
    """요약블록 맨 끝에 기준시점 한 줄을 붙인다(발행일 자동, 중복 방지).
    ★반드시 헤더카드(extract_summary_bullets)·개념카드(concept_lines)가 원문
    summary_text를 이미 소비한 '뒤', poster 전달 인자에서만 호출할 것 —
    생성기/스크립트 앞단에서 붙이면 카드에 날짜줄이 섞여 들어간다."""
    if not summary_text or not summary_text.strip():
        return summary_text  # 요약블록 없는 글은 그대로(강제 생성 안 함)
    if "최종 업데이트:" in summary_text:  # 이미 있으면 중복 삽입 금지
        return summary_text
    return summary_text.rstrip() + "\n" + eeat_asof_line(dt)
