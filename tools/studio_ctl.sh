#!/usr/bin/env bash
# 🎛 studio_ctl.sh — 安全启停 zmax-studio (避免"pkill -f studio.py 杀自己")
#
# 为什么需要: 命令行里出现 "studio.py" 字样时, `pkill -f studio.py` / `ps|grep studio.py`
#   会匹配到**当前这个 shell 自身** → 自杀 (2026-09-24 实测 SIGTERM -15)。
#   本脚本按**解释器绝对路径**精确匹配 (arg0 = .../gui-venv311/bin/python), 且用 argv 数组比较,
#   不含自身命令行里的裸字符串 → 不会自杀。
#
# 用法: bash tools/studio_ctl.sh {status|stop|start|restart}
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUI_DIR="$REPO/tools/gui"
# ⚠️ 坑: venv 在**仓库根** (launch_studio.sh 硬编码 $REPO/gui-venv311/bin/python),
#    不在 tools/gui/ 下 —— 按错的路径匹配会永远报 "stopped" (2026-09-24 实测踩到)
PY=""
for cand in "$REPO/gui-venv311/bin/python" "$GUI_DIR/gui-venv311/bin/python"; do
  [ -x "$cand" ] && PY="$cand" && break
done
[ -n "$PY" ] || { echo "❌ 找不到 gui-venv311 解释器"; exit 1; }

pids() {                       # 宽松精确匹配: cmdline 里同时含 'studio.py' 与 本工程 venv 解释器路径
  # ⚠️ 判断在**脚本文件里**做 (不是命令行), 所以不会像 `pkill -f studio.py` 那样匹配到自己
  python3 - "$PY" <<'PYEOF'
import os, sys, glob
target_dir = sys.argv[1].rsplit("/", 1)[0]          # .../gui-venv311/bin
out = []
for p in glob.glob("/proc/[0-9]*"):
    try:
        with open(os.path.join(p, "cmdline"), "rb") as f:
            argv = [a.decode(errors="ignore") for a in f.read().split(b"\0") if a]
    except Exception:
        continue
    if not argv:
        continue
    # 启动脚本会套 nice/setsid/env → 不假设 argv[1], 只要任一段是解释器且任一段是 studio.py
    # 🔧 2026-10-01 修(老倪「重启」点不动): 原来按**字面路径**比 ⇒ 进程是 /home/ubuntu/zmax/...
    #   起的、脚本算出来是 /home/ubuntu/zmax/...(软链两种写法) ⇒ 永远报 "stopped",
    #   stop/restart 都作用不到 → 老倪点了重启其实没动(实测 pid 一直不变)。
    _tgt = os.path.realpath(target_dir + "/python")
    _ok_py = any((a == target_dir + "/python" or a.startswith(target_dir + "/python")
                  or os.path.realpath(a) == _tgt) for a in argv)
    if _ok_py and any(a.endswith("studio.py") for a in argv):
        out.append(int(os.path.basename(p)))
print(" ".join(str(x) for x in out))
PYEOF
}

# ── 🩺 启动 + 成活自检 + 崩溃留档 + 自动重试一次 (2026-10-10) ─────────────────────────────
# 为什么: 实测**偶发**启动 abort (core dumped) —— 老倪 16:1x 那次 restart 就中招 (v5.39.9),
#   且原写法日志全写 /tmp/studio_launch.log, 被下一次成功启动**覆盖** ⇒ 崩溃现场永远丢。
#   现在: 每次启动日志按时间戳留档 + 起后 25s 自检 + 没成活就抓关键行 + 自动重起一次。
_start_gui() {
  _LOG="/tmp/studio_launch_$(date '+%Y%m%d_%H%M%S').log"
  cd "$GUI_DIR" && DISPLAY=:0 setsid bash launch_studio.sh >"$_LOG" 2>&1 < /dev/null &
  ln -sfn "$_LOG" /tmp/studio_launch.log            # 兼容旧习惯: 永远指向最新那次
  sleep 25
  if [ -z "$(pids)" ]; then
    echo "⚠️ 第 1 次启动未成活 — 崩溃现场关键行:"
    grep -nE "QThread|Aborted|Fatal|Segmentation|Traceback|error" "$_LOG" 2>/dev/null | tail -8
    echo "   现场留存: $_LOG   (core: $(ls -t /var/lib/systemd/coredump/* ${HOME}/zmax/core* 2>/dev/null | head -1 || echo 无))"
    echo "   → 自动重试一次"
    _LOG="/tmp/studio_launch_$(date '+%Y%m%d_%H%M%S')_retry.log"
    cd "$GUI_DIR" && DISPLAY=:0 setsid bash launch_studio.sh >"$_LOG" 2>&1 < /dev/null &
    ln -sfn "$_LOG" /tmp/studio_launch.log
    sleep 25
  fi
  echo "started: $(pids)"
}

case "${1:-status}" in
  status)
    P=$(pids); [ -n "$P" ] && echo "running: $P" || echo "stopped"
    ;;
  stop|restart)
    # 🛑 2026-09-28 老倪两次问「控制台怎么自己重启呢」——真因不是自启(Restart=no, 无 cron 碰它),
    #   而是 **agent 改完代码就重启它**, 现场只看到窗口闪来闪去。加硬闸: 起不到 5 分钟的实例,
    #   stop/restart 一律拒绝, 要重启必须显式 --force; 每次动作都记进 /tmp/studio_ctl.log 可追溯。
    P=$(pids)
    if [ -n "$P" ]; then
      _age=$(ps -o etimes= -p $P 2>/dev/null | tr -d ' ')
      if [ -n "${_age:-}" ] && [ "$_age" -lt 300 ] && [ "${2:-}" != "--force" ] && [ "${2:-}" != "-f" ]; then
        echo "⛔ 拒绝: 控制台才起了 ${_age}s (<300s)。反复重启会让现场看到窗口闪来闪去 (老倪已投诉 2 次)。"
        echo "   确实要重启(比如必须加载新代码): bash $0 restart --force"
        echo "$(date '+%F %T') REFUSED stop pid=$P age=${_age}s arg=${1:-}" >> /tmp/studio_ctl.log
        exit 3
      fi
      echo "$(date '+%F %T') $1 pid=$P age=${_age:-?}s force=${2:-no}" >> /tmp/studio_ctl.log
      kill $P; sleep 4
    fi
    if [ "$1" = "restart" ]; then
      [ -n "$(pids)" ] && { echo "already running: $(pids)"; exit 0; }
      _start_gui
    else
      echo "stopped: ${P:-none}"
    fi
    ;;
  start)
    [ -n "$(pids)" ] && { echo "already running: $(pids)"; exit 0; }
    echo "$(date '+%F %T') start" >> /tmp/studio_ctl.log
    _start_gui
    ;;
  *) echo "用法: $0 {status|stop|start|restart} [--force]" ; exit 2 ;;
esac
