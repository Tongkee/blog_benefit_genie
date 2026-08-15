# -*- coding: utf-8 -*-
"""번호 팩트 연대기(M1) 엔진 오프라인 테스트 + DART RSS 라이브 스모크.

실행: py -3 scratch/test_fact_chronicle.py          (오프라인만)
      LIVE=1 py -3 scratch/test_fact_chronicle.py   (DART RSS 스모크 포함)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from generator.fact_chronicle import (
    dart_today_facts, load_facts, min_items_gate, render_body, verify_rendered,
)

passed = 0
failed = []


def check(name, cond):
    global passed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed.append(name)
        print(f"  ❌ {name}")


RAW = [
    {"date": "2026-07-30", "fact": "A사가 유상증자 3,000억원을 결정했다",
     "figures": ["3000"], "source_url": "https://dart.fss.or.kr/1"},
    {"date": "2026-07-28", "fact": "B사가 자기주식 500억원 취득을 공시했다",
     "figures": ["500"], "source_url": "https://dart.fss.or.kr/2"},
    {"date": "2026-07-29", "fact": "URL 없는 팩트다", "figures": [], "source_url": ""},
    {"date": "2026-07-29", "fact": "대통령의 아파트 매매내용이 공개됐다",
     "figures": [], "source_url": "https://example.com/x"},          # 금지 목록
    {"date": "내일", "fact": "날짜 불량 팩트 1건이다", "figures": [],
     "source_url": "https://example.com/y"},
    {"date": "2026-07-31", "fact": "관계자는 상장 계획을 밝혔다", "figures": [],
     "source_url": "https://example.com/z"},                          # 미상 인용
]

print("[1] 적재 게이트 — URL·금지목록·날짜·정렬·기계 번호")
items = load_facts(RAW)
check("URL 없음·금지목록·날짜불량·미상인용 배제(6→2)", len(items) == 2)
check("날짜순 정렬", [f["date"] for f in items] == ["2026-07-28", "2026-07-30"])
check("기계 번호 1~N", [f["no"] for f in items] == [1, 2])

print("[2] 숫자 대조 게이트 — 실패 항목 삭제 + 번호 재부여")
rendered = {1: "B사가 500억원 규모 자기주식 취득을 공시했다",
            2: "A사가 9,999억원 유상증자를 결정했다"}   # 2번 수치 날조
verified = verify_rendered(items, rendered)
check("날조 항목 삭제", len(verified) == 1)
check("번호 재부여(1부터)", verified[0]["no"] == 1)
check("생존 문장 유지", "500억원" in verified[0]["sentence"])
verified2 = verify_rendered(items, {})   # 변환 실패 → 튜플 원문 폴백
check("변환 실패 시 튜플 원문 폴백", len(verified2) == 2
      and verified2[0]["sentence"].startswith("B사가"))

print("[3] 본문 렌더 — 번호 연대기 + 출처 줄 + 참고 줄")
body = render_body(verified2, "주제")
check("번호 줄 형식", "1. (2026-07-28)" in body and "2. (2026-07-30)" in body)
check("출처 줄", body.count("출처: https://dart.fss.or.kr") == 2)
check("참고 줄 마지막", body.strip().endswith("참고: 공식 공시·공공데이터 원문 연대기"))
check("1문단 1문장(빈 줄 구분)", "\n\n" in body)

print("[4] 하한 게이트")
check("15항 미달 스킵", min_items_gate(verified2, 15) is False)
check("하한 충족 통과", min_items_gate(verified2, 2) is True)

if os.environ.get("LIVE") == "1":
    print("[5] DART RSS 라이브 스모크")
    all_items = dart_today_facts([], limit=10)   # 키워드 없음 = 전체 상위
    check("오늘공시 수신", len(all_items) > 0)
    if all_items:
        f = all_items[0]
        check("4-튜플 형식", all(k in f for k in ("date", "fact", "figures", "source_url")))
        check("URL 존재", f["source_url"].startswith("http"))
        print(f"     예시: {f['fact'][:60]} | {f['date']}")

print(f"\n결과: {passed}개 통과, {len(failed)}개 실패")
if failed:
    print("실패:", failed)
    sys.exit(1)
