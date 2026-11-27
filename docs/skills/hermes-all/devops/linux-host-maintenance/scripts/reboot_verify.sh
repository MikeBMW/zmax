#!/bin/bash
# 重启后链路自愈核验 (只读) —— linux-host-maintenance §9
#
# 用法: bash reboot_verify.sh [--wait]
#   --wait : 等 /proc/uptime 到 600s 再做第二点网络复采(判"产线网卡真缺失"要 5min+10min 两点)
#
# 本脚本只 print, 不改任何状态。缺的服务按 §9 另跑官方脚本补:
#   bash tools/boot_restore.sh local          # 本机 5 个手工进程
#   terminal(background=true, persist_on_release=true)  # 8795 hil_local_api(§9f③)
#
# 计时一律走 /proc/uptime: `date -d "<绝对时间> + N minutes"` 会把 +N 当@@时区偏移@@(UTC+N:00),
# 算出过去的时间戳 ⇒ 等待循环立刻退出 ⇒ 假造出"已满 10min"的第二点采样。

ROOT=${ZMAX_ROOT:-/home/ubuntu/zmax}
ORIN=${ORIN:-192.168.23.66}
PLANT=${PLANT:-192.168.23.23}
WAIT=0; [ "${1:-}" = "--wait" ] && WAIT=1

up() { awk '{print int($1)}' /proc/uptime; }

net_probe() {
  echo "--- 采样点: 开机 $(up)s · $(date '+%F %T') ---"
  ip -br a | grep -v '^lo'
  ip route | grep -E '192\.168\.23' || echo "  无 192.168.23.x 路由 ⇒ 产线网卡不在位"
  lsusb 2>/dev/null | grep -i -E 'ethernet|asix|rtl815|cdc|rndis' || echo "  lsusb: 无 USB 网卡"
  ping -c1 -W2 "$ORIN"  >/dev/null 2>&1 && echo "  Orin 通"   || echo "  Orin 不通"
  ping -c1 -W2 "$PLANT" >/dev/null 2>&1 && echo "  工控机 通" || echo "  工控机 不通"
}

echo "===== 0. 时间 / 开机 ====="
date '+%F %T %Z'; uptime

echo "===== 1. failed 单元 (应为空) ====="
systemctl --failed --no-legend --no-pager | head -20

echo "===== 2. zmax-*/aoi-* 已启用单元 (逐个 is-enabled; awk '/enabled/' 会把 disabled 也匹配上) ====="
for u in $(systemctl list-unit-files 'zmax-*' 'aoi-*' --no-pager 2>/dev/null | awk '{print $1}'); do
  [ "$(systemctl is-enabled "$u" 2>/dev/null)" = "enabled" ] || continue
  printf '  %-32s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null)"
done

echo "===== 3. 关键端口 + 探活 (有进程 != 在役; 403 也可能是合法拒绝) ====="
ss -ltnp 2>/dev/null | grep -E ':(8790|8791|8793|8795|8797|8798|8891|8893|10082|10083)\b' || echo "  (无匹配)"
for p in 8791 8793 8795 8797 8798; do
  printf '  127.0.0.1:%-5s ' "$p"
  curl -s -o /dev/null -m 4 -w '%{http_code}\n' "http://127.0.0.1:$p/" || echo timeout
done
printf '  8793/station   '; curl -s -o /dev/null -m 4 -w '%{http_code}\n' http://127.0.0.1:8793/station

echo "===== 4. 帧号递增 (推流那格的唯一判据; 隔 8s 两采) ====="
for i in 1 2; do
  curl -s -m 5 http://127.0.0.1:8793/stats | python3 -c "
import sys,json
d=json.load(sys.stdin); c=d.get('cams',d)
for k,v in c.items():
    if isinstance(v,dict):
        print('  %-12s online=%-5s fps=%-5s age=%-10s stalled=%-5s frames=%s'%(
            k,v.get('online'),v.get('fps'),v.get('age_s'),v.get('stalled'),v.get('frames_served')))
" 2>/dev/null || echo "  (8793/stats 读不到)"
  sleep 8
done

echo "===== 5. 本机手工进程 (自启单元管不到的那 5 个 + HIL) ====="
for pat in 'cam_live_stream.py' 'l5_live_mark' 'vl_safety_monitor' 'l2_daemon' 'hil_local_api.py' 'tcp_ar_server' 'studio.py'; do
  printf '  %-20s ' "$pat"; pgrep -af "$pat" | head -1 | cut -c1-110; echo
done
echo "  注: boot_restore.sh check 的 ✓ 只等于'取样那一刻有进程' —— l5_live_mark 还要看 zmax_data/l5live/l5_live_mark.out 的 mtime/存在性"

echo "===== 6. 相机设备解析 (重启后设备号会变) ====="
( cd "$ROOT" 2>/dev/null && python3 tools/cam_dev_resolve.py 2>&1 | head -6 ) || echo "  (解析器跑不了)"

echo "===== 7. 位姿真值 (真实路径是 ~/zmax/zmax_data/... 不是 ~/zmax_data/...) ====="
ls -l --time-style=+%F_%T "$ROOT/zmax_data/rokae_sdk/tcp_out/latest.json" 2>&1

echo "===== 8. cron ticker 心跳 (偏钟下会静默卡死; 双向判活) ====="
now=$(date +%s)
for f in "$HOME/.hermes/cron/ticker_heartbeat" "$HOME/.hermes/cron/ticker_last_success"; do
  if [ ! -e "$f" ]; then echo "  $f : 不存在"; continue; fi
  v=$(tr -d '\n' < "$f")
  python3 - "$f" "$v" "$now" <<'PY'
import sys
f, v, now = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    t = float(v)
except ValueError:
    print("  ? %s : 内容非 epoch (%s)" % (f, v[:40])); raise SystemExit
d = now - t
if d > 600:
    print("  !! %s 心跳过期 %ds (>600)" % (f, int(d)))
elif d < -120:
    print("  !! %s 心跳在未来 %ds (时钟被回拨污染)" % (f, int(-d)))
else:
    print("  ok %s 心跳新鲜 %ds" % (f, int(d)))
PY
done
pgrep -af 'gateway run' >/dev/null && echo "  gateway 进程在" || echo "  !! 无 gateway 进程"

echo "===== 9. 网络 / 外设 (产线网卡) ====="
net_probe
if [ "$WAIT" = 1 ] && [ "$(up)" -lt 600 ]; then
  echo "  --wait: 等到开机满 600s 做第二点复采(按 /proc/uptime 计时, 不用 date -d)"
  while [ "$(up)" -lt 600 ]; do sleep 10; done
  net_probe
  echo "  判据: 两点都查不到 192.168.23.x / 无 USB 网卡 ⇒ 真缺失; 任一点在位 ⇒ 只是开机枚举慢, 别报缺失"
fi

echo "===== 10. 资源 ====="
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,persistence_mode --format=csv,noheader 2>/dev/null || echo "  no-gpu"
df -h / | tail -1
free -h | head -2
echo "===== 完 (只读; 缺的进程按 §9 走 boot_restore.sh local / §9f③ 的 background 起法) ====="
