#!/usr/bin/env bash
# ar_aoi_bus_ctl.sh — AR/AOI 信号总线 (ar_aoi_bus.py) 常驻拉取器 起/停/看
#
# 为什么要有它: 「信号分析对应 AR 场景下的所有空间点位」要**活着** —— 点位/TCP 真值/RealSense 相机系
# 是外部真源, 得有人周期性地读进总线文件 (zmax_data/ar_live/ar_aoi_live.json), 信号分析页才有实时值。
# 画布节点「🔍 光学质量检测」自己发的话题是节点执行时**顺带**并进同一个文件的 (publish 合并, 不互相覆盖)。
#
# 用法: tools/ar_aoi_bus_ctl.sh start|stop|status|once   (once = 拉一次就退, 调试用)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/gui-venv311/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
RUN="$ROOT/zmax_data/ar_live"
PID="$RUN/ar_aoi_bus.pid"
LOG="$RUN/ar_aoi_bus.log"
mkdir -p "$RUN"
INTERVAL="${ZMAX_AR_AOI_INTERVAL:-2}"

_alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }

case "${1:-status}" in
  start)
    if _alive; then echo "已在跑 (pid $(cat "$PID"))"; exit 0; fi
    cd "$ROOT" || exit 2
    nohup setsid "$PY" tools/ar_aoi_bus.py watch --interval "$INTERVAL" >>"$LOG" 2>&1 &
    echo $! > "$PID"
    sleep 3
    if _alive && [ -f "$RUN/ar_aoi_live.json" ]; then
      echo "✅ 已启动 (pid $(cat "$PID"), 间隔 ${INTERVAL}s) · 总线 $(stat -c %y "$RUN/ar_aoi_live.json" | cut -d. -f1)"
    else
      echo "❌ 启动失败 —— 最后 15 行日志:"; tail -15 "$LOG"; exit 3
    fi
    ;;
  stop)
    if _alive; then kill "$(cat "$PID")" && echo "已停 (pid $(cat "$PID"))"; else echo "本来就没跑"; fi
    rm -f "$PID"
    ;;
  status)
    if _alive; then
      echo "运行中 (pid $(cat "$PID"))"
      "$PY" tools/ar_aoi_bus.py show 2>/dev/null | head -12
    else
      echo "未运行 (文件可能仍是上次拉的: $RUN/ar_aoi_live.json)"
    fi
    ;;
  once)
    cd "$ROOT" || exit 2
    "$PY" tools/ar_aoi_bus.py pull
    ;;
  *) echo "用法: $0 start|stop|status|once"; exit 2 ;;
esac
