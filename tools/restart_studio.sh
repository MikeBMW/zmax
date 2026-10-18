#!/bin/bash
# 重启控制台 (2026-10-18): 停旧实例(旧代码, RSS 3.6GB 仍在涨) → 起修复版 → 验证
cd /home/ubuntu/zmax || exit 1
# ⚠️ pgrep -f "studio[.]py" 会匹配到**执行本脚本的 shell** (其命令行含该串) ⇒ kill 会自杀。
#    因此只取 comm 为 python* 的进程 (真正的解释器)。
_pids() {
  local p cwd
  # 🔴 2026-10-18: 原模式 "gui/studio[.]py" 只匹配 `tools/gui/studio.py`,
  #   漏掉**以 cwd=tools/gui 用裸 `studio.py` 启动**的实例 (实测: VSCode F5 / 手工启动) ⇒
  #   清理时永远留下一个旧进程, 于是「N 个实例并存、用户看的是旧那个、改了看不到」。
  #   现在按 cmdline 认 studio.py + 按 cwd 认工程目录, comm 必须是 python* (防匹配到本 shell)。
  for p in $(pgrep -f "studio[.]py" 2>/dev/null); do
    case "$(cat /proc/$p/comm 2>/dev/null)" in
      python*) ;;
      *) continue ;;
    esac
    cwd=$(readlink /proc/$p/cwd 2>/dev/null)
    case "$cwd" in
      /home/ubuntu/zmax|/home/ubuntu/zmax/tools/gui) echo "$p" ;;
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
