#!/usr/bin/env bash
# ss_fw_chain_service.sh — 插拔场景「流形引擎空间智能链」常驻服务启停 (老倪 2026-10-15 联合调试落地)
#
# 把两层接进 **常驻** 引擎回路 (不再只跑联调实例):
#   ① 插拔场景渲染帧服务  127.0.0.1:8799   (tools/fw_render_server.py — RealStateSpaceSim 渲染帧,
#                                          现场相机不在位时的真渲染源)
#   ② 引擎回路 --encoder l4 --l4-frame-url 8799  ⇒ 渲染图进 VLM, 潜表示被流形引擎结构感知 (16 维 · 黎曼度规约束)
#      + --pipeline --pipe-every 10 --pipe-img 8799 ⇒ L5/L4(INTACT)/L3/L2 多层在线, 驱动 L2 原子功能
#
# 用法:  ./tools/ss_fw_chain_service.sh start|stop|restart|status|revert
#        revert = 回到零回归原样 (pca 编码器, 不挂管线) —— 出问题一条命令退回去
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/gui-venv311/bin/python"
PORT="${ZMAX_FW_RENDER_PORT:-8799}"
FRAME="http://127.0.0.1:$PORT/frame.png"
PIPE_EVERY="${ZMAX_FW_PIPE_EVERY:-10}"
LOG=/tmp/ss_fw_chain_service.log
# 锚定整条 cmdline (子串会把助手终端里的诊断命令误判成实例 —— 见 zmax-console 技能「假实例坑」)
RENDER_RE="^[^ ]*gui-venv311/bin/python tools/fw_render_server\.py"
LOOP_RE="^[^ ]*gui-venv311/bin/python tools/ss_engine_loop\.py run.*"

_pids() { pgrep -f "$1" 2>/dev/null | tr '\n' ' '; }

start() {
  if [ -z "$(_pids "$RENDER_RE")" ]; then
    ( cd "$ROOT" && setsid nohup "$PY" tools/fw_render_server.py --port "$PORT" --hz 2 >>"$LOG" 2>&1 & )
    echo "  · 渲染帧服务启动中 (:$PORT)"
    for i in $(seq 1 60); do
      [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$FRAME")" = "200" ] && { echo "  ✅ 渲染帧就绪 (${i}00ms 内)"; break; }
      sleep 0.5
    done
  else echo "  · 渲染帧服务已在跑 (pid $(_pids "$RENDER_RE"))"; fi

  if [ -z "$(_pids "$LOOP_RE")" ]; then
    ( cd "$ROOT" && SS_L4_INTACT=1 SS_INTACT=1 setsid nohup "$PY" tools/ss_engine_loop.py run \
        --hz 10 --encoder l4 --l4-hz 1 --l4-frame-url "$FRAME" \
        --pipeline --pipe-every "$PIPE_EVERY" --pipe-img "$FRAME" >>"$LOG" 2>&1 & )
    echo "  · 引擎回路启动中 (VLM 编码 + 管线每 $PIPE_EVERY 拍)"
  else echo "  · 引擎回路已在跑 (pid $(_pids "$LOOP_RE")) — 要换档先 stop"; fi
  sleep 6; status
}

stop() {
  for re in "$LOOP_RE" "$RENDER_RE"; do
    p="$(_pids "$re")"
    if [ -n "$p" ]; then echo "  · 停 $p"; kill $p 2>/dev/null; sleep 2
      p2="$(_pids "$re")"; [ -n "$p2" ] && { echo "  · 强杀 $p2"; kill -9 $p2 2>/dev/null; }; fi
  done
  echo "✅ 已停 (渲染帧服务 + 引擎回路)"
}

status() {
  re_p="$(_pids "$RENDER_RE")"; lp="$(_pids "$LOOP_RE")"
  echo "  渲染帧服务: ${re_p:-未跑}  $FRAME → $(curl -s --max-time 3 "$FRAME" -o /dev/null -w '%{http_code}' || echo 000)"
  echo "  引擎回路  : ${lp:-未跑}"
  [ -n "$lp" ] && tr '\0' ' ' </proc/${lp%% *}/cmdline 2>/dev/null | sed 's/^/    cmdline: /' && echo
  if [ -f "$ROOT/zmax_data/ss_live/engine_latest.json" ]; then
    "$PY" - "$ROOT/zmax_data/ss_live/engine_latest.json" <<'PYEOF'
import json, os, sys, time
p = sys.argv[1]; e = json.load(open(p, encoding="utf-8"))
print("  引擎真值: 帧龄 %.1fs · cycle %s · task %s · 编码器 %s · 管线 %s(calls %s)"
      % (time.time() - os.path.getmtime(p), e.get("cycle"), e.get("task_id"),
         e.get("encoder"), e.get("pipe_on"), e.get("pipe_calls")))
print("  z_source : %s" % e.get("z_source"))
PYEOF
  fi
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 2; start ;;
  status)  status ;;
  revert)  stop; sleep 2
           ( cd "$ROOT" && setsid nohup "$PY" tools/ss_engine_loop.py run --hz 10 >>"$LOG" 2>&1 & )
           echo "↩ 已回零回归档 (pca 编码器, 不挂管线)"; sleep 5; status ;;
  *) echo "用法: $0 start|stop|restart|status|revert"; exit 2 ;;
esac
