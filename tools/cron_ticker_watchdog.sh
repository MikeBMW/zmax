#!/bin/bash
# cron_ticker_watchdog.sh — 独立哨兵: 只看一件事 —— "网关的 cron 心跳还活着吗?"
#
# 为什么必须独立于 cron 本身(2026-10-13 实录, 血):
#   开机时 RTC 比真实时间快 8h, 内核先按 RTC 置钟, NTP 约 30s 后才拨正。这一次网关
#   (01:51:57 起) 在偏掉的时钟下起, cron ticker 只写了**一次**心跳就再没动过 ——
#   而心跳文件里记的是"回拨前"的 epoch(比真实时间晚 8h)。于是:
#     · get_ticker_heartbeat_age() = max(0, now - value) = **0 秒, 永远"新鲜"** ⇒ 任何
#       基于 cron 自身的看门狗都认为一切正常;
#     · 13 个 cron 任务(磁盘红线/推流守护/AOI 看门狗/运动警报/阶梯哨兵)全线静默 23 分钟,
#       next_run 早过点也不点火 —— 而且是**没人会发现**的那种静默。
#   cron 看门狗不能靠 cron 自己看着自己 ⇒ 这里用 systemd user timer(不在 cron 里) 独立巡视。
#
# 判据(任一成立即认为 ticker 死了):
#   ① 心跳缺失 / 已过期 > STALE 秒
#   ② 心跳 epoch 在"未来"超过 120s (时钟被回拨污染的典型特征, 它的 age 是假的 0)
#   ③ 有 enabled 任务的 next_run 已过点 > LATE 秒  ← 最硬的一条: 该点没点
# 动作: 记一行日志 + 重启 gateway user 服务(限流 30 分钟一次), 让 ticker 在正时钟下重起。
# 正常时: 一个字都不打(老倪口径: 没请求不要刷屏)。
set -uo pipefail
HOME_DIR=/home/ubuntu/.hermes
HB=$HOME_DIR/cron/ticker_heartbeat
JOBS=$HOME_DIR/cron/jobs.json
STATE=$HOME_DIR/state/cron_ticker_watchdog.json
LOG=$HOME_DIR/logs/cron_ticker_watchdog.log
HERMES=/home/ubuntu/.local/bin/hermes
STALE=600        # 心跳超过 10 分钟没动 = 死
LATE=300         # 最该跑的任务过点超过 5 分钟 = 该点没点
MIN_GAP=1800     # 两次重启之间至少 30 分钟

log() { mkdir -p "$(dirname "$LOG")"; echo "$(date '+%F %T') $*" >> "$LOG"; }

verdict=$(python3 - "$HB" "$JOBS" "$STALE" "$LATE" <<'PY'
import datetime, json, sys, time
hb, jobs_p, stale, late = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
now = time.time(); out = []
try:
    v = float(open(hb, encoding="utf-8-sig").read().strip())
    if v - now > 120:
        out.append("heartbeat_in_future=%.0fs" % (v - now))     # 回拨污染: age 会是假的 0
    elif now - v > stale:
        out.append("heartbeat_stale=%.0fs" % (now - v))
except Exception as e:
    out.append("heartbeat_unreadable=%s" % e)
try:
    d = json.load(open(jobs_p)); js = d if isinstance(d, list) else d.get("jobs", [])
    ts = [datetime.datetime.fromisoformat(j["next_run_at"]).timestamp() for j in js
          if j.get("enabled") and j.get("state") != "paused" and j.get("next_run_at")]
    if ts and now - min(ts) > late:
        out.append("job_late=%.0fs" % (now - min(ts)))
except Exception as e:
    out.append("jobs_unreadable=%s" % e)
print(" ".join(out))
PY
)
[ -z "$verdict" ] && exit 0          # 健康: 静默退出

# 网关不在跑就别重启了(那是另一类故障)
if ! pgrep -f 'gateway run' >/dev/null 2>&1; then
  log "ticker 异常($verdict) 但没找到 gateway 进程 ⇒ 不动手"
  exit 0
fi

last=0
[ -f "$STATE" ] && last=$(python3 -c "import json;print(int(json.load(open('$STATE')).get('last_restart',0)))" 2>/dev/null || echo 0)
now_i=$(date +%s)
if [ "$last" -gt 0 ] && [ $((now_i - last)) -lt "$MIN_GAP" ]; then
  log "ticker 异常($verdict) 但 ${MIN_GAP}s 限流内(上次重启 $((now_i - last))s 前) ⇒ 只记录"
  exit 0
fi

log "ticker 异常($verdict) ⇒ 重启 gateway 让 ticker 在正时钟下重起"
timeout 300 "$HERMES" gateway restart >>"$LOG" 2>&1
rc=$?
echo "{\"last_restart\": $now_i, \"reason\": \"$verdict\"}" > "$STATE"
log "已请求重启 (hermes gateway restart rc=$rc)"
