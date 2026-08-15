# -*- coding: utf-8 -*-
"""계산 슬롯(calc_slot) 오프라인 테스트 — 네트워크·LLM 없음.

실행: py -3 scratch/test_calc_slot.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from generator.calc_slot import FORMULAS, build_calc_section

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


def mk(name, price, prev, pct=1.0):
    return {"name": name, "price": price, "prev": prev, "pct": pct,
            "price_str": f"{price:,}", "pct_str": f"(+{pct:.2f}%)", "up": True}


DATA = [
    mk("나스닥", 23000.0, 22770.0, 1.01),
    mk("S&P500", 6600.0, 6580.0, 0.30),
    mk("WTI 국제유가", 70.0, 69.0),
    mk("원/달러 환율", 1400.0, 1390.0),
    mk("국제 금", 3000.0, 2990.0),
    mk("비트코인", 100000.0, 99000.0),
]

print("[1] 산식별 수치 검증(코드 계산)")
gold = FORMULAS["gold_don"](DATA)
# 3000$ × 1400원 = 420만원/온스, 1온스=8.294돈 → 1돈 ≈ 50.6만원
check("금 1돈 환산", gold and "420만원" in gold[1] and "51만원" in gold[2])
oil = FORMULAS["oil_liter"](DATA)
# 70×1400=98,000원/배럴 ÷158.987 = 616원/L
check("기름 리터 환산", oil and "616원" in oil[2])
btc = FORMULAS["btc_krw"](DATA)
# 100,000×1400 = 1.4억
check("비트코인 원화", btc and "1.4억원" in btc[1])
spread = FORMULAS["tech_spread"](DATA)
check("기술주 스프레드 0.71%p", spread and "+0.71%p" in spread[1])
fx = FORMULAS["fx_10k"](DATA)
# (1400-1390)×10000 = 10만원 더
check("1만달러 환전 차액", fx and "10만원" in fx[1] and "더 들어갑니다" in fx[1])

print("[2] 화이트리스트 게이트")
check("미등록 산식 → None(슬롯 생략)", build_calc_section(DATA, formula="없는산식") is None)
check("등록 산식 지정 실행", "🧮 오늘의 계산" in (build_calc_section(DATA, formula="gold_don") or ""))

print("[3] 로테이션·폴백")
sec = build_calc_section(DATA)
check("자동 로테이션 섹션 생성", sec is not None and sec.startswith("[구분선]\n🧮 오늘의 계산"))
no_fx = [d for d in DATA if "환율" not in d["name"]]
sec2 = build_calc_section(no_fx)   # 환율 필요 산식은 건너뛰고 tech_spread로 폴백 가능
check("입력 결손 시 폴백", sec2 is not None and "나스닥" in sec2)
check("전부 결손 → None", build_calc_section([]) is None)

print(f"\n결과: {passed}개 통과, {len(failed)}개 실패")
if failed:
    print("실패:", failed)
    sys.exit(1)
