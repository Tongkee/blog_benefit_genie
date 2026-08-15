"""A/S 4필드 추출기 오프라인 테스트 (API 호출 없음 — 검증 로직만).

실행: py -3 scratch/test_as_fields.py  (집 PC는 python 도 가능)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator.as_fields import (
    EMPTY_FIELDS, _norm_verify_date, _num_tokens, _parse_json, validated_fields,
)

BODY = """2026년 기준 중위소득은 1인 가구 월 2,564,238원입니다.
주거급여는 중위소득 48% 이하가 대상이고, 서울 1인 가구 기준임대료는 월 369,000원입니다.
경조사비는 건당 20만원까지 경비 처리됩니다."""

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


print("[1] 숫자 토큰 정규화")
check("콤마 제거", _num_tokens("월 2,564,238원") == {"2564238"})
check("소수점 보존", _num_tokens("6.51% 인상") == {"6.51"})
check("빈 문자열", _num_tokens("") == set())

print("[2] JSON 파싱")
check("코드펜스 허용", _parse_json('```json\n{"claim": "x"}\n```') == {"claim": "x"})
check("앞뒤 잡설 허용", _parse_json('추출 결과:\n{"claim": "x"} 끝') == {"claim": "x"})
try:
    _parse_json("JSON 없음")
    check("JSON 없음은 예외", False)
except ValueError:
    check("JSON 없음은 예외", True)

print("[3] verify_date 정규화")
check("YYYY-MM-DD 통과", _norm_verify_date("2026-08-15") == "2026-08-15")
check("YYYY-MM은 말일로", _norm_verify_date("2026-08") == "2026-08-31")
check("2월 말일", _norm_verify_date("2026-02") == "2026-02-28")
check("형식 불량은 None", _norm_verify_date("내년 8월") is None)
check("None 입력", _norm_verify_date(None) is None)

print("[4] 정상 추출 통과")
raw = {
    "claim": "2026년 기준 중위소득은 1인 가구 월 2,564,238원이다.",
    "claim_numbers": [
        {"value": "월 2,564,238원", "source": "보건복지부 고시 제2025-135호"},
        {"value": "48%", "source": None},
    ],
    "verify_event": "2026년 8월 기준 중위소득 고시 발표",
    "verify_date": "2026-08",
}
out = validated_fields(raw, BODY)
check("claim 보존", out["claim"] == raw["claim"])
check("수치 2쌍 통과", len(out["claim_numbers"]) == 2)
check("source 보존", out["claim_numbers"][0]["source"] == "보건복지부 고시 제2025-135호")
check("verify_date 말일 정규화", out["verify_date"] == "2026-08-31")

print("[5] 본문에 없는 수치가 claim에 → 전체 폐기")
out = validated_fields({"claim": "지원금은 월 999,999원이다.",
                        "claim_numbers": [{"value": "월 369,000원", "source": None}]}, BODY)
check("전체 폐기", out == EMPTY_FIELDS)

print("[6] 본문에 없는 수치 쌍만 제거 (claim은 유지)")
out = validated_fields({
    "claim": "서울 1인 가구 기준임대료는 월 369,000원이다.",
    "claim_numbers": [
        {"value": "월 369,000원", "source": None},
        {"value": "월 999,999원", "source": None},   # 날조 — 이 쌍만 제거
    ],
}, BODY)
check("유효 쌍만 생존", [p["value"] for p in out["claim_numbers"]] == ["월 369,000원"])
check("claim 유지", out["claim"] is not None)

print("[7] 결측·이상 입력 내성")
out = validated_fields({}, BODY)
check("빈 raw → 전부 null", out == EMPTY_FIELDS)
out = validated_fields({"claim": "  ", "claim_numbers": "문자열", "verify_event": 3,
                        "verify_date": ["x"]}, BODY)
check("타입 이상 → 전부 null", out == EMPTY_FIELDS)
out = validated_fields({"claim_numbers": [{"value": "20만원", "source": "  "}, "잡음", {"no": 1}]},
                       BODY)
check("잡음 항목 무시·빈 source는 null",
      out["claim_numbers"] == [{"value": "20만원", "source": None}])

print(f"\n결과: {passed}개 통과, {len(failed)}개 실패")
if failed:
    print("실패:", failed)
    sys.exit(1)
