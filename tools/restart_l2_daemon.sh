#!/usr/bin/env bash
# 重启 L2 常驻执行器(单实例): 老倪 2026-10-12 现场 —— 「手动回已记的点不再硬拦」的改动要重启才生效。
# 用法: bash tools/restart_l2_daemon.sh
set -u
REPO="/home/ubuntu/zmax"
PY="$REPO/gui-venv311/bin/python"
LOG=/tmp/l2_daemon.out
cd "$REPO" || exit 1

# 1) 按 /proc 精确找执行器(别用 ps|grep 名字: 会匹配到自己这条命令)
PIDS=$(python3 - <<'PY'
import os
me=os.getpid(); up=set(); p=me
while p and p != 1:
    up.add(p)
    try: p=int(open('/proc/%d/stat'%p).read().split(') ',1)[1].split()[1])
    except Exception: break
out=[]
for d in os.listdir('/proc'):
    if not d.isdigit() or int(d) in up: continue
    try: cl=open('/proc/%s/cmdline'%d,'rb').read().decode('utf8','replace').split('\x00')
    except Exception: continue
    if any(x.endswith('l2_daemon.py') for x in cl): out.append(d)
print(" ".join(out))
PY
)
if [ -n "${PIDS:-}" ]; then
  echo "  停旧实例: $PIDS"
  for p in $PIDS; do kill "$p" 2>/dev/null; done
  sleep 2
  for p in $PIDS; do kill -9 "$p" 2>/dev/null; done
fi

# 2) 拉起新实例(与 boot_restore.sh 同口径 + 现场这两个环境变量)
ZMAX_VL_REUSE_S=600 ZMAX_VL_INTENT_WAIT_S=600 setsid nohup "$PY" -u tools/l2_daemon.py >> "$LOG" 2>&1 < /dev/null &
sleep 6

# 3) 核实: 真有且只有一个实例 + 启动行打出来了
N=$(python3 - <<'PY'
import os
n=0
for d in os.listdir('/proc'):
    if not d.isdigit(): continue
    try: cl=open('/proc/%s/cmdline'%d,'rb').read().decode('utf8','replace').split('\x00')
    except Exception: continue
    if any(x.endswith('l2_daemon.py') for x in cl): n+=1
print(n)
PY
)
echo "  现在实例数 = $N"
grep -c "L2 常驻执行器启动" "$LOG" >/dev/null && echo "  启动日志: $(grep 'L2 常驻执行器启动' "$LOG" | tail -1)"
[ "$N" = "1" ] && echo "✅ 重启完成(单实例)" || echo "❌ 实例数异常($N) —— 去看 $LOG"
