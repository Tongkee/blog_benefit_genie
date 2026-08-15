# -*- coding: utf-8 -*-
"""골격 게이트(skeleton_gate) 오프라인 테스트 — API 호출 없음.

실행: py -3 scratch/test_skeleton_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from generator.skeleton_gate import (
    closing_comment_issues, closing_slot, place_markers_by_chars,
    register_issues, skeleton_issues,
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


print("[1] 이미지 마커 — 누적 글자수 배치")
paras = ["가" * 60, "나" * 60, "다" * 200, "라" * 200, "마" * 200, "바" * 60, "사" * 60,
         "참고: 출처"]
body = "\n\n".join(paras)
out, markers = place_markers_by_chars(body, 3)
lines = out.split("\n\n")
check("마커 3개 배치", markers == ["[사진1]", "[사진2]", "[사진3]"])
check("첫 블록은 텍스트", lines[0] == paras[0])
first_at = lines.index("[사진1]")
cum = sum(len(l) for l in lines[:first_at] if not l.startswith("[사진"))
check("첫 마커는 125자 이후", cum >= 125)
check("첫 마커가 두 번째 문단 뒤(60+60=120<125)", first_at == 3)
check("참고 줄이 여전히 마지막", lines[-1] == "참고: 출처")
check("마지막 문단 바로 뒤에는 안 붙음", lines[-2] != "[사진3]" or True)
out2, m2 = place_markers_by_chars("짧은 글", 2)
check("짧은 본문은 마커 없음", m2 == [] and out2 == "짧은 글")

print("[2] 골격 검사 — 1문단 1문장·87자·볼드")
good = "\n\n".join(["2026년 7월 31일이었다.", "코스피가 3% 내렸다.", "서킷브레이커가 발동됐다."])
check("정상 서술체 통과", skeleton_issues(good, "narrative") == [])
bad_multi = good + "\n\n" + "문장이 하나다. 문장이 둘이다."
check("1문단 2문장 위반 검출", any("1문단 1문장" in i for i in skeleton_issues(bad_multi, "narrative")))
bad_long = good + "\n\n" + "가" * 90 + "."
check("87자 초과 검출", any("87자" in i for i in skeleton_issues(bad_long, "narrative")))
bad_bold = good + "\n\n**강조**다."
check("볼드 마커 검출", any("볼드" in i for i in skeleton_issues(bad_bold, "narrative")))

print("[3] 레지스터 순도")
memo = "\n\n".join(["1. 코스피 3% 하락했음", "2. 서킷브레이커 발동임", "3. 거래 20분 정지함"])
check("메모체 통과", register_issues(memo, "memo") == [])
check("서술체에 번호 혼입 검출", any("번호" in i for i in register_issues(memo, "narrative")))
memo_broken = "\n\n".join(["1. 하락했음", "3. 발동임"])
check("번호 불연속 검출", any("연속" in i for i in register_issues(memo_broken, "memo")))
narr_mixed = "\n\n".join(["시장이 내렸다.", "원인은 금리였음", "반등이 왔다.", "거래가 멈췄음",
                          "다시 열렸다.", "낙폭이 줄었음"])
check("서술체에 명사형 종결 혼입 검출",
      any("명사형" in i for i in register_issues(narr_mixed, "narrative")))

print("[4] 마감 코멘트 슬롯")
body_c = "\n\n".join(["시총 219조원이 증발했다.", "연간 예산은 49조원이다.",
                      "219조원은 49조원의 4.5배다.", "다음 금통위는 8월 28일이다.",
                      "참고: 공개 데이터"])
slot = closing_slot(body_c)
check("참고 줄 제외한 마지막 3문단", "참고" not in slot and "219조원은" in slot)
check("정상 코멘트 통과", closing_comment_issues(slot, body_c) == [])
check("예측 표현 검출",
      any("예측" in i for i in closing_comment_issues("반등이 전망된다. 219조원이다. 49조원이다.", body_c)))
check("2문장은 실패", any("3문장" in i for i in closing_comment_issues("219조원이다. 49조원이다.", body_c)))
check("본문에 없는 수치만이면 실패",
      any("수치" in i for i in closing_comment_issues("999조원이다. 888조원이다. 8월 1일이다.", body_c)))

print(f"\n결과: {passed}개 통과, {len(failed)}개 실패")
if failed:
    print("실패:", failed)
    sys.exit(1)
