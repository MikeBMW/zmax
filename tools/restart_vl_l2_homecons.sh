#!/usr/bin/env bash
# 家目录整合后的收尾重启(2026-10-07):
#   ① VL 快/慢层看门狗(老进程内存里揣着旧路径字面量, 会静默往老目录写)
#   ② L2 常驻执行器
# 为什么写成脚本: 直接内联 `pgrep -f <模式>` 会匹配到**执行它的 shell 自己**
#    (命令行里出现的名字照样被模式命中) ⇒ 自杀。已踩 5 次。
# 本脚本自带 VERIFY 段: 只看结果, 不看过程。
set -u
REPO=/home/ubuntu/zmax
DATA=$REPO/zmax_data
PY=$REPO/gui-venv311/bin/python
say(){ echo "[$(date +%H:%M:%S)] $*"; }

say "① 停 VL 链"
for p in $(pgrep -f 'vl_safety_keepalive\.sh'); do kill "$p" 2>/dev/null && say "   停 keepalive $p"; done
for p in $(pgrep -f 'tools/vl_safety_monitor\.py'); do kill "$p" 2>/dev/null && say "   停 monitor $p"; done
for p in $(pgrep -f 'tools/vl_safety_fast\.py'); do kill "$p" 2>/dev/null && say "   停 fast $p"; done
sleep 3

say "② 起 VL 链(脱离会话)"
setsid nohup bash /home/ubuntu/.hermes/scripts/vl_safety_keepalive.sh >> "$DATA/vl_safety_keepalive.log" 2>&1 < /dev/null &
sleep 10

say "③ 重启 L2 执行器"
L2=$(pgrep -f "^$PY tools/l2_daemon\.py$" | head -1)
[ -n "$L2" ] && kill "$L2" 2>/dev/null && say "   停 L2 $L2"
sleep 3
timeout 150 bash /home/ubuntu/.hermes/scripts/l2_daemon_keepalive.sh 2>&1 | tail -1
sleep 5

say "──────── 核验 ────────"
for k in vl_safety_keepalive vl_safety_monitor vl_safety_fast; do
  n=$(pgrep -cf "$k")
  [ "$k" = vl_safety_keepalive ] && n=$(pgrep -cf 'vl_safety_keepalive\.sh')
  printf "  %-22s 进程 %s\n" "$k" "$([ "${n:-0}" -gt 0 ] && echo 在跑 || echo 不在)"
done
printf "  L2 执行器              %s\n" "$(pgrep -f "^$PY tools/l2_daemon\.py$" >/dev/null && echo 在跑 || echo 不在)"
echo "  --- VL 落盘位置(新路径应新鲜) ---"
for p in "$DATA/vl_safety_fast.json" "$DATA/vl_safety.json"; do
  [ -e "$p" ] && printf "    %-30s %s\n" "$(basename "$p")" "$(stat -c '%y' "$p" | cut -c12-19)"
done
[ -e /home/ubuntu/zmax_data ] && echo "    ⚠️ 老目录又冒出来了: $(ls /home/ubuntu/zmax_data | head -3 | tr '\n' ' ')" || echo "    ✅ 老目录不存在"
echo "  --- 臂真值 ---"
"$PY" -c "
import json,time
d=json.load(open('$DATA/rokae_sdk/tcp_out/latest.json'))
print('    帧龄 %.2fs  pos=(%.4f,%.4f,%.4f)' % (time.time()-d.get('ts',0), d.get('x',0), d.get('y',0), d.get('z',0)))"
say "完成"
