"""
워드프레스 부트스트랩 일괄 발행 (CLAUDE_CODE_TASKS.md P0).

일차별 플랜 또는 topic 목록을 받아 scripts.wp_post를 편당 subprocess로 실행.
- 이미 wp_post_history.json에 있는 topic은 스킵
- 실패 시 1회 재시도, 편 간 sleep(기본 180초 — Gemini rate limit)

사용:
  python -m scripts.wp_batch --day 2
  python -m scripts.wp_batch --topics jeonse_loan,car_insurance --status draft
  python -m scripts.wp_batch --day 3 --dry-run
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import DATA_DIR
from generator.wp_topics import TOPICS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_batch")

_HISTORY_PATH = os.path.join(DATA_DIR, "wp_post_history.json")

# 부트스트랩 2~7일차 플랜 (CLAUDE_CODE_TASKS.md — 30편 목표)
DAY_PLANS: dict[int, list[str]] = {
    2: ["jeonse_loan", "car_insurance", "newlywed_package", "housing_benefit"],
    3: ["refinance_loan", "insurance_portfolio", "unemployment_benefit", "bogeumjari_loan"],
    4: ["pension_withdraw_tax", "retirement_irp_tax", "monthly_rent_tax", "child_tax_credit"],
    5: ["hug_jeonse_insurance", "first_home_tax", "youth_rent_support", "youth_future_savings"],
    6: ["dsr_ltv_guide", "national_pension_timing", "energy_voucher", "subscription_points"],
    7: ["gift_tax_basic", "cancer_insurance_renew", "side_income_tax"],
}


def _load_history() -> dict:
    if os.path.exists(_HISTORY_PATH):
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _run_one(topic_id: str, status: str) -> bool:
    env = {**os.environ, "WP_TOPIC": topic_id, "WP_STATUS": status}
    r = subprocess.run([sys.executable, "-m", "scripts.wp_post"], cwd=ROOT, env=env)
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description="WP 부트스트랩 일괄 발행")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--day", type=int, choices=sorted(DAY_PLANS), help="일차 플랜(2~7)")
    g.add_argument("--topics", type=str, help="쉼표 구분 topic_id 목록")
    ap.add_argument("--status", default="publish", choices=["publish", "draft"])
    ap.add_argument("--sleep", type=int, default=180, help="편 간 대기(초)")
    ap.add_argument("--dry-run", action="store_true", help="발행 없이 대상 목록만 출력")
    args = ap.parse_args()

    wanted = DAY_PLANS[args.day] if args.day else [t.strip() for t in args.topics.split(",") if t.strip()]

    unknown = [t for t in wanted if t not in TOPICS]
    if unknown:
        logger.error(f"wp_topics.py에 없는 topic: {unknown} — 먼저 추가 필요")
        sys.exit(1)

    hist = _load_history()
    queue, skipped = [], []
    for t in wanted:
        (skipped if t in hist else queue).append(t)
    if skipped:
        logger.info(f"이미 발행됨 — 스킵: {skipped}")
    if not queue:
        logger.info("발행할 topic 없음 — 종료")
        return
    logger.info(f"발행 대상 {len(queue)}편 [{args.status}]: {queue}")
    if args.dry_run:
        return

    results: dict[str, str] = {}
    for n, tid in enumerate(queue):
        if n:
            logger.info(f"{args.sleep}초 대기(rate limit)…")
            time.sleep(args.sleep)
        logger.info(f"── ({n + 1}/{len(queue)}) {tid} ──")
        ok = _run_one(tid, args.status)
        if not ok:
            logger.warning(f"{tid} 실패 — 60초 후 1회 재시도")
            time.sleep(60)
            ok = _run_one(tid, args.status)
        results[tid] = "OK" if ok else "FAIL"

    logger.info("── 결과 ──")
    for tid, res in results.items():
        logger.info(f"  {tid}: {res}")
    if "FAIL" in results.values():
        sys.exit(1)


if __name__ == "__main__":
    main()
