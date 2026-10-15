#!/usr/bin/env bash
# 🧹 INTACT 子进程看门狗 (2026-10-15 实测发现): engine loop 每建一个 IntactRuntime 就会 spawn 一个
#   tools/intact_worker.py (每个 ~420 MiB 显存); 旧实例没被 close ⇒ 实测 5 分钟一个新 worker,
#   累积到 7 个就把 8188 MiB 显存吃满 ⇒ **RuntimeError: CUDA error: out of memory** ⇒ 3D 面板/信号页停更。
#   本脚本只做一件事: **保留最新那个 worker, 其余同名旧 worker 全杀** (永不杀最新/永不动别的进程)。
#   真修法 (待办): 让 IntactRuntime 走单例 / 复用已有 worker —— 见 src/lerobot/policies/intact/runtime/model_adapter.py:106。
set -u
KEEP_N="${KEEP_N:-1}"
# etimes = 已存活秒数 ⇒ 升序排 = **最新的排最前**; 只留第 1 个 (最新), 其余旧的全杀
mapfile -t PIDS < <(ps -eo pid,etimes,cmd | grep '[i]ntact_worker.py' | sort -k2 -n | awk '{print $1}')
if [ "${#PIDS[@]}" -le "$KEEP_N" ]; then
    echo "intact_worker 现有 ${#PIDS[@]} 个 (≤${KEEP_N}, 不动) $(date '+%F %T')"
    exit 0
fi
_KILL=("${PIDS[@]:KEEP_N}")            # 保留前 KEEP_N 个 (最新的那几个), 其余旧 worker 全杀
for p in "${_KILL[@]}"; do kill -9 "$p" 2>/dev/null && echo "killed 旧 worker $p"; done
echo "$(date '+%F %T') 现存 worker 数 $(ps -eo cmd | grep -c '[i]ntact_worker.py') · GPU $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
