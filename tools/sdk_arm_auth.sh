#!/usr/bin/env bash
# sdk_arm_auth.sh — 本机 SDK 直连动作的**现场授权**入口 (只能从命令行给, 页面不能自助授权)
# 口径: 授权 = 现场人口头确认 + 这里落一条带 TTL/次数上限的记录; 到期/用完自动失效; 撤销随时。
# 用法:
#   bash tools/sdk_arm_auth.sh --status
#   bash tools/sdk_arm_auth.sh --ttl 1800 --uses 30 --by "老倪(现场)" --note "现场确认安全"
#   bash tools/sdk_arm_auth.sh --revoke
set -euo pipefail
AUTH="$HOME/zmax/zmax_data/sdk_arm_auth.json"

case "${1:-}" in
  --status|"")
    python3 - "$AUTH" <<'PY'
import json, os, sys, time
p = sys.argv[1]
try:
    a = json.load(open(p, encoding="utf-8"))
except Exception:
    print("授权文件不存在: %s  (未授权)" % p); raise SystemExit(0)
left = a.get("ttl_s", 0) - (time.time() - a.get("ts", 0))
print("enabled=%s 剩余=%.0fs 次数=%s/%s by=%s note=%s 授予于=%s 撤销于=%s"
      % (a.get("enabled"), max(0, left), a.get("used"), a.get("max_uses"), a.get("by"),
         a.get("note"), a.get("t"), a.get("revoked_str")))
PY
    ;;
  --revoke)
    python3 - "$AUTH" <<'PY'
import json, os, sys, time
p = sys.argv[1]
a = {}
if os.path.exists(p):
    a = json.load(open(p, encoding="utf-8"))
a.update({"enabled": False, "revoked_ts": time.time(), "revoked_str": time.strftime("%F %T")})
tmp = p + ".tmp"; json.dump(a, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, p)
print("已撤销: %s" % p)
PY
    ;;
  --ttl)
    TTL="${2:-1800}"; USES="${4:-30}"; BY="${6:-老倪(现场)}"; NOTE=""
    shift 2 || true
    # 允许 --by / --note 任意顺序
    while [ $# -gt 0 ]; do
      case "$1" in
        --by) BY="$2"; shift 2 ;;
        --note) NOTE="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    python3 - "$AUTH" "$TTL" "$USES" "$BY" "$NOTE" <<'PY'
import json, os, sys, time
p, ttl, uses, by, note = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
a = {}
if os.path.exists(p):
    try:
        a = json.load(open(p, encoding="utf-8"))
    except Exception:
        a = {}
now = time.time()
a.update({"enabled": True, "ts": now, "ts_str": time.strftime("%F %T", time.localtime(now)),
          "ttl_s": ttl, "max_uses": uses, "used": 0, "by": by, "note": note,
          "epoch": int(a.get("epoch", 0)) + 1})
tmp = p + ".tmp"
json.dump(a, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(tmp, p)
os.chmod(p, 0o600)
print("已授权: %s + %.0fs (到期 %s) · 上限 %d 次 · by=%s"
      % (a["ts_str"], ttl, time.strftime("%H:%M:%S", time.localtime(now + ttl)), uses, by))
PY
    bash "$(dirname "$0")/sdk_arm_auth.sh" --status
    ;;
  *)
    echo "用法: $0 [--status | --revoke | --ttl 1800 --uses 30 --by \"老倪(现场)\" --note \"...\"]" >&2
    exit 2 ;;
esac
