"""QC 로그 다이제스트 — 최근 N일 판정 요약 + FAIL/WARN 목록.

사용: python scripts/qc_digest.py [--days 1]
(FAIL만 빠르게 보려면 data/qc_fail.jsonl 직접 확인)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from generator.publish_qc import summarize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    a = ap.parse_args()
    print(summarize(days=a.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
