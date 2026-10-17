#!/bin/bash
# 重启技能派发发布器 (只写 zmax_data/ss_live/skill_*.json, 不碰真机动作)
# 安全要点:
#   ① 只杀 comm 以 python 开头的进程 —— 否则会把自己这个 bash 包装杀掉 (踩过两次);
#   ② 保证只剩 1 个实例 —— 多实例同时写 skill_phys.json 会让 schema 回退 (a/b/c 被覆盖没);
set -u
TARGET="tools/ss_skill_dispatch.py"

list_py() {
  for p in $(pgrep -f "$TARGET" 2>/dev/null); do
    c=$(cat "/proc/$p/comm" 2>/dev/null || true)
    case "$c" in
      python*) tr "\0" " " < "/proc/$p/cmdline" 2>/dev/null | grep -q "$TARGET" && echo "$p" ;;
    esac
  done
}

for p in $(list_py); do kill "$p" 2>/dev/null; done
for i in $(seq 1 25); do
  [ -z "$(list_py)" ] && break
  sleep 0.2
done
for p in $(list_py); do kill -9 "$p" 2>/dev/null; done

cd /home/ubuntu/zmax || exit 1
setsid nohup ./gui-venv311/bin/python "$TARGET" --hz 60 \
  >> /home/ubuntu/.hermes/cache/scratch/skill_dispatch.log 2>&1 &
sleep 3
echo "现在实例数=$(list_py | wc -l) pids=[$(list_py | tr '\n' ' ')]"
