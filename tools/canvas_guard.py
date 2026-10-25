#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_guard.py — 控制台退出时守住画布真源 (2026-10-25)

为什么需要: 控制台退出/另存为会把**内存里的画布**写回真源 ⇒
刚在真源里改的节点名 ('运动规划') 与数据源 (AR场景) 会被旧内存版覆盖回去。
做法: 盯着目标 pid, 一退出就等 3s 让它 flush, 再回读画布; 不一致就按现场口径写回,
      然后跑 space-save + engineering_db build (只补不扩, 不碰别的字段)。
日志: /tmp/canvas_guard.log (每步一行, 不静默)
"""
import json
import os
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "src"))
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 87506
WANT_NAME = "运动规划"
WANT_SRC = "AR场景"
LOG = "/tmp/canvas_guard.log"
MAX_WAIT_S = 6 * 3600


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


log("canvas_guard 启动, 盯 pid=%d (画布名=%s · 数据源=%s)" % (PID, WANT_NAME, WANT_SRC))
t0 = time.time()
while time.time() - t0 < MAX_WAIT_S:
    if not alive(PID):
        log("pid=%d 已退出, 等 3s 让控制台 flush 完" % PID)
        time.sleep(3)
        break
    time.sleep(2)
else:
    log("超过 %ds 还没退出, 放弃盯守 (不改任何东西)" % MAX_WAIT_S)
    raise SystemExit(0)

from lerobot.engineering import flows  # noqa: E402

d, errs = flows.load_canvas()
name_now, src_now = None, None
for n in d.get("nodes") or []:
    p = n.get("params") or {}
    if "bridge_vff" in p:
        name_now = n.get("name")
    if "src_state" in p:
        src_now = p.get("src_state")
log("退出后回读: name=%r src=%r 校验=%s" % (name_now, src_now, "OK" if not errs else errs[:2]))

if name_now == WANT_NAME and src_now == WANT_SRC:
    log("画布没被覆盖, 无需动作")
    raise SystemExit(0)

changed = []
for n in d.get("nodes") or []:
    p = n.get("params") or {}
    if "bridge_vff" in p and n.get("name") != WANT_NAME:
        n["name"] = WANT_NAME
        changed.append("name")
    if "src_state" in p and p.get("src_state") != WANT_SRC:
        p["src_state"] = WANT_SRC
        changed.append("src_state")
if not changed:
    log("没有可改的字段, 退出")
    raise SystemExit(0)
p, bak = flows.save_canvas(d, reason="guard_restore_after_console_exit")
log("已写回 %s · 备份 %s" % (changed, bak))

for cmd in (["tools/project_archive.py", "space-save"], ["tools/engineering_db.py", "build"]):
    r = subprocess.run([os.path.join(REPO, "gui-venv311/bin/python")] + [os.path.join(REPO, c) if i == 0 else c
                                                                         for i, c in enumerate(cmd)],
                       cwd=REPO, capture_output=True, text=True)
    log("%s → rc=%d %s" % (cmd[0].split("/")[-1] + " " + cmd[1], r.returncode,
                           (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else ""))
log("完成")
