#!/bin/bash
# tech.benefitgenie.com 심층 가이드 러너 — pull → 발행 → 이력 push → IndexNow
#
# 2026-07-24: EC2 로컬(/home/ubuntu/ai-agent/run_wp_tech.sh)에만 있던 스크립트를 레포로 편입
# (버전관리·리뷰·EC2 재구축 시 복원). EC2에는 얇은 부트스트랩만 남기고 실제 로직은 여기.
#   EC2 부트스트랩: cd <repo> && git pull -q && exec ops/run_wp_tech.sh "$@"
#   ※부트스트랩이 pull까지 끝낸 뒤 exec 하므로, 이 파일이 pull로 갱신돼도 안전하게 새 버전이 실행됨
#     (bash가 실행 중 스크립트 파일을 이어 읽는 특성 때문에 자기 자신을 pull하면 깨질 수 있음).
# 실행 전제: CWD = 레포 루트(부트스트랩이 cd 완료), venv=/home/ubuntu/ai-agent/venv
set -o pipefail
VENV=/home/ubuntu/ai-agent/venv/bin/python
KEYFILE=/home/ubuntu/ai-agent/indexnow.key

OUT=$("$VENV" -m scripts.wp_tech_post 2>&1)
CODE=$?
echo "$OUT"

# 발행 이력 + QC 로그(2026-07-23 신설 게이트) 커밋
git add data/wp_tech_history.json data/qc_log.jsonl data/qc_fail.jsonl 2>/dev/null
if ! git diff --staged --quiet 2>/dev/null; then
  git commit -qm "chore: tech WP 가이드 이력 (ec2 $(date -u +%F))"
  git pull --rebase --autostash -q && git push -q
fi

# IndexNow 핑(빙) — 발행 성공 + URL 있을 때만
URL=$(echo "$OUT" | grep -oP "(?<=POST_URL=).*" | tail -1)
if [ $CODE -eq 0 ] && [ -n "$URL" ] && [ -f "$KEYFILE" ]; then
  KEY=$(cat "$KEYFILE")
  EURL=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=chr(39)))" "$URL")
  curl -s "https://api.indexnow.org/indexnow?url=${EURL}&key=${KEY}" >/dev/null && echo "indexnow ok: $URL"
fi
exit $CODE
