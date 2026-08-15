#!/bin/bash
# 베네핏지니 WP 허브 발행 러너 — 발행 → 이력 커밋·푸시 → IndexNow 핑
#
# 2026-07-24 ops 편입: EC2 로컬에만 있던 스크립트를 레포로(버전관리·복원).
#   EC2 부트스트랩: cd <repo> && git pull -q && exec ops/run_wp.sh "$@"
# 실행 전제: CWD = 레포 루트(부트스트랩이 cd·pull 완료)
VENV=/home/ubuntu/ai-agent/venv/bin/python
KEYFILE=/home/ubuntu/ai-agent/indexnow.key

nice -n 10 "$VENV" -m scripts.wp_post
CODE=$?

git add data/wp_post_history.json data/wp_first_published.json data/qc_log.jsonl data/qc_fail.jsonl 2>/dev/null
if ! git diff --staged --quiet 2>/dev/null; then
  git commit -qm "chore: 워드프레스 발행 이력 (ec2 $(date -u +%F))"
  git pull --rebase --autostash -q && git push -q
fi

# IndexNow(2026-07-19): 빙 색인 0 해소 — 발행 성공 시 최신 글 URL 핑
if [ $CODE -eq 0 ] && [ -f "$KEYFILE" ]; then
  KEY=$(cat "$KEYFILE")
  PID=$(sudo -n -u www-data wp --path=/var/www/html post list --post_type=post --post_status=publish --orderby=date --order=DESC --posts_per_page=1 --field=ID 2>/dev/null | head -1)
  URL=$(sudo -n -u www-data wp --path=/var/www/html post url "$PID" 2>/dev/null | head -1)
  if [ -n "$URL" ]; then
    EURL=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=chr(39)))" "$URL")
    curl -s "https://api.indexnow.org/indexnow?url=${EURL}&key=${KEY}" >/dev/null && echo "indexnow ok: $URL"
  fi
fi
exit $CODE
