#!/bin/bash
# 内存救援 (2026-10-18): 释放 20GB 泄漏的控制台 GUI + 崩溃循环容器 + 重置 swap
# 前提已核实: ①studio.py 无子进程 (纯显示层) ②引擎/采样/总线/桥 全部 ppid=1 独立守护
#            ③两个容器在 Restarting 崩溃循环 (0B 占用, 一会儿连真机再起)
set -x
echo "=== 前 ==="; free -m | head -3

# 1) 停崩溃循环容器 (不删, 连真机时再 start)
sudo docker stop rokae_tcp_sampler zmax-sdk-arm-agent 2>/dev/null || true

# 2) 关掉 20.2GB RSS + 8.5GB swap 的控制台 GUI (debugpy launcher + 其子进程)
kill -TERM 1504917 1505039 2>/dev/null || true
sleep 8
kill -KILL 1504917 1505039 2>/dev/null || true
sleep 2

# 3) 回收页缓存
sync
echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null 2>&1 || true

# 4) 重置 swap (清掉泄漏进程压在 swap 里的死页)
sudo swapoff -a 2>/dev/null && sudo swapon -a 2>/dev/null || echo "swap reset skipped"

echo "=== 后 ==="; free -m | head -3
echo "=== 在役守护仍在? ==="
for p in $(pgrep -f "ss_engine_loop[.]py|sam3_seg[.]py --serve|tdrive_bus[.]py|hil_bridge[.]py --watch"); do
  printf "pid=%s %s\n" "$p" "$(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-64)"
done
