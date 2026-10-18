#!/bin/bash
# 重启控制台 (2026-10-18): 停旧实例(旧代码, RSS 3.6GB 仍在涨) → 起修复版 → 验证
cd /home/ubuntu/zmax || exit 1
# ⚠️ pgrep -f "studio[.]py" 会匹配到**执行本脚本的 shell** (其命令行含该串) ⇒ kill 会自杀。
#    因此只取 comm 为 python* 的进程 (真正的解释器)。
_pids() {
  local p
  for p in $(pgrep -f "gui/studio[.]py" 2>/dev/null); do
    case "$(cat /proc/$p/comm 2>/dev/null)" in
      python*) echo "$p" ;;
    esac
  done
}
echo "=== ① 停旧实例 ==="
OLD=$(_pids | tr '\n' ' ')
echo "旧 pid: ${OLD:-无}"
for p in $OLD; do kill -TERM "$p" 2>/dev/null; done
sleep 5
for p in $OLD; do kill -KILL "$p" 2>/dev/null; done
sleep 1
if [ -n "$(_pids)" ]; then echo "⚠ 仍有残留: $(_pids)"; else echo "✓ 旧实例已退出"; fi

echo "=== ② 起新实例 (惰性扩容修复版) ==="
mkdir -p zmax_data/ops
export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority
export PYTHONUNBUFFERED=1
# 🐛 2026-10-18 OOM 根治: 限制 glibc arena (默认 8×核数, 每个 64MB 只增不还; 实测 38 个段 ≈2GB)
export MALLOC_ARENA_MAX=4
export MALLOC_TRIM_THRESHOLD_=131072
setsid nohup ./gui-venv311/bin/python tools/gui/studio.py >> zmax_data/ops/studio.log 2>&1 < /dev/null &
sleep 6
NEW=$(_pids | head -1)
echo "新 pid: $NEW"
if [ -z "$NEW" ]; then echo "✗ 启动失败, 看日志:"; tail -20 zmax_data/ops/studio.log; exit 2; fi

echo "=== ③ 等它把界面和数据源拉起来 (40s) ==="
sleep 40
echo "--- 进程 ---"
ps -o pid,etime,rss,nlwp -p $NEW | cat
echo "--- 日志尾 ---"
tail -8 zmax_data/ops/studio.log
