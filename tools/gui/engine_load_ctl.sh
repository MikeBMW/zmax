#!/usr/bin/env bash
# ============================================================
# engine_load_ctl.sh — 引擎/渲染服务的负载开关 (2026-10-17)
#
# 为什么有它: 老倪「鼠标延迟很大, 配置中心拖动侧栏好几秒才动」——实测真因:
#   `ss_engine_loop.py` 常驻 10Hz 把 **GPU 算力吃到 70~80%**, 桌面合成(Xorg)只剩 3~9%
#   ⇒ 窗口拖动/鼠标响应被饿死。`fw_render_server.py`(2Hz) 另外吃 ~160% CPU。
#   两者都是常驻服务(不是 GUI 本身的问题), 现场相机不在位时给 VLM 喂渲染帧用。
#
# 用法:
#   bash tools/gui/engine_load_ctl.sh status    # 看现在谁在跑 + GPU 占用 (只读)
#   bash tools/gui/engine_load_ctl.sh pause     # 全停 ⇒ 立刻释放 GPU (演示/看画面时再 resume)
#   bash tools/gui/engine_load_ctl.sh resume    # 按原参数恢复 (10Hz 满速)
#   bash tools/gui/engine_load_ctl.sh light     # 低负载恢复 (引擎 3Hz / 渲染 1Hz) ⇒ 边看边不卡
# ============================================================
set -u
ROOT=/home/ubuntu/zmax
PY="$ROOT/gui-venv311/bin/python"
RENDER_LOG=/tmp/zmax_fw_render.log
ENGINE_LOG=/tmp/zmax_engine_loop.log

# 按 /proc/*/cmdline 找 pid —— 不用 pgrep -f (本脚本名里含关键字, 会匹配到自己)
_pids() {
    local pat="$1" p out=""
    for p in $(ls /proc | grep -E '^[0-9]+$'); do
        [ -r "/proc/$p/cmdline" ] || continue
        if tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q -- "$pat"; then
            [ "$p" = "$$" ] && continue
            out="$out $p"
        fi
    done
    echo "$out"
}
_engine_pids() { _pids "tools/ss_engine_loop.py"; }
_render_pids() { _pids "tools/fw_render_server.py"; }

_gpu() {
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu \
        --format=csv,noheader 2>/dev/null | sed 's/^/  GPU: /'
    nvidia-smi pmon -c 1 -s u 2>/dev/null | tail -n +3 | awk '{printf "  sm %-4s pid %-8s %s\n", $4, $2, $NF}' | head -6
}

_status() {
    echo "=== 引擎/渲染服务 ==="
    local e r
    e="$(_engine_pids)"; r="$(_render_pids)"
    [ -n "$e" ] && echo "  ss_engine_loop   pid$e 运行中" || echo "  ss_engine_loop   未运行"
    [ -n "$r" ] && echo "  fw_render_server pid$r 运行中" || echo "  fw_render_server 未运行"
    echo "=== GPU ==="
    _gpu
}

_pause() {
    local p
    for p in $(_engine_pids); do echo "  停引擎 pid=$p"; kill "$p" 2>/dev/null; done
    sleep 2
    for p in $(_render_pids); do echo "  停渲染服务 pid=$p"; kill "$p" 2>/dev/null; done
    sleep 2
    echo "已停。GPU 现在:"
    _gpu
}

_engine_args() {                       # $1 = hz , $2 = 渲染 hz
    echo "run --hz $1 --encoder l4 --l4-hz 1 --l4-frame-url http://127.0.0.1:8799/frame.png --pipeline --pipe-every 10 --pipe-img http://127.0.0.1:8799/frame.png"
}

_resume() {                            # $1 = 引擎 hz (默认 10), $2 = 渲染 hz (默认 2)
    local hz="${1:-10}" rhz="${2:-2}"
    [ -n "$(_render_pids)" ] || {
        echo "  起 fw_render_server (--hz $rhz)"
        ( cd "$ROOT" && setsid nohup "$PY" tools/fw_render_server.py --port 8799 --hz "$rhz" \
            >> "$RENDER_LOG" 2>&1 < /dev/null & )
        sleep 4
    }
    if [ -n "$(_engine_pids)" ]; then
        echo "  引擎已在跑 (要改频率先 pause)"
    else
        echo "  起 ss_engine_loop (--hz $hz)"
        ( cd "$ROOT" && setsid nohup "$PY" tools/ss_engine_loop.py $(_engine_args "$hz" "$rhz") \
            >> "$ENGINE_LOG" 2>&1 < /dev/null & )
        sleep 5
    fi
    _status
}

case "${1:-status}" in
    status) _status ;;
    pause)  _pause ;;
    resume) _resume "${2:-10}" "${3:-2}" ;;
    light)  _pause >/dev/null 2>&1; _resume "${2:-3}" "${3:-1}" ;;
    *) sed -n '2,18p' "$0" ;;
esac
