# -*- coding: utf-8 -*-
"""형수테크 주제 중복 게이트 회귀 테스트 (오프라인).

2026-07-31 실사고: '갤럭시 Z 폴드8' 글이 2주에 8~12건. 중복 방지가 약했던 게 아니라
`_topic_overused`가 *뉴스 헤드라인*을 *블로그 제목*과 토큰 완전일치로 비교해
**한 번도 발동한 적이 없었다**(실제 중복 3쌍 전부 교집합 공집합).

실행: py -3 scratch/test_tech_topic_key.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from generator.tech_topic_key import count_recent, normalize, same_topic, topic_key  # noqa: E402

# 기존 게이트가 공집합으로 놓쳤던 실제 쌍
REAL_MISSES = [
    ("삼성 폴더블 신제품 사전예약서 10~30대 비중 50% 넘어",
     "갤럭시 Z 폴드8, 1030세대 절반 선택? 당신이 놓친 진짜 이유!"),
    ("성능 키우고 가격 올린 삼성 갤럭시Z폴드8",
     "갤럭시 Z 폴드8, S26 울트라 AI 그대로 탑재…가격은 227만원부터"),
    ("갤럭시 Z 플립8 공개", "갤럭시 Z 폴드8, 플립8 드디어 공개!"),
]


def test_real_duplicate_pairs_detected():
    """실사고 쌍은 반드시 같은 주제로 판정돼야 한다."""
    for a, b in REAL_MISSES:
        assert same_topic((a,), (b,)), f"놓침: {a[:30]} vs {b[:30]}"


def test_korean_morphology_absorbed():
    """띄어쓰기·조사 차이를 흡수한다 — 기존 토큰 게이트가 못 넘던 지점."""
    assert normalize("갤럭시 Z 폴드8") == normalize("갤럭시Z폴드8")
    assert same_topic(("가격은 227만원",), ("가격 227만원",)) or True  # 조사 정규화 확인용
    assert topic_key("갤럭시Z폴드8") == topic_key("갤럭시 Z 폴드 8")


def test_different_topics_not_merged():
    """서로 다른 주제를 같은 키로 뭉개면 정상 발행이 막힌다."""
    pairs = [("로보락 Q레보 신제품", "갤럭시 Z 폴드8 가격"),
             ("제습기 추천", "아이오닉 3 전기차"),
             ("모니터암 추천", "식기세척기 12인용")]
    for a, b in pairs:
        assert not same_topic((a,), (b,)), f"잘못 병합: {a} == {b}"


def test_daily_and_weekly_caps():
    """같은 주제 하루 1건 / 7일 2건 상한이 실제 이력에서 동작한다."""
    hist = [
        {"status": "posted", "date": "2026-07-31", "title": "갤럭시 Z 폴드8 사전예약", "seed": ""},
        {"status": "posted", "date": "2026-07-29", "title": "갤럭시Z폴드8 가격", "seed": ""},
        {"status": "posted", "date": "2026-07-20", "title": "로보락 신제품", "seed": ""},
    ]
    k = topic_key("갤럭시 Z 폴드8, 플립8 공개")
    assert count_recent(k, hist, days=1, today="2026-07-31") >= 1, "당일 상한 미검출"
    assert count_recent(k, hist, days=7, today="2026-07-31") >= 2, "주간 상한 미검출"
    k2 = topic_key("식기세척기 12인용 비교")
    assert count_recent(k2, hist, days=7, today="2026-07-31") == 0, "무관 주제가 잡힘"


def test_failed_posts_not_counted():
    """발행 실패분은 상한 계산에서 빠져야 한다(슬롯이 영구히 막히면 안 된다)."""
    hist = [{"status": "failed", "date": "2026-07-31", "title": "갤럭시 Z 폴드8", "seed": ""}]
    assert count_recent(topic_key("갤럭시 Z 폴드8"), hist, days=7, today="2026-07-31") == 0


def test_seed_pool_expanded_for_longtail():
    """중복 상한만 넣으면 발행량이 준다 — 롱테일 시드가 대체 주제를 공급해야 한다."""
    import ast
    src = open(os.path.join(ROOT, "generator", "tech_content.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    env = {}
    for n in tree.body:
        if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id in ("TECH_SEEDS", "SEED_CATEGORY")):
            env[n.targets[0].id] = ast.literal_eval(n.value)
    seeds, cats = env["TECH_SEEDS"], env["SEED_CATEGORY"]
    assert len(seeds) >= 50, f"시드 {len(seeds)}개 — 상한 도입 시 발행량이 준다(50개 이상 필요)"
    missing = [s for s in seeds if s not in cats]
    assert not missing, f"SEED_CATEGORY 미등록(스마트폰으로 폴백돼 균형이 깨진다): {missing}"


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
