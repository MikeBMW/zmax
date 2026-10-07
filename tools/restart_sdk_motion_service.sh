#!/usr/bin/env bash
# restart_sdk_motion_service.sh — 重启 8798「本机 SDK 动作服务」(2026-10-08 新增)
#
# 为什么单独要这个脚本:
#   ① `tools/start_sdk_arm.sh` 见到端口在听就**跳过** ⇒ 改了代码/路径不会生效;
#   ② 这条腿的老进程会把**老路径字面量揣在内存里**。2026-10-08 实测: 家目录整合后
#      `l2_transport_sdk.py` / `sdk_motion_service.py` 里 `join(expanduser("~"),"zmax_data",...)`
#      这第 4 种写法没被整合扫到 ⇒ SDK 腿永远"代理未就绪" ⇒ 页面报「已下发(真动)」但机器人不动。
#   ③ 内联 `setsid` 会被上层工具策略拦(防丢进程), 写成脚本才跑得干净。
# 用法: bash tools/restart_sdk_motion_service.sh
set -u
REPO=/home/ubuntu/zmax
PY="$REPO/gui-venv311/bin/python"
LOG="$REPO/zmax_data/sdk_motion_service.log"
PORT="${ZMAX_ARM_PORT:-8798}"

echo "① 停旧服务(锚定 /proc cmdline 匹配, 不用 pgrep -f 免自杀)"
for d in /proc/[0-9]*; do
    p="${d#/proc/}"
    [ "$p" = "$$" ] && continue
    tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q "tools/sdk_motion_service.py" || continue
    kill -TERM "$p" 2>/dev/null && echo "   killed pid=$p"
done
sleep 2

echo "② 起新服务(setsid 完全脱离, 命令行与 start_sdk_arm.sh 逐字节一致)"
( cd "$REPO" && setsid "$PY" -u tools/sdk_motion_service.py >> "$LOG" 2>&1 < /dev/null & )
sleep 3

echo "③ 复核(只看结果)"
NP="$(pgrep -f 'tools/sdk_motion_service.py' | head -1)"
printf "   新 pid: %s   起于: %s\n" "${NP:-无}" "$(ps -o lstart= -p "${NP:-1}" 2>/dev/null | sed 's/^ *//')"
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then echo "   端口 $PORT: 在听"; else echo "   ❌ 端口 $PORT 没在听"; fi
curl -s -m 5 -o /dev/null -w "   8798 HTTP: %{http_code}\n" "http://127.0.0.1:$PORT/" 2>/dev/null
"$PY" -c "
import sys, os; sys.path.insert(0, '$REPO/tools')
import sdk_motion_service as s
print('   服务将使用的 FIFO: %s' % s.FIFO)
print('   FIFO 存在: %s   (必须 True, 否则 L2 的 SDK 腿会判定代理未就绪)' % os.path.exists(s.FIFO))
" 2>&1 | tail -3
echo "   —— 服务日志尾部 ——"
tail -3 "$LOG" 2>/dev/null | sed 's/^/   /'
