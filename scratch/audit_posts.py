import io, sys, json, glob, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
today = "2026-07-06"
total = 0
for f in sorted(glob.glob("data/*history*.json")):
    try:
        rows = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    if not isinstance(rows, list):
        continue
    todays = [r for r in rows if isinstance(r, dict) and str(r.get('date', r.get('timestamp', ''))).startswith(today)]
    if not todays:
        continue
    posted = [r for r in todays if r.get('status') == 'posted' or r.get('post_url')]
    total += len(posted)
    print("")
    print("[%s] 오늘 %d건 (posted %d)" % (os.path.basename(f), len(todays), len(posted)))
    for r in todays:
        kw = r.get('keyword') or (r.get('title', '') or '')[:24]
        slot = r.get('run_slot') or r.get('slot') or r.get('stock_topic') or r.get('topic') or ''
        ts = (r.get('timestamp', '') or '')[11:16]
        print("   %s %-7s slot=%-14s %s" % (ts, r.get('status', '?'), slot, kw))
print("")
print("=== 오늘 실제 posted 총 %d건 ===" % total)
