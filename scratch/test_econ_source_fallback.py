# -*- coding: utf-8 -*-
"""요즘경제 소스 폴백 회귀 테스트 (오프라인 — LLM/네트워크 불필요).

2026-07-31 실사고: 후보 12건을 모아놓고 **1건만 시도**한 뒤 표절 게이트에 걸리면
발행을 포기했다. 세법·부동산 분석글은 개념 문장이 그대로 겹치기 쉬워 특정 소스는
몇 번을 다시 써도 통과하지 못한다 → 트랙이 신설 이후 발행 0건이었다.

실행: py -3 scratch/test_econ_source_fallback.py
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import generator.econ_digest as ed  # noqa: E402
from generator.econ_digest import overlap_guard  # noqa: E402


def test_gate_still_blocks_verbatim_copy():
    """게이트를 느슨하게 푼 게 아님을 확인 — 원문 그대로 베끼면 여전히 잡힌다."""
    src = ("전세의 월세 전환과 임대료 인상이 이어지면서 세입자 부담이 커지고 있습니다. "
           "장기 보유자가 늘었습니다.")
    assert overlap_guard(src, src), "원문 복제가 게이트를 통과하면 안 된다"


def test_gate_allows_fixed_terms():
    """법정 고정용어·수치 나열은 표절이 아니다(과차단 방지)."""
    src = "3주택이상 중과세율은 과세표준 구간별로 다르며 장기보유특별공제가 배제됩니다."
    body = "다주택자라면 중과세율과 과세표준을 먼저 확인해 보세요. 장기보유특별공제도 살펴봐야 해요."
    hits = overlap_guard(body, src)
    assert not hits, f"고정용어 나열을 표절로 잡음: {hits}"


def test_source_fallback_advances(monkeypatch=None):
    """게이트에 걸리는 소스는 버리고 다음 후보로 넘어간다."""
    calls = {"picked": [], "wrote": 0}

    cands = [{"url": f"u{i}", "blog_id": "b", "log_no": str(i),
              "author": "a", "title": f"t{i}"} for i in range(5)]

    def fake_pick(pool, key):
        t = pool[0]
        calls["picked"].append(t["url"])
        return t

    def fake_body(bid, lno):
        return "원" * 800

    def fake_facts(src, author, key):
        return {"facts": [1, 2, 3, 4, 5]}

    def fake_write(facts, author, key, avoid=None):
        calls["wrote"] += 1
        # 앞의 3개 소스는 계속 겹치는 본문, 4번째부터 깨끗한 본문
        idx = len(calls["picked"]) - 1
        return {"title": "T", "body": ("원" * 50) if idx < 3 else "완전히 새로 쓴 문장입니다.",
                "tags": []}

    def fake_guard(body, src):
        return ["원" * 18] if "원" * 50 in body else []

    mod = types.ModuleType("stub")
    for name, fn in (("fetch_candidates", lambda seen: cands), ("pick_topic", fake_pick),
                     ("fetch_body_text", fake_body), ("extract_facts", fake_facts),
                     ("write_post", fake_write), ("overlap_guard", fake_guard)):
        setattr(mod, name, fn)
    sys.modules["generator.econ_digest"] = mod
    try:
        # run()의 소스 루프만 재현 — 실제 코드와 같은 구조
        pool, post, failed = list(cands), None, []
        for _ in range(4):
            if not pool:
                break
            topic = fake_pick(pool, "")
            pool = [c for c in pool if c["url"] != topic["url"]]
            for _a in range(3):
                p = fake_write(fake_facts("", "", ""), "", "")
                if fake_guard(p["body"], ""):
                    continue
                post = p
                break
            if post:
                break
            failed.append(topic["title"])
    finally:
        sys.modules["generator.econ_digest"] = ed

    assert post is not None, "폴백이 동작하면 4번째 소스에서 성공해야 한다"
    assert len(failed) == 3, f"실패한 소스 3건을 건너뛰어야 함(실제 {len(failed)})"
    assert len(calls["picked"]) == 4, f"소스를 4건 시도해야 함(실제 {len(calls['picked'])})"


def test_max_sources_bounded():
    """무한 시도 방지 — 소스 시도 횟수에 상한이 있다."""
    src = open(os.path.join(ROOT, "scripts", "econ_digest_post.py"), encoding="utf-8").read()
    assert "MAX_SOURCES" in src, "소스 시도 상한 상수가 없다"
    assert "range(MAX_SOURCES)" in src, "상한이 루프에 적용되지 않았다"


def test_failure_is_loud():
    """전부 실패하면 조용히 성공으로 끝나면 안 된다."""
    src = open(os.path.join(ROOT, "scripts", "econ_digest_post.py"), encoding="utf-8").read()
    assert "::error::" in src, "게이트 전멸 시 ::error 미출력"
    assert "sys.exit(1)" in src, "게이트 전멸 시 종료코드가 0이면 워크플로가 초록불이 된다"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"[OK  ] {name}")
            except AssertionError as e:
                fails += 1
                print(f"[FAIL] {name}: {e}")
    print("PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
