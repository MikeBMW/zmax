#!/usr/bin/env bash
# ci_watch_release.sh <tag> [sha-prefix]
# 轮询 Build Desktop(Windows .exe + macOS .app) 到 completed, 再回读 release 资产。
# 用法(后台跑, 不要前台 sleep): terminal(background=true, notify=true) bash ci_watch_release.sh v5.50.773 05c89995
# 无 gh 也行: token 从 git 凭据库取, 全程走 REST。
set -uo pipefail
TAG=${1:?用法: ci_watch_release.sh <tag> [sha8]}
SHA=${2:-}
REPO=$(git config --get remote.origin.url 2>/dev/null | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?$#\1#')
[ -z "$REPO" ] && { echo "✗ 取不到 owner/repo(在仓库目录里跑)"; exit 1; }
OWNER=${REPO%%/*}
TOK=$(printf "protocol=https\nhost=github.com\nusername=%s\n\n" "$OWNER" | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2)
[ -z "$TOK" ] && { echo "✗ 取不到 GitHub token"; exit 1; }
API="https://api.github.com/repos/$REPO"
PY=./gui-venv311/bin/python; [ -x "$PY" ] || PY=python3

json() { $PY -c "$1"; }

for i in $(seq 1 80); do
  RUN=$(curl -s -H "Authorization: Bearer $TOK" "$API/actions/runs?per_page=20" | $PY -c "
import json,sys
sha='$SHA'; tag='$TAG'
for r in json.load(sys.stdin).get('workflow_runs',[]):
    if sha and r.get('head_sha','').startswith(sha): print('%s|%s|%s'%(r['id'],r['name'],r['status'])); break
    if not sha and tag in (r.get('display_title') or ''): print('%s|%s|%s'%(r['id'],r['name'],r['status'])); break
")
  if [ -z "$RUN" ]; then echo "[$i] 还没找到 run(队列延迟)"; sleep 30; continue; fi
  RID=${RUN%%|*}; RNAME=$(echo "$RUN"|cut -d'|' -f2); RST=$(echo "$RUN"|cut -d'|' -f3)
  JOBS=$(curl -s -H "Authorization: Bearer $TOK" "$API/actions/runs/$RID/jobs" | $PY -c "
import json,sys
out=[]
for j in json.load(sys.stdin).get('jobs',[]):
    steps=j.get('steps') or []
    cur=next((s.get('name') for s in steps if s.get('status') in ('in_progress','queued')), '')
    ok=sum(1 for s in steps if s.get('conclusion')=='success')
    out.append('%s: %s/%s %s/%s %s'%(j.get('name'), j.get('status'), j.get('conclusion') or '-', ok, len(steps), cur[:40]))
print(' | '.join(out))
")
  echo "[$i] run=$RID($RNAME) status=$RST · $JOBS"
  if [ "$RST" = "completed" ]; then
    echo "── run 完成, 回读 release ──"
    curl -s -H "Authorization: Bearer $TOK" "$API/releases/tags/$TAG" | $PY -c "
import json,sys
d=json.load(sys.stdin)
if 'assets' not in d: print('release 还没建:', d.get('message')); raise SystemExit(1)
print('release:', d.get('name'), d.get('published_at'))
for a in d['assets']: print('  %-52s %8.1f MB  %s'%(a['name'], a['size']/1048576.0, a['state']))
"; exit $?
  fi
  sleep 30
done
echo "✗ 40 分钟仍未完成: $API/actions"; exit 1
