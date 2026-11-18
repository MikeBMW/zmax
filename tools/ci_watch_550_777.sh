#!/usr/bin/env bash
# 轮询 v5.50.777 的 Build Desktop run, 完成后回读 release 资产
set -uo pipefail
cd /home/ubuntu/zmax || exit 1
TOK=$(printf "protocol=https\nhost=github.com\nusername=MikeBMW\n\n" | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2)
API=https://api.github.com/repos/MikeBMW/zmax
RID=43976284800
for i in $(seq 1 90); do
  J=$(curl -s -H "Authorization: Bearer $TOK" "$API/actions/runs/$RID/jobs")
  echo "$J" > /tmp/jobs777.json
  python3 - <<'PY'
import json
d = json.load(open('/tmp/jobs777.json'))
for j in d.get('jobs', []):
    steps = j.get('steps') or []
    ok = sum(1 for s in steps if s.get('conclusion') == 'success')
    cur = next((s['name'] for s in steps if s.get('status') == 'in_progress'), '')
    print("  %-28s %-10s %-8s 成功 %d/%d %s" % (j['name'][:28], j['status'], j['conclusion'], ok, len(steps), cur))
PY
  ST=$(python3 -c "import json;d=json.load(open('/tmp/jobs777.json'));print('done' if all((j.get('status')=='completed') for j in d.get('jobs',[])) and d.get('jobs') else 'run')")
  if [ "$ST" = "done" ]; then
    echo "---- CI 结束, 回读 release ----"
    curl -s -H "Authorization: Bearer $TOK" "$API/releases/tags/v5.50.777" > /tmp/rel777.json
    python3 - <<'PY2'
import json
try:
    d = json.load(open('/tmp/rel777.json'))
except Exception as e:
    print("release 读取失败", e); raise SystemExit
print("release:", d.get('tag_name'), d.get('name'))
for a in d.get('assets', []) or []:
    print("  %-46s %8.1fMB  %s" % (a['name'], a['size']/1048576, a['state']))
    print("    ", a['browser_download_url'])
if not d.get('assets'):
    print("  (无资产)", d.get('message'))
PY2
    exit 0
  fi
  sleep 60
done
echo "轮询超时(90 分钟)"
