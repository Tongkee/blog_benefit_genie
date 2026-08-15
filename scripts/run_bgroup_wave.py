# -*- coding: utf-8 -*-
"""B그룹 '제목 오류' 글 웨이브 처리 — 삭제 → FORCE_KEYWORD 재발행 (2026-07-31 §2-③).

한 번에 몇 건씩만 처리한다(웨이브). 63건을 하루에 다 재발행하면 네이버
유사문서·스팸 리스크(인수인계서 경고) — 기본 웨이브 5건.

순서(건별): delete_posts_ui.py 로 삭제(실검증 포함) → 해당 트랙 스크립트를
FORCE_KEYWORD·FORCE_POST 로 재발행(고정 사실 테이블이 올바른 수치 자동 주입)
→ data/bgroup_progress.json 에 기록. 재발행 실패해도 다음 건 진행(글은 이미
삭제됨 — 실패 목록을 남겨 다음 웨이브에서 재시도).

⚠️웨이브 후 반드시: scan_broken_links.py → build_relink_plan.py →
fix_related_links.py (삭제로 새로 깨진 다른 글의 관련글 카드 복구).

사용: py -3 scripts/run_bgroup_wave.py [웨이브크기=5] [--dry]
"""
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
DATA = os.path.join(ROOT, "data")
PROGRESS = os.path.join(DATA, "bgroup_progress.json")
PY = sys.executable


def _load_progress():
    try:
        return json.load(open(PROGRESS, encoding="utf-8"))
    except Exception:
        return {"done": [], "republish_failed": []}


def _save_progress(p):
    json.dump(p, open(PROGRESS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _pick_wave(plan, progress, size):
    """강한 신호(지적문에 제목 언급) 우선, 계획 순서 유지."""
    done = set(progress["done"])
    strong = [e for e in plan if e.get("title_error") and e.get("keyword")
              and e["logno"] not in done
              and any("제목 언급" in s for s in e.get("signals", []))]
    weak = [e for e in plan if e.get("title_error") and e.get("keyword")
            and e["logno"] not in done and e not in strong]
    return (strong + weak)[:size]


def _republish(entry) -> bool:
    env = {**os.environ, "FORCE_KEYWORD": entry["keyword"], "FORCE_POST": "true"}
    if entry["track"] == "info":
        env["INFO_CATEGORY"] = entry["track_cat"]
        mod = "scripts.info_post"
    elif entry["track"] == "gov":
        mod = "scripts.gov_post"
    else:
        print(f"    알 수 없는 트랙 {entry['track']!r} — 재발행 스킵")
        return False
    r = subprocess.run([PY, "-m", mod], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    tail = "\n".join((r.stdout or "").splitlines()[-4:])
    print(f"    재발행 exit={r.returncode}\n      " + tail.replace("\n", "\n      "))
    return r.returncode == 0


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    dry = "--dry" in sys.argv
    plan = json.load(open(os.path.join(DOCS, "bgroup_plan.json"), encoding="utf-8"))
    progress = _load_progress()
    wave = _pick_wave(plan, progress, size)
    print(f"웨이브 {len(wave)}건 (dry={dry}) — 누적 완료 {len(progress['done'])}건")
    for e in wave:
        print(f"  {e['logno']} [{e['track']}/{e.get('track_cat')}] kw={e['keyword']!r} "
              f"{e['title'][:34]}")
    if dry:
        return

    for i, e in enumerate(wave, 1):
        print(f"\n[{i}/{len(wave)}] {e['logno']} {e['title'][:40]}")
        # ① 삭제(실검증 포함 — delete_posts_ui 만 사용, §5-3)
        tmp = os.path.join(DATA, "_wave_delete.json")
        json.dump([{"logno": e["logno"]}], open(tmp, "w", encoding="utf-8"))
        r = subprocess.run([PY, os.path.join("scripts", "delete_posts_ui.py"), tmp],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        deleted = "✓ 삭제 확인" in (r.stdout or "") or "이미 없음" in (r.stdout or "")
        print(f"    삭제 {'확인' if deleted else '실패'}")
        if not deleted:
            continue
        # ② 재발행
        ok = _republish(e)
        progress["done"].append(e["logno"])
        if not ok:
            progress["republish_failed"].append(e["logno"])
        _save_progress(progress)
        time.sleep(90)   # 발행 페이스 조절

    print(f"\n웨이브 종료 — 누적 완료 {len(progress['done'])}건, "
          f"재발행 실패 {len(progress['republish_failed'])}건")
    print("⚠️ 다음 순서: scan_broken_links.py → build_relink_plan.py → fix_related_links.py")


if __name__ == "__main__":
    main()
