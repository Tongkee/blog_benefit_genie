# -*- coding: utf-8 -*-
"""유실된 발행 이력 복구 (2026-07-29).

배경: 07-27~29 워크플로 git add 회귀로 '발행은 됐으나 이력만 커밋 안 된' 구간 발생.
이력이 비면 ①중복 방지(같은 주제 재발행)가 무력화되고 ②QC/통계가 어긋난다.
GH Actions 실행 로그에서 실제 발행 URL·제목을 뽑아 이력 파일에 채워 넣는다.

멱등: 이미 있는 post_url은 건너뛴다. DRY_RUN=1이면 진단만.
실행: python scripts/recover_history.py            (gh CLI 필요)
      DRY_RUN=1 python scripts/recover_history.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

KST = timezone(timedelta(hours=9))
DRY = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True")
GH = r"C:\Program Files\GitHub CLI\gh.exe"
if not os.path.exists(GH):
    GH = "gh"

# 워크플로 → (이력파일, 로그의 '완료' 패턴)
TRACKS = [
    ("gov_post.yml", "data/gov_history.json", r"정부지원 포스팅 완료: (\S+)"),
    ("info_post.yml", None, r"([가-힣, ·]+) 포스팅 완료: (\S+)"),  # 카테고리별 파일 분기
    ("cheongyak_naver_post.yml", "data/cheongyak_naver_history.json",
     r"청약.*발행 완료.*?(https://\S+)"),
]
INFO_CAT_FILE = {
    "부동산, 주거": "data/info_부동산주거_history.json",
    "금융, 재테크": "data/info_금융재테크_history.json",
    "세금, 절세": "data/info_세금절세_history.json",
    "보험": "data/info_보험_history.json",
}


def _sh(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=180).stdout or ""
    except Exception as e:
        print(f"   (명령 실패: {e})")
        return ""


def _load(path: str):
    """list 이력만 지원. dict 이력(청약 네이버 = 공고번호 키)은 None을 돌려 복구 대상에서
    제외한다 — 2026-07-29 실사고: dict를 []로 간주하고 list로 덮어써 중복 가드가 무력화됨."""
    p = os.path.join(ROOT, path)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            print(f"   (스킵: {path}는 dict 이력 — 이 스크립트로 복구 금지, 수동 복구 필요)")
            return None
        return []
    except Exception:
        return []


def _save(path: str, data: list) -> None:
    p = os.path.join(ROOT, path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    print(f"유실 이력 복구{' [DRY_RUN]' if DRY else ''}\n")
    added_total = 0
    for wf, hist_path, pat in TRACKS:
        print(f"■ {wf}")
        runs = _sh([GH, "run", "list", "--workflow", wf, "--limit", "12",
                    "--json", "databaseId,createdAt,conclusion"])
        try:
            runs = json.loads(runs)
        except Exception:
            print("   run 목록 조회 실패 — gh 인증 확인")
            continue
        for r in runs:
            if r.get("conclusion") != "success":
                continue
            created = r.get("createdAt", "")[:10]
            if created < "2026-07-27":       # 유실 구간만
                continue
            log = _sh([GH, "run", "view", str(r["databaseId"]), "--log"])
            if not log:
                continue
            for m in re.finditer(pat, log):
                groups = m.groups()
                if wf.startswith("info"):
                    cat, url = groups[0].strip(), groups[1]
                    hp = INFO_CAT_FILE.get(cat)
                    if not hp:
                        continue
                else:
                    url = groups[-1]
                    hp = hist_path
                url = url.strip().rstrip(",.|")
                if "blog.naver.com" not in url:
                    continue
                # gh 로그는 시크릿(블로그ID)을 ***로 마스킹 → 실제 ID로 복원
                url = url.replace("/***/", "/benefit_genie/")
                hist = _load(hp)
                if hist is None:
                    continue      # dict 이력 — 이 스크립트 소관 아님
                if any(str(h.get("post_url", "")).endswith(url.split("/")[-1])
                       for h in hist if isinstance(h, dict)):
                    continue          # 이미 있음(멱등)
                entry = {
                    "date": created,
                    "timestamp": r.get("createdAt", ""),
                    "title": "(로그 복구 — 제목 미상)",
                    "status": "posted",
                    "post_url": url,
                    "recovered": True,   # 복구분 표시
                }
                print(f"   + {created} {url}  → {os.path.basename(hp)}")
                added_total += 1
                if not DRY:
                    hist.insert(0, entry)
                    _save(hp, hist[:300])
    print(f"\n복구 {added_total}건{' (DRY_RUN — 미저장)' if DRY else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
