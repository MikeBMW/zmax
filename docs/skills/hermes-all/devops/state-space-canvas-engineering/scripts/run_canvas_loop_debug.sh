#!/usr/bin/env bash
# 🧪 把一个 systemd 常驻循环起成「可 attach 的调试版」(断点进得去的形态)
#
# 背景: systemd 起的那个进程不带 debugpy, VSCode F5 起的 GUI 进程又不执行这段代码
#       ⇒ UI 断点永远不进 (取证与判别见 references/breakpoint-does-not-hit.md §10)。
#
# 用法:
#   sudo systemctl stop zmax-ss-canvas-loop     # 必须先停; 不停则两进程抢写 live 产物、AR 页面被冻
#   ./tools/run_canvas_loop_debug.sh &          # 本脚本 (或 terminal background=true + persist_on_release=true)
#   VSCode → 调试下拉「🔌 Attach 现有控制台 (5678)」→ F5 → 在目标行打断点
#   验证/收工: scripts/dap_probe_breakpoint.py --path <abs> --line <N>
#             然后在 VSCode Ctrl+F5, 再 sudo systemctl start zmax-ss-canvas-loop
#
# 🔴 env 必须与 `systemctl cat <unit>` 里的 Environment= 逐条一致, 否则调试版的节点集合/频率
#    与在役进程不同, 你调到的行为和用户看到的不是一回事。
cd "$(dirname "$(dirname "$0")")" || exit 1

# ↓ 抄 systemctl cat zmax-ss-canvas-loop 的 Environment 行 (白名单要全, 少一个节点就调不到)
export ZMAX_CANVAS_ONLY="ssplan,ssact,ssyolo,ssdec,ss_grav_h,ssmani_c,ssmani_p,n_calib_mani,ss_mani_eng"
export ZMAX_CANVAS_HZ=10
export ZMAX_UPH_AR_PUB=1
export ZMAX_YOLO_SHARE=1
export PYTHONUNBUFFERED=1

# 不加 --wait-for-client: 进程起来就正常跑, 5678 在听、随时可 attach ⇒ 页面不冻、不逼用户立刻连
# (加了 --wait-for-client 会卡在第一行等 attach, 产物停更, 用户看到的是「画面卡住了」)
exec ./gui-venv311/bin/python -m debugpy --listen 127.0.0.1:5678 tools/ss_canvas_loop.py
