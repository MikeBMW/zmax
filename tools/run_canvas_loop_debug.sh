#!/usr/bin/env bash
# 🧪 状态空间常驻循环 · 可 attach 的调试版 (替代 systemd 的 zmax-ss-canvas-loop)
#
# 用途: 让「状态空间常驻循环」这个进程能在 VSCode 里打断点 (execution.py:111 等)。
# 背景: systemd 起的那个进程不带 debugpy, VSCode 的 studio.py 进程又不跑这段代码
#       ⇒ 断点永远不进 (2026-10-30 实测, 取证见 skills/.../breakpoint-does-not-hit.md §10)。
#
# 用法:
#   sudo systemctl stop zmax-ss-canvas-loop      # 必须先停, 否则两个进程抢写 ar_cmd.json
#   ./tools/run_canvas_loop_debug.sh &           # 或者用本脚本同名后台方式
#   VSCode → 调试下拉「🔌 Attach 现有控制台 (5678)」→ F5
#   在 execution.py:111 打断点 ⇒ 每 100ms 停一次
#   收工: Ctrl+F5, 然后 sudo systemctl start zmax-ss-canvas-loop
#
# env 与 systemd unit 保持一致 (systemctl cat zmax-ss-canvas-loop 对账)。
cd /home/ubuntu/zmax || exit 1
export ZMAX_CANVAS_ONLY="ssplan,ssact,ssyolo,ssdec,ss_grav_h,ssmani_c,ssmani_p,n_calib_mani,ss_mani_eng"
export ZMAX_CANVAS_HZ=10
export ZMAX_UPH_AR_PUB=1
export ZMAX_YOLO_SHARE=1
export PYTHONUNBUFFERED=1
exec ./gui-venv311/bin/python -m debugpy --listen 127.0.0.1:5678 tools/ss_canvas_loop.py
